"""Phase 3C sealing: credential metadata and independently bounded tool probes."""
import asyncio
import hashlib
import json
from secrets import token_hex
import pytest
import httpx
from fastapi.testclient import TestClient
from fastapi import FastAPI
from api import main
from experiments.api import configure,router,install_validation_handler
from experiments.canonical import digest,encoded
from experiments.providers import ProviderConfig,ProviderFailure,ProviderSessions
from experiments.provider_transport import ObservedProvider
from experiments.runtime import ProcessRuntime
from experiments.store import JsonStore
from test_experiment_service import setup,confirmed
from test_provider_sessions import local_provider,ready
from test_openai_chat import chat_provider

def api_client():
    # Route contract only; the independent experiments.app lifecycle is covered
    # by test_provider_smoke_app, without starting the historical online RAG API.
    app=FastAPI();app.include_router(router);install_validation_handler(app)
    return TestClient(app)


def test_public_session_presence_without_stable_key_identifier(tmp_path):
    service,_,_=setup(tmp_path)
    key=token_hex(24);fingerprint=hashlib.sha256(key.encode()).hexdigest()[:12]
    a=service.providers.create(ProviderConfig(model='user'),key)
    b=service.providers.create(ProviderConfig(model='user'),key)
    assert a.provider_session_id!=b.provider_session_id
    configure(lambda:service)
    try:
        with api_client() as client:
            for session in (a,b):
                body=client.get('/experiments/provider-sessions/'+session.provider_session_id).json()
                assert body['credential_status']=='PRESENT'
                assert 'masked_fingerprint' not in body and fingerprint not in json.dumps(body) and key not in json.dumps(body)
            assert client.delete('/experiments/provider-sessions/'+a.provider_session_id).json()['credential_status']=='UNAVAILABLE'
            assert service.providers.credential(b.provider_session_id)==key
    finally:configure(main._experiments)
    restarted=ProviderSessions(JsonStore(tmp_path/'store'))
    assert restarted.public(restarted.get(b.provider_session_id))['credential_status']=='UNAVAILABLE'
    assert set(service.providers._keys)=={b.provider_session_id}
    assert all('masked_fingerprint' not in p.read_text() and fingerprint not in p.read_text()
               and key not in p.read_text() for p in (tmp_path/'store').rglob('*.json'))


def test_old_fingerprint_read_adapter_does_not_expose_or_rewrite_history(tmp_path):
    service,_,_=setup(tmp_path)
    session=service.providers.create(ProviderConfig(model='user'),token_hex(24))
    path=service.store.path('provider_sessions',session.provider_session_id)
    data=json.loads(path.read_text())['artifact']
    data['masked_fingerprint']='sha256:123456789abc';data['status']='READY'
    for field in ('text_connection_status','tool_call_capability','last_tool_test'):data.pop(field)
    path.write_bytes(encoded({'artifact':data,'sha256':digest(data)}));before=path.read_bytes()
    loaded=service.providers.get(session.provider_session_id)
    public=service.providers.public(loaded)
    assert loaded.text_connection_status=='READY' and loaded.tool_call_capability=='UNKNOWN'
    assert 'masked_fingerprint' not in public and '123456789abc' not in json.dumps(public)
    assert path.read_bytes()==before
    service.providers.delete(session.provider_session_id)  # Explicit lifecycle write uses new schema.
    assert 'masked_fingerprint' not in path.read_text()


@pytest.mark.parametrize('protocol',['openai-compatible','anthropic-compatible'])
def test_actual_http_echo_probe_separate_from_text_and_covers_agent_models(tmp_path,protocol):
    service,ev,_=setup(tmp_path,runtime=ProcessRuntime())
    key=token_hex(24)
    with (chat_provider() if protocol=='openai-compatible' else local_provider()) as (url,state):
        session=ready(service,url,key,provider=protocol,max_tokens=96,role_overrides={
            'technical':{'model':'tech'},'billing':{'model':'billing'},
            'escalation':{'model':'escalation'},'judge':{'model':'judge'}})
        assert session.text_connection_status=='READY' and session.tool_call_capability=='UNKNOWN'
        before=len(state['calls'])
        result=asyncio.run(service.providers.test_tools(session.provider_session_id))
        assert result['tool_call_capability']=='VERIFIED' and result['call_count']==4
        probes=state['calls'][before:]
        assert {c['body']['model'] for c in probes}=={'user-model','tech','billing','escalation'}
        for call in probes:
            body=call['body']
            if protocol=='openai-compatible':
                assert body['tool_choice']=={'type':'function','function':{'name':'echo'}}
                tool=body['tools'][0]['function'];schema=tool['parameters']
                assert body['max_completion_tokens']==64
            else:
                assert body['tool_choice']=={'type':'tool','name':'echo'}
                tool=body['tools'][0];schema=tool['input_schema']
                assert body['max_tokens']==64
            assert tool['name']=='echo' and schema['required']==['value'] and schema['additionalProperties'] is False
        assert service.providers.get(session.provider_session_id).last_tool_test==result
        run=asyncio.run(service.run(ev.eval_set_id,provider_session_id=session.provider_session_id))
        assert run.status=='COMPLETE' and run.provider_readiness_snapshot=={
            'text_connection_status':'READY','tool_call_capability':'VERIFIED','requires_tools':True}
        assert not any(w.startswith('TOOL_CALL_CAPABILITY_') for w in run.warnings)
        assert all(t.get('name')!='echo' for r in run.case_results for e in r.turn_evidence for t in e.tool_traces)
        assert key not in json.dumps(result) and all(key not in p.read_text() for p in (tmp_path/'store').rglob('*.json'))


def probe_mock(service,session,mode,monkeypatch):
    """Replace HTTP only; real transport/validation/probe logic still executes."""
    requests=[]
    def init(provider,config,key):
        provider.config,provider._key=config,key
        provider.call_count=0;provider.observations=[];provider.errors=[]
        async def respond(request):
            requests.append(json.loads(request.content))
            if mode=='timeout':raise httpx.ReadTimeout('unsafe detail',request=request)
            if mode=='delete':service.providers.delete(session.provider_session_id)
            if mode in {'unsupported','generic_400','429'}:
                code='tools_not_supported' if mode=='unsupported' else 'invalid_request_error'
                return httpx.Response(429 if mode=='429' else 400,json={'error':{
                    'code':code,'type':code,'message':'tools unsupported '+key}})
            msg={'role':'assistant','content':'text success'}
            finish='stop'
            if mode=='bad_arguments':
                msg.update(content=None,tool_calls=[{'type':'function','id':'probe','function':{
                    'name':'echo','arguments':'{"value":"wrong"}'}}]);finish='tool_calls'
            if config.provider=='openai-compatible':
                data={'object':'chat.completion','id':'probe','model':config.model,
                      'choices':[{'finish_reason':finish,'message':msg}]}
            else:
                data={'id':'probe','type':'message','role':'assistant','model':config.model,
                      'content':[{'type':'text','text':'text success'}],'stop_reason':'end_turn',
                      'stop_sequence':None,'usage':{'input_tokens':1,'output_tokens':1}}
            return httpx.Response(200,json=data)
        transport=httpx.MockTransport(respond)
        if config.provider=='openai-compatible':
            from experiments.openai_chat import ChatCompletionClient
            # Same adapter, with its sole HTTP client supplied by this fixture.
            provider._sdk=ChatCompletionClient.__new__(ChatCompletionClient)
            provider._sdk._config,provider._sdk._key=config,key
            provider._sdk.messages=provider._sdk
            provider._sdk._http=httpx.AsyncClient(transport=transport)
        else:
            from anthropic import AsyncAnthropic
            provider._sdk=AsyncAnthropic(api_key=key,max_retries=0,base_url=config.base_url,
                                        http_client=httpx.AsyncClient(transport=transport))
    monkeypatch.setattr(ObservedProvider,'__init__',init)
    return requests


@pytest.mark.parametrize('protocol',['openai-compatible','anthropic-compatible'])
@pytest.mark.parametrize('mode,capability,status',[
    ('unsupported','UNSUPPORTED','TOOL_CALL_UNSUPPORTED'),
    ('generic_400','FAILED','PROVIDER_ERROR'),('429','FAILED','RATE_LIMITED'),
    ('timeout','FAILED','TIMEOUT'),('ignored','FAILED','INVALID_TOOL_RESPONSE'),
    ('bad_arguments','FAILED','INVALID_TOOL_RESPONSE')])
def test_probe_failure_is_not_text_failure_or_false_unsupported(tmp_path,monkeypatch,protocol,mode,capability,status):
    service,_,_=setup(tmp_path)
    with (chat_provider() if protocol=='openai-compatible' else local_provider()) as (url,state):
        session=ready(service,url,provider=protocol)
    requests=probe_mock(service,session,mode,monkeypatch)
    result=asyncio.run(service.providers.test_tools(session.provider_session_id))
    assert result['tool_call_capability']==capability and result['checks'][0]['status']==status
    assert result['call_count']==len(requests)==1
    latest=service.providers.get(session.provider_session_id)
    assert latest.status=='READY' and latest.text_connection_status=='READY' and latest.tool_call_capability==capability
    assert not list((tmp_path/'store'/'runs').glob('*.json'))


@pytest.mark.parametrize('capability',['UNKNOWN','FAILED','VERIFIED','UNSUPPORTED'])
def test_dialog_admission_and_tool_free_intent_run(tmp_path,capability):
    service,ev,_=setup(tmp_path,runtime=ProcessRuntime())
    with chat_provider() as (url,state):
        session=ready(service,url,provider='openai-compatible')
        service.store.put('provider_sessions',session.model_copy(update={'tool_call_capability':capability}))
        before=len(state['calls'])
        if capability=='UNSUPPORTED':
            with pytest.raises(ProviderFailure,match='TOOL_CALL_UNSUPPORTED'):
                asyncio.run(service.run(ev.eval_set_id,provider_session_id=session.provider_session_id))
            assert len(state['calls'])==before and not list((tmp_path/'store'/'runs').glob('*.json'))
        else:
            run=asyncio.run(service.run(ev.eval_set_id,provider_session_id=session.provider_session_id))
            assert run.status=='COMPLETE' and run.provider_readiness_snapshot['tool_call_capability']==capability
            if capability in {'UNKNOWN','FAILED'}:assert 'TOOL_CALL_CAPABILITY_'+capability in run.warnings
            else:assert not any(w.startswith('TOOL_CALL_CAPABILITY_') for w in run.warnings)
            # Later Session probes cannot rewrite the sealed Run readiness.
            service.store.put('provider_sessions',session.model_copy(update={'tool_call_capability':'UNSUPPORTED'}))
            assert service.store.get('runs',run.run_id).provider_readiness_snapshot['tool_call_capability']==capability
        intents=service.create_eval_set([],intent_cases=[{'case_id':'i','message':'订单咨询','expected_intent':'query'}])
        irun=asyncio.run(service.run(intents.eval_set_id,provider_session_id=session.provider_session_id))
        assert irun.status=='COMPLETE' and irun.intent_metrics['total']==1
        assert irun.provider_readiness_snapshot['requires_tools'] is False and not irun.case_results
        assert not any(w.startswith('TOOL_CALL_CAPABILITY_') for w in irun.warnings)


def test_probe_requires_text_ready_and_memory_key_no_requests(tmp_path):
    service,_,_=setup(tmp_path)
    with chat_provider() as (url,state):
        session=service.providers.create(ProviderConfig(provider='openai-compatible',base_url=url,model='user'),token_hex(24))
        with pytest.raises(ProviderFailure,match='TEXT_CONNECTION_NOT_READY'):
            asyncio.run(service.providers.test_tools(session.provider_session_id))
        service.providers.delete(session.provider_session_id)
        with pytest.raises(ProviderFailure,match='CREDENTIAL_UNAVAILABLE'):
            asyncio.run(service.providers.test_tools(session.provider_session_id))
        assert not state['calls']


def test_probe_budget_and_inflight_delete_cannot_revive_session(tmp_path,monkeypatch):
    service,_,_=setup(tmp_path)
    with chat_provider() as (url,state):
        session=ready(service,url,provider='openai-compatible',max_calls=1)
        requests=probe_mock(service,session,'delete',monkeypatch)
        result=asyncio.run(service.providers.test_tools(session.provider_session_id))
        assert result['tool_call_capability']=='FAILED' and len(requests)==result['call_count']==1
        assert service.providers.get(session.provider_session_id).status=='DELETED'
        assert not service.providers.get(session.provider_session_id).last_tool_test


def test_distinct_model_probe_respects_budget(tmp_path):
    service,_,_=setup(tmp_path)
    with chat_provider() as (url,state):
        # Text connection also covers two models; separate probe budget is two calls.
        session=ready(service,url,provider='openai-compatible',max_calls=2,
                      role_overrides={'technical':{'model':'other'}})
        before=len(state['calls'])
        result=asyncio.run(service.providers.test_tools(session.provider_session_id))
        assert result['tool_call_capability']=='VERIFIED' and result['call_count']==2
        assert len(state['calls'])-before==2

def test_probe_budget_exhaustion_cannot_claim_verified(tmp_path):
    service,_,_=setup(tmp_path)
    with chat_provider() as (url,state):
        session=service.providers.create(ProviderConfig(provider='openai-compatible',base_url=url,
            model='default',max_calls=1,role_overrides={'technical':{'model':'other'}}),token_hex(24))
        # Defensive budget boundary with an injected READY fixture, not a real connection assertion.
        service.store.put('provider_sessions',session.model_copy(update={'status':'READY','text_connection_status':'READY'}))
        result=asyncio.run(service.providers.test_tools(session.provider_session_id))
        assert result['tool_call_capability']=='FAILED' and result['call_count']==len(state['calls'])==1
        assert result['checks'][-1]['status']=='CALL_BUDGET_EXCEEDED'


def test_tool_probe_api_readiness_and_missing_credentials(tmp_path):
    service,_,_=setup(tmp_path);configure(lambda:service)
    try:
        with chat_provider() as (url,state),api_client() as client:
            data=client.post('/experiments/provider-sessions',json={'provider':'openai-compatible',
                'base_url':url,'model':'user','api_key':token_hex(24)}).json()
            sid=data['provider_session_id'];endpoint='/experiments/provider-sessions/'+sid
            assert data['credential_status']=='PRESENT' and data['tool_call_capability']=='UNKNOWN'
            assert client.post(endpoint+'/test-tools').status_code==409
            assert client.post(endpoint+'/test').json()['scope']=='TEXT_CONNECTION_ONLY'
            assert client.post(endpoint+'/test-tools').json()['tool_call_capability']=='VERIFIED'
            assert client.get(endpoint).json()['tool_call_capability']=='VERIFIED'
            ev=client.post('/experiments/evalsets',json={'dialog_cases':[{'input':'订单','case_id':'a'}]}).json()
            latest=service.providers.get(sid)
            service.store.put('provider_sessions',latest.model_copy(update={'tool_call_capability':'UNSUPPORTED'}))
            before=len(state['calls'])
            rejected=client.post('/experiments/runs',json={'eval_set_id':ev['eval_set_id'],'provider_session_id':sid})
            assert rejected.status_code==409 and rejected.json()['detail']=='TOOL_CALL_UNSUPPORTED'
            assert len(state['calls'])==before and not list((tmp_path/'store'/'runs').glob('*.json'))
            client.delete(endpoint)
            assert client.post(endpoint+'/test-tools').json()['detail']=='CREDENTIAL_UNAVAILABLE'
            assert client.post('/experiments/provider-sessions/missing/test-tools').status_code==404
    finally:configure(main._experiments)


def test_readiness_change_preserves_comparability_and_warning_evidence(tmp_path):
    service,ev,_=setup(tmp_path,runtime=ProcessRuntime())
    with chat_provider() as (url,state):
        session=ready(service,url,provider='openai-compatible')
        a=asyncio.run(service.run(ev.eval_set_id,provider_session_id=session.provider_session_id))
        assert a.provider_readiness_snapshot['tool_call_capability']=='UNKNOWN'
        decision=confirmed(service,a)
        change=service.apply_change(service.propose_change(decision.decision_id,'refund.md',
            'Verify payment before claims.',a.skill_version['hash']).change_id)
        assert asyncio.run(service.providers.test_tools(session.provider_session_id))['tool_call_capability']=='VERIFIED'
        b=asyncio.run(service.run(ev.eval_set_id,'RETEST',a.run_id,decision.decision_id,[change.change_id],
            provider_session_id=session.provider_session_id))
        comparison=service.compare(a.run_id,b.run_id)
        assert comparison.comparable and comparison.single_recorded_change and not comparison.attributable
        assert comparison.attribution_status=='INSUFFICIENT_EVIDENCE'
        assert 'TOOL_CALL_CAPABILITY_UNKNOWN' in comparison.attribution_warnings
        assert b.provider_readiness_snapshot['tool_call_capability']=='VERIFIED'
        assert a.evaluation_protocol_hash==b.evaluation_protocol_hash
