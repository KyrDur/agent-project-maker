import asyncio
import json
import os
from pathlib import Path
from secrets import token_hex
import shutil
from fastapi.testclient import TestClient
import pytest
from experiments.api import configure
from experiments.canonical import digest,encoded
from experiments.providers import ProviderConfig
from experiments.runtime import ProcessRuntime
from experiments.smoke import run_smoke,smoke_cases
from experiments.store import JsonStore
from test_experiment_service import setup,baseline
from test_provider_sessions import local_provider
from test_openai_chat import chat_provider

@pytest.mark.parametrize('provider',['anthropic-compatible','openai-compatible'])
def test_four_case_bounded_chain_smoke_with_actual_local_http(tmp_path,provider):
    service,_,_=setup(tmp_path,runtime=ProcessRuntime())
    with (chat_provider() if provider=='openai-compatible' else local_provider()) as (url,state):
        report=asyncio.run(run_smoke(service,ProviderConfig(provider=provider,base_url=url,model='smoke',
                                    max_tokens=256,max_calls=48),token_hex(24)))
        assert report['chain_verified'] and report['case_count']==4 and report['successful_tool_calls']>0
        assert report['quality_claim'] is False and report['run_call_count']<=48
        assert service.providers.get(report['provider_session_id']).status=='DELETED'
        assert report['tool_call_capability']=='VERIFIED'
        assert len(state['calls'])==report['connection_call_count']+report['tool_probe_call_count']+report['run_call_count']
        assert len(smoke_cases()[2]['turns'])==2
        assert smoke_cases()[3]['executable_rules']


def test_role_overrides_inherit_each_user_parameter_across_restart(tmp_path):
    service,_,_=setup(tmp_path)
    session=service.providers.create(ProviderConfig(provider='openai-compatible',model='default-user',
        temperature=.4,max_tokens=300,role_overrides={'judge':{'model':'judge-user'},'intent':{'temperature':.2}}),token_hex(24))
    restored=JsonStore(tmp_path/'store').get('provider_sessions',session.provider_session_id).configuration
    assert restored.resolved()['judge']=={'model':'judge-user','temperature':.4,'max_tokens':300}
    assert restored.resolved()['intent']=={'model':'default-user','temperature':.2,'max_tokens':300}
    assert restored.resolved()['general']=={'model':'default-user','temperature':.4,'max_tokens':300}
    from experiments.snapshots import capture
    from evaluation.config import EvaluationConfig
    snap=capture(service.skills.manager,EvaluationConfig(),provider_config=restored)
    assert snap['inference_config_snapshot']['parameter_inheritance']['judge']=={
        'model':'explicit_override','temperature':'user_default','max_tokens':'user_default'}


def test_old_sealed_run_absent_provider_defaults_keeps_original_hash_and_bytes(tmp_path):
    service,ev,_=setup(tmp_path)
    run=baseline(service,ev)
    path=service.store.path('runs',run.run_id)
    data=json.loads(path.read_text())['artifact']
    for field in ('provider_session_id','provider_configuration_snapshot','provider_readiness_snapshot','provider_observations','provider_call_count'):
        data.pop(field)
    data['artifact_hash']=digest({k:v for k,v in data.items() if k!='artifact_hash'})
    path.write_bytes(encoded({'artifact':data,'sha256':digest(data)}))
    before=path.read_bytes()
    restored=JsonStore(tmp_path/'store').get('runs',run.run_id)
    assert restored.artifact_hash==data['artifact_hash'] and restored.provider_session_id is None
    assert path.read_bytes()==before


def test_standalone_api_boots_without_server_keys_redis_or_chroma_and_drops_keys(tmp_path,monkeypatch):
    from api import main
    from experiments.app import app
    service,_,_=setup(tmp_path)
    monkeypatch.setenv('ECHOMIND_SKILL_DIR',str(service.skills.manager.root_dir))
    monkeypatch.setenv('ECHOMIND_EXPERIMENT_DIR',str(tmp_path/'standalone-store'))
    monkeypatch.delenv('ANTHROPIC_API_KEY',raising=False);monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    def forbidden(*a,**k):raise AssertionError('Online/RAG runtime must not be initialized')
    monkeypatch.setattr(main,'_anthropic_cfg',forbidden)
    sentinel=object()
    monkeypatch.setattr(main,'_memory',sentinel)
    monkeypatch.setattr(main,'_tool_manager',sentinel)
    key=token_hex(24)
    try:
        with local_provider() as (url,state):
            with TestClient(app) as client:
                response=client.post('/experiments/provider-sessions',json={'model':'user','base_url':url,'api_key':key})
                assert response.status_code==200 and key not in response.text
                sid=response.json()['provider_session_id']
                assert client.post(f'/experiments/provider-sessions/{sid}/test').json()['status']=='SUCCESS'
                ev=client.post('/experiments/evalsets',json={'dialog_cases':[{'case_id':'a','input':'退款'}]}).json()
                run=client.post('/experiments/runs',json={'eval_set_id':ev['eval_set_id'],'provider_session_id':sid})
                assert run.status_code==200 and run.json()['status']=='COMPLETE' and key not in run.text
                assert client.get(f"/experiments/runs/{run.json()['run_id']}").status_code==200
                vault=app.state.experiments.providers._keys
                assert sid in vault
            assert vault=={}
            assert main._memory is sentinel and main._tool_manager is sentinel
            with TestClient(app) as client:
                assert client.get(f'/experiments/provider-sessions/{sid}').json()['status']=='CREDENTIAL_UNAVAILABLE'
                before=len(state['calls'])
                failed=client.post('/experiments/runs',json={'eval_set_id':ev['eval_set_id'],'provider_session_id':sid}).json()
                assert failed['status']=='FAILED' and 'CREDENTIAL_UNAVAILABLE' in failed['warnings']
                assert len(state['calls'])==before
        assert all(key not in p.read_text() for p in (tmp_path/'standalone-store').rglob('*.json'))
    finally:configure(main._experiments)

@pytest.mark.parametrize('endpoint',['https://example.invalid:bad','https://user:secret@example.invalid',
                                     'https://example.invalid?api_key=secret','https://example.invalid\n'])
def test_invalid_endpoint_rejected_without_request(endpoint):
    with pytest.raises(ValueError):ProviderConfig(model='x',base_url=endpoint)


def test_real_provider_smoke_explicit_opt_in_only(tmp_path):
    if os.getenv('ECHOMIND_REAL_PROVIDER_TEST')!='1':
        pytest.skip('Real Provider smoke test not executed: explicit opt-in absent')
    key=os.getenv('ECHOMIND_SMOKE_API_KEY')
    if not key:
        pytest.skip('Real Provider smoke test not executed: explicit smoke credential absent')
    model=os.getenv('ECHOMIND_SMOKE_MODEL')
    if not model:
        pytest.skip('Real Provider smoke test not executed: explicit model absent')
    # Never discover or fall back to server OPENAI_API_KEY/ANTHROPIC_API_KEY.
    try:
        from core.skill_loader import SkillManager
        from experiments.service import ExperimentService
        root=Path(__file__).resolve().parents[1]
        shutil.copytree(root/'skills',tmp_path/'skills')
        manager=SkillManager(str(tmp_path/'skills'));manager.load_strict()
        service=ExperimentService(JsonStore(tmp_path/'store'),manager)
        provider=os.getenv('ECHOMIND_SMOKE_PROVIDER','openai-compatible')
        config=ProviderConfig(provider=provider,model=model,base_url=os.getenv('ECHOMIND_SMOKE_BASE_URL'),
            completion_token_parameter=os.getenv('ECHOMIND_SMOKE_TOKEN_PARAMETER','max_completion_tokens'),
            max_tokens=256,timeout_seconds=30,max_calls=48)
        report=asyncio.run(run_smoke(service,config,key))
        if not report['chain_verified']:pytest.fail('Real Provider chain smoke failed; no quality conclusion',pytrace=False)
    except Exception:
        pytest.fail('Real Provider chain smoke failed; provider exception details suppressed',pytrace=False)
