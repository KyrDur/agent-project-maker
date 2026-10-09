"""No live credentials; temporary random test keys never written to fixtures/XML."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import json
import logging
import re
from secrets import token_hex
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from fastapi.testclient import TestClient
from experiments.providers import ProviderConfig,ProviderFailure
from experiments.provider_transport import ObservedProvider
from experiments.store import JsonStore
from experiments.service import ExperimentService
from experiments.api import configure
from api import main
from test_experiment_service import setup, confirmed

@contextmanager
def local_provider():
    state={'failure':None,'stage':'all','revision':'returned-v1','malformed':None,'calls':[],'delay':False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            auth=self.headers.get('x-api-key')
            state['calls'].append({'body':body,'auth':auth})
            prompt=str(body.get('messages',''))
            stage=('connection' if 'Reply OK.' in prompt else 'judge' if '客服质量评估专家' in prompt
                   else 'intent' if '客服意图分析专家' in prompt else 'agent')
            failed=state['stage'] in {'all',stage}
            status=state['failure'] if failed else None
            if state['delay']:
                time.sleep(.15)
            content=None
            if status:
                data={'type':'error','error':{'type':'provider_error','message':auth}}
            else:
                if stage=='connection':text='OK'
                elif any(t['name']=='echo' for t in body.get('tools',[])):
                    text='OK'
                    content=[{'type':'tool_use','id':'probe_echo','name':'echo',
                              'input':{'value':re.search(r'echo-[a-f0-9]{12}',prompt).group()}}]
                elif stage=='intent':text=json.dumps({'intent':'refund' if '退款' in prompt else 'query',
                                                      'confidence':1,'reasoning':'scripted'})
                elif stage=='judge':
                    score=.95 if 'payment' in prompt else .2
                    text=json.dumps(dict(relevance=score,accuracy=score,completeness=score,helpfulness=score))
                else:
                    if 'tool_result' not in prompt:
                        tools={t['name'] for t in body.get('tools',[])}
                        name='check_billing_fields' if 'check_billing_fields' in tools else 'inspect_request_context'
                        content=[{'type':'tool_use','id':'call_local','name':name,'input':{}}]
                    text='payment checked' if 'payment' in body.get('system','') else 'Please verify information.'
                if state['malformed']=='tool' and failed and stage=='agent':
                    content=[{'type':'tool_use','id':'call_local','name':'compare_amounts','input':{'amount_a':'invalid'}}]
                if state['malformed']=='judge' and stage=='judge':text='not JSON'
                if state['malformed']=='empty' and failed:text='';content=[]
                if state['malformed']=='echo_key' and failed:text=auth;content=[]
                data={'id':'msg_local','type':'message','role':'assistant','model':state['revision'],
                      'content':content or [{'type':'text','text':text}],
                      'stop_reason':'tool_use' if content else 'end_turn','stop_sequence':None,
                      'usage':{'input_tokens':1,'output_tokens':1}}
            raw=b'not JSON' if state['malformed']=='wire_json' and failed else json.dumps(data).encode()
            self.send_response(status or 200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:yield f'http://127.0.0.1:{server.server_port}',state
    finally:server.shutdown();server.server_close()


def ready(service,url,key=None,**config):
    session=service.providers.create(ProviderConfig(base_url=url,model='user-model',**config),key or token_hex(24))
    result=asyncio.run(service.providers.test(session.provider_session_id))
    assert result['status']=='SUCCESS'
    return service.providers.get(session.provider_session_id)

@pytest.mark.parametrize('status,expected',[(401,'AUTH_FAILED'),(403,'AUTH_FAILED'),(404,'MODEL_NOT_FOUND'),
                                           (429,'RATE_LIMITED'),(500,'PROVIDER_ERROR'),(503,'PROVIDER_ERROR')])
def test_connection_real_requests_safe_errors(tmp_path,caplog,status,expected):
    service,_,_=setup(tmp_path)
    key=token_hex(24)
    with local_provider() as (url,state):
        session=service.providers.create(ProviderConfig(base_url=url,model='specified'),key)
        state['failure']=status
        with caplog.at_level(logging.DEBUG):
            result=asyncio.run(service.providers.test(session.provider_session_id))
        assert result['status']==expected and len(state['calls'])==1
        assert state['calls'][0]['body']['model']=='specified'
        assert state['calls'][0]['auth']==key
        assert service.providers.get(session.provider_session_id).status=='CONNECTION_FAILED'
        assert key not in caplog.text and key not in json.dumps(result)
        assert all(key not in p.read_text() for p in (tmp_path/'store').rglob('*.json'))

@pytest.mark.parametrize('malformed',['wire_json','empty','echo_key'])
def test_connection_invalid_response(tmp_path,malformed):
    service,_,_=setup(tmp_path)
    with local_provider() as (url,state):
        session=service.providers.create(ProviderConfig(base_url=url,model='user-model'),token_hex(24))
        state['malformed']=malformed
        result=asyncio.run(service.providers.test(session.provider_session_id))
        assert result['status']=='INVALID_RESPONSE'
        assert service.providers.get(session.provider_session_id).status!='READY'

def test_timeout_and_network_error_classification(tmp_path):
    service,_,_=setup(tmp_path)
    with local_provider() as (url,state):
        state['delay']=True
        session=service.providers.create(ProviderConfig(base_url=url,model='user-model',timeout_seconds=.1),token_hex(24))
        assert asyncio.run(service.providers.test(session.provider_session_id))['status']=='TIMEOUT'
    # The now-closed local server is a deterministic connection refusal.
    session=service.providers.create(ProviderConfig(base_url=url,model='user-model',timeout_seconds=.1),token_hex(24))
    assert asyncio.run(service.providers.test(session.provider_session_id))['status']=='NETWORK_ERROR'

def test_sessions_isolated_delete_restart_and_no_environment_fallback(tmp_path,monkeypatch):
    from experiments.runtime import ProcessRuntime
    service,ev,manager=setup(tmp_path,runtime=ProcessRuntime())
    key_a,key_b,server_key=token_hex(24),token_hex(24),token_hex(24)
    monkeypatch.setenv('ANTHROPIC_API_KEY',server_key);monkeypatch.setenv('OPENAI_API_KEY',server_key)
    monkeypatch.setenv('ANTHROPIC_MODEL','wrong-environment-model')
    monkeypatch.setenv('ECHOMIND_BILLING_MODEL','wrong-billing-model')
    with local_provider() as (url,state):
        a=ready(service,url,key_a);b=ready(service,url,key_b,temperature=.4)
        assert service.providers.credential(a.provider_session_id)==key_a
        assert service.providers.credential(b.provider_session_id)==key_b
        assert a.configuration.temperature==0 and b.configuration.temperature==.4
        assert {c['auth'] for c in state['calls']}=={key_a,key_b}
        restarted=ExperimentService(JsonStore(tmp_path/'store'),manager)
        assert restarted.providers.get(a.provider_session_id).status=='CREDENTIAL_UNAVAILABLE'
        before=len(state['calls'])
        run=asyncio.run(restarted.run(ev.eval_set_id,provider_session_id=a.provider_session_id))
        assert run.status=='FAILED' and 'CREDENTIAL_UNAVAILABLE' in run.warnings
        assert len(state['calls'])==before and server_key not in json.dumps(run.model_dump())
        service.providers.delete(a.provider_session_id)
        with pytest.raises(ProviderFailure,match='CREDENTIAL_UNAVAILABLE'):
            service.providers.credential(a.provider_session_id)
        assert service.providers.credential(b.provider_session_id)==key_b
        assert key_a not in service.store.forbidden_values
        with pytest.raises(ValueError,match='revived'):
            service.store.put('provider_sessions',a)

def test_user_config_stage_identifiers_full_loop_and_scope(tmp_path,monkeypatch):
    from experiments.runtime import ProcessRuntime
    service,_,_=setup(tmp_path,runtime=ProcessRuntime())
    monkeypatch.setenv('ANTHROPIC_MODEL','wrong');monkeypatch.setenv('ECHOMIND_BILLING_MODEL','wrong-billing')
    with local_provider() as (url,state):
        session=ready(service,url,temperature=.3,max_tokens=96,role_overrides={
            'judge':{'model':'user-judge','temperature':0,'max_tokens':120}})
        # Connection tests both distinct effective models, not just the default Agent.
        assert {c['body']['model'] for c in state['calls']}=={'user-model','user-judge'}
        ev=service.create_eval_set([{'case_id':'a','turns':['退款','退款 order','退款 time']},
                                    {'case_id':'b','input':'我的订单怎么查询？'}])
        a=asyncio.run(service.run(ev.eval_set_id,provider_session_id=session.provider_session_id))
        assert a.status=='COMPLETE' and not a.runtime_end_check['drift_detected']
        inference=a.inference_config_snapshot
        assert inference['agents']['billing']=={'model':'user-model','temperature':.3,'max_tokens':96}
        assert inference['judge']=={'model':'user-judge','temperature':0,'max_tokens':120}
        assert inference['model_inheritance']['billing']=='user_default' and inference['model_inheritance']['judge']=='explicit_override'
        assert a.provider_configuration_snapshot==session.configuration.model_dump()
        assert a.provider_call_count==len(a.provider_observations)>0
        assert a.case_results[0].original_status=='FAIL' and len(a.case_results[0].turn_evidence)==3
        assert any(o['stage']=='billing' for o in a.provider_observations)
        assert any(o['stage']=='judge' and o['requested_model']=='user-judge' for o in a.provider_observations)
        dec=confirmed(service,a)
        change=service.propose_change(dec.decision_id,'refund.md','Verify payment before claims.',a.skill_version['hash'])
        change=service.apply_change(change.change_id)
        state['revision']='returned-v2'
        b=asyncio.run(service.run(ev.eval_set_id,'RETEST',a.run_id,dec.decision_id,[change.change_id],
                                  provider_session_id=session.provider_session_id))
        assert b.case_results[0].original_status=='PASS' and not b.runtime_end_check['drift_detected']
        assert 'RESPONSE_MODEL_IDENTIFIER_CHANGED' in b.warnings
        comp=service.compare(a.run_id,b.run_id)
        assert comp.comparable and comp.single_recorded_change and not comp.attributable
        assert comp.attribution_status=='INSUFFICIENT_EVIDENCE'
        assert comp.case_comparisons[0]['effective_transition']=='IMPROVED'
        assert {'RESPONSE_MODEL_IDENTIFIER_CHANGED','MODEL_BACKEND_REVISION_UNVERIFIED',
                'REDUCED_RUNTIME_KNOWLEDGE_DISABLED','SINGLE_RUN_RANDOMNESS_NOT_CAUSAL_PROOF'} <= set(comp.attribution_warnings)
        service.rollback(change.change_id)
        calls=[c['body'] for c in state['calls'] if 'Reply OK.' not in str(c['body']['messages'])]
        assert all(c['model'] in {'user-model','user-judge'} for c in calls)
        assert any(c['model']=='user-judge' and c['max_tokens']==120 for c in calls)
        assert any(c['model']=='user-model' and c['temperature']==.3 and c['max_tokens']==96 for c in calls)

@pytest.mark.parametrize('stage,kind',[('agent',401),('agent',429),('agent',500),('judge',401),('judge',429),
                                      ('judge','judge'),('agent','tool'),('agent','empty'),('agent','wire_json')])
def test_formal_provider_errors_are_invalid_not_quality_fail(tmp_path,stage,kind):
    from experiments.runtime import ProcessRuntime
    service,_,_=setup(tmp_path,runtime=ProcessRuntime())
    with local_provider() as (url,state):
        session=ready(service,url)
        ev=service.create_eval_set([{'case_id':'a','input':'退款'}])
        state['stage']=stage
        if isinstance(kind,int):state['failure']=kind
        else:state['malformed']=kind
        run=asyncio.run(service.run(ev.eval_set_id,provider_session_id=session.provider_session_id))
        assert run.status=='COMPLETE',run.warnings
        result=run.case_results[0]
        assert result.original_status=='INVALID' and result.exclude_from_quality_metrics and not result.scores
        assert result.execution_status==('FAILED' if stage=='agent' else 'SUCCESS')
        assert result.judge_status==('NOT_RUN' if stage=='agent' else 'FAILED')
        metrics=service.result_view(run.run_id)['dialog_case_metrics']
        assert metrics['valid']==0 and metrics['avg_scores']=={}


def test_api_secret_input_errors_and_lifecycle(tmp_path,caplog):
    service,_,_=setup(tmp_path)
    key=token_hex(24)
    configure(lambda:service)
    client=TestClient(main.app)
    try:
        with local_provider() as (url,state):
            body={'provider':'anthropic-compatible','model':'user-model','base_url':url,'api_key':key}
            with caplog.at_level(logging.DEBUG):
                bad=client.post('/experiments/provider-sessions',json={**body,'temperature':key})
                assert bad.status_code==422 and key not in bad.text
                response=client.post('/experiments/provider-sessions',json=body)
                assert response.status_code==200 and key not in response.text
                session=response.json();sid=session['provider_session_id']
                assert 'api_key' not in session and 'masked_fingerprint' not in session
                assert session['credential_status']=='PRESENT'
                assert client.post(f'/experiments/provider-sessions/{sid}/test').json()['status']=='SUCCESS'
                assert client.get(f'/experiments/provider-sessions/{sid}').json()['status']=='READY'
                assert client.post('/experiments/runs',json={'eval_set_id':'nonexistent'}).status_code==422
                assert client.delete(f'/experiments/provider-sessions/{sid}').json()['status']=='DELETED'
                assert client.get(f'/experiments/provider-sessions/{sid}').json()['status']=='DELETED'
            assert key not in caplog.text
            assert all(key not in p.read_text() for p in (tmp_path/'store').rglob('*.json'))
    finally:configure(main._experiments)


def test_provider_snapshot_immutable_and_call_budget(tmp_path):
    service,_,_=setup(tmp_path)
    with local_provider() as (url,state):
        session=ready(service,url,max_calls=1)
        with pytest.raises(ValueError,match='immutable'):
            service.store.put('provider_sessions',session.model_copy(update={'configuration':ProviderConfig(model='changed')}))
        async def limited():
            provider=ObservedProvider(session.configuration,service.providers.credential(session.provider_session_id))
            try:
                await provider.client('judge').messages.create(messages=[{'role':'user','content':'Reply OK.'}])
                with pytest.raises(ProviderFailure,match='CALL_BUDGET_EXCEEDED'):
                    await provider.client('judge').messages.create(messages=[{'role':'user','content':'Reply OK.'}])
                assert provider.call_count==1
            finally:await provider.close()
        before=len(state['calls']);asyncio.run(limited());assert len(state['calls'])==before+1


def test_standalone_intent_provider_failure_never_counts_fallback_as_correct(tmp_path):
    from experiments.runtime import ProcessRuntime
    service,_,_=setup(tmp_path,runtime=ProcessRuntime())
    with local_provider() as (url,state):
        session=ready(service,url)
        ev=service.create_eval_set([{'case_id':'a','input':'退款'}],
            intent_cases=[{'case_id':'intent-a','message':'退款','expected_intent':'refund'}])
        state.update(stage='intent',failure=401)
        run=asyncio.run(service.run(ev.eval_set_id,provider_session_id=session.provider_session_id))
        assert run.status=='FAILED' and 'AUTH_FAILED' in run.warnings
        assert not run.intent_metrics and not run.intent_sample_results and not run.case_results
        assert service.result_view(run.run_id)['dialog_case_metrics']['valid']==0
