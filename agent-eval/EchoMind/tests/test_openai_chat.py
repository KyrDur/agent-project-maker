"""Actual local HTTP Chat Completions protocol, including tool-call result roundtrip."""
import asyncio
from contextlib import contextmanager
import json
import re
from secrets import token_hex
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from experiments.providers import ProviderConfig
from experiments.runtime import ProcessRuntime
from test_experiment_service import setup,confirmed
from test_provider_sessions import ready

@contextmanager
def chat_provider():
    state={'calls':[],'failure':None,'malformed':None,'revision':'chat-returned-v1','stage':'all'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['calls'].append({'path':self.path,'body':body,'auth':self.headers.get('Authorization')})
            prompt=str(body['messages']);tools={t['function']['name'] for t in body.get('tools',[])}
            stage=('connection' if 'Reply OK.' in prompt else 'judge' if '客服质量评估专家' in prompt
                   else 'intent' if '客服意图分析专家' in prompt else 'agent')
            failed=state['stage'] in {'all',stage}
            msg={'role':'assistant','content':'OK'};finish='stop'
            status=(state['failure'] or 200) if failed else 200
            if status!=200:
                response={'error':{'message':self.headers.get('Authorization')}}
            else:
                if tools=={'echo'}:
                    msg.update(content=None,tool_calls=[{'type':'function','id':'probe_echo',
                        'function':{'name':'echo','arguments':json.dumps({
                            'value':re.search(r'echo-[a-f0-9]{12}',prompt).group()})}}]);finish='tool_calls'
                elif '客服意图分析专家' in prompt:
                    msg['content']=json.dumps({'intent':'refund' if '退款' in prompt else 'query','confidence':1,'reasoning':'local chat'})
                elif '客服质量评估专家' in prompt:
                    score=.95 if 'payment checked' in prompt else .2
                    msg['content']=json.dumps(dict(relevance=score,accuracy=score,completeness=score,helpfulness=score))
                    if state['malformed']=='judge' and failed:msg['content']='not JSON'
                elif tools and not any(m['role']=='tool' for m in body['messages']):
                    name='check_billing_fields' if 'check_billing_fields' in tools else 'inspect_request_context'
                    msg.update(content=None,tool_calls=[{'type':'function','id':'chat_call_1',
                        'function':{'name':name,'arguments':'{}'}}]);finish='tool_calls'
                    if state['malformed']=='arguments':msg['tool_calls'][0]['function']['arguments']='{broken'
                    if state['malformed']=='unknown_tool':msg['tool_calls'][0]['function']['name']='search_knowledge_base'
                elif tools:
                    system='\n'.join(m['content'] for m in body['messages'] if m['role']=='system')
                    msg['content']='payment checked' if 'Verify payment before claims.' in system else 'Please verify information.'
                if state['malformed']=='empty' and failed:msg['content']=''
                response={'id':'chatcmpl_local','object':'chat.completion','model':state['revision'],'created':1,
                          'choices':[{'index':0,'message':msg,'finish_reason':finish}],
                          'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
                if state['malformed']=='missing_choices':response.pop('choices')
                if state['malformed']=='echo_key':response['model']=self.headers['Authorization'][7:]
            raw=json.dumps(response).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:yield f'http://127.0.0.1:{server.server_port}/v1',state
    finally:server.shutdown();server.server_close()

@pytest.mark.parametrize('token_parameter',['max_completion_tokens','max_tokens'])
def test_chat_real_http_connection_tool_roundtrip_baseline_retest(tmp_path,monkeypatch,token_parameter):
    service,_,_=setup(tmp_path,runtime=ProcessRuntime())
    monkeypatch.setenv('OPENAI_API_KEY',token_hex(24));monkeypatch.setenv('ANTHROPIC_MODEL','wrong-server-model')
    key=token_hex(24)
    with chat_provider() as (url,state):
        session=ready(service,url,key,provider='openai-compatible',completion_token_parameter=token_parameter,
                      temperature=.2,max_tokens=128,role_overrides={'judge':{'model':'judge-chat','temperature':0,'max_tokens':160}})
        assert len(state['calls'])==2
        assert all(c['path']=='/v1/chat/completions' and c['auth']=='Bearer '+key for c in state['calls'])
        assert all(c['body'][token_parameter]==8 for c in state['calls'])
        ev=service.create_eval_set([{'case_id':'a','turns':['退款','退款订单','退款时间']},
                                   {'case_id':'b','input':'订单咨询'},
                                   {'case_id':'c','input':'退款','judge_method':'tool trace',
                                    'executable_rules':[{'type':'required_tool','tool':'check_billing_fields'}]}])
        a=asyncio.run(service.run(ev.eval_set_id,provider_session_id=session.provider_session_id))
        assert a.status=='COMPLETE' and not a.runtime_end_check['drift_detected']
        assert [r.original_status for r in a.case_results]==['FAIL','FAIL','PASS']
        assert len(a.case_results[0].turn_evidence)==3
        assert a.provider_observations and all(o['response_model_identifier']=='chat-returned-v1' for o in a.provider_observations)
        assert a.inference_config_snapshot['transport']=='openai_chat_completions_v1'
        assert a.inference_config_snapshot['provider']['endpoint']==url
        decision=confirmed(service,a)
        change=service.apply_change(service.propose_change(decision.decision_id,'refund.md',
                       'Verify payment before claims.',a.skill_version['hash']).change_id)
        state['revision']='chat-returned-v2'
        b=asyncio.run(service.run(ev.eval_set_id,'RETEST',a.run_id,decision.decision_id,[change.change_id],
                                  provider_session_id=session.provider_session_id))
        assert b.case_results[0].original_status=='PASS'
        comp=service.compare(a.run_id,b.run_id)
        assert comp.comparable and comp.single_recorded_change and not comp.attributable
        assert comp.attribution_status=='INSUFFICIENT_EVIDENCE'
        assert {'RESPONSE_MODEL_IDENTIFIER_CHANGED','REDUCED_RUNTIME_KNOWLEDGE_DISABLED'}<=set(comp.attribution_warnings)
        tool_followups=[c['body'] for c in state['calls'] if any(m['role']=='tool' for m in c['body']['messages'])]
        assert tool_followups
        assert all(any(m['role']=='assistant' and m.get('tool_calls') for m in b['messages']) for b in tool_followups)
        assert all(m['tool_call_id']=='chat_call_1' for b in tool_followups for m in b['messages'] if m['role']=='tool')
        assert all('search_knowledge_base' not in {t['function']['name'] for t in c['body'].get('tools',[])} for c in state['calls'])
        assert all(c['body']['stream'] is False and c['body']['store'] is False for c in state['calls'])
        assert all(key not in p.read_text() for p in (tmp_path/'store').rglob('*.json'))
        service.rollback(change.change_id)

@pytest.mark.parametrize('status,expected',[(401,'AUTH_FAILED'),(404,'MODEL_NOT_FOUND'),(429,'RATE_LIMITED'),(500,'PROVIDER_ERROR')])
def test_chat_connection_errors_safe(tmp_path,status,expected,caplog):
    service,_,_=setup(tmp_path)
    key=token_hex(24)
    with chat_provider() as (url,state):
        session=service.providers.create(ProviderConfig(provider='openai-compatible',model='chat',base_url=url),key)
        state['failure']=status
        result=asyncio.run(service.providers.test(session.provider_session_id))
        assert result['status']==expected
        assert key not in json.dumps(result) and key not in caplog.text

@pytest.mark.parametrize('malformed',['missing_choices','empty','echo_key'])
def test_chat_invalid_connection_response(tmp_path,malformed):
    service,_,_=setup(tmp_path)
    with chat_provider() as (url,state):
        session=service.providers.create(ProviderConfig(provider='openai-compatible',model='chat',base_url=url),token_hex(24))
        state['malformed']=malformed
        assert asyncio.run(service.providers.test(session.provider_session_id))['status']=='INVALID_RESPONSE'

@pytest.mark.parametrize('malformed',['arguments','unknown_tool'])
def test_chat_malformed_tool_call_invalid_never_success(tmp_path,malformed):
    service,_,_=setup(tmp_path,runtime=ProcessRuntime())
    with chat_provider() as (url,state):
        session=ready(service,url,provider='openai-compatible')
        ev=service.create_eval_set([{'case_id':'a','input':'退款'}])
        state['malformed']=malformed
        run=asyncio.run(service.run(ev.eval_set_id,provider_session_id=session.provider_session_id))
        assert run.case_results[0].original_status=='INVALID' and run.case_results[0].execution_status=='FAILED'
        assert not run.case_results[0].scores
        assert all('search_knowledge_base' not in e.tools_used for e in run.case_results[0].turn_evidence)

@pytest.mark.parametrize('stage,kind',[('agent',401),('agent',429),('agent',503),('judge',401),
                                      ('judge',429),('judge','judge'),('intent',401)])
def test_chat_provider_stage_failure_not_a_quality_fail(tmp_path,stage,kind):
    service,_,_=setup(tmp_path,runtime=ProcessRuntime())
    with chat_provider() as (url,state):
        session=ready(service,url,provider='openai-compatible')
        ev=service.create_eval_set([{'case_id':'a','input':'退款'}])
        state['stage']=stage
        if isinstance(kind,int):state['failure']=kind
        else:state['malformed']=kind
        run=asyncio.run(service.run(ev.eval_set_id,provider_session_id=session.provider_session_id))
        assert run.status=='COMPLETE'
        result=run.case_results[0]
        assert result.original_status=='INVALID' and not result.scores and result.exclude_from_quality_metrics
        assert result.execution_status==('SUCCESS' if stage=='judge' else 'FAILED')
        assert result.judge_status==('FAILED' if stage=='judge' else 'NOT_RUN')
        assert service.result_view(run.run_id)['dialog_case_metrics']['valid']==0

def test_chat_inconsistent_finish_reason_is_not_successful_tool_evidence():
    # Exercise finish_reason consistency independently of a successful HTTP status.
    from experiments.provider_transport import ObservedProvider
    from experiments.providers import ProviderFailure
    import httpx
    async def check():
        config=ProviderConfig(provider='openai-compatible',model='x')
        provider=ObservedProvider(config,token_hex(24))
        raw={'object':'chat.completion','id':'c','model':'x','choices':[{'finish_reason':'tool_calls',
              'message':{'role':'assistant','content':'apparently successful'}}]}
        await provider._sdk._http.aclose()
        provider._sdk._http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=raw)))
        try:
            with pytest.raises(ProviderFailure,match='INVALID_RESPONSE'):
                await provider.client('general').messages.create(messages=[{'role':'user','content':'x'}])
            assert not provider.observations
        finally:await provider.close()
    asyncio.run(check())
