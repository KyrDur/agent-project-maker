import asyncio
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from secrets import token_hex
from threading import Thread
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from experiments.assist import AssistService, CATEGORIES
from experiments.providers import ProviderConfig, ProviderFailure
from experiments.provider_transport import ObservedProvider
from experiments.retrieval_service import RetrievalService
from experiments.api import configure
from experiments.app import app
from test_experiment_service import setup

@contextmanager
def assistant_server():
    state={'calls':[],'mode':None}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['calls'].append({'body':body,'auth':self.headers.get('x-api-key')})
            prompt=body.get('system','');data={}
            if 'ASSIST_KNOWLEDGE' in prompt:
                data={'name':'模拟耳机电商','documents':[{'document_id':'topic_'+str(i),'title':category,
                    'category':category,'text':'模拟设定：普通商品适用此规则。请核验订单和商品状态，不承诺业务操作已完成。',
                    'applicability':'模拟店铺的普通商品','exceptions':'定制商品需另行核验'} for i,category in enumerate(CATEGORIES)]}
                if state['mode']=='bad_category':data['documents'][0]['category']='配送'
            elif 'ASSIST_TESTS' in prompt:
                payload=json.loads(body['messages'][0]['content']);doc=payload['documents'][0]
                data={'cases':[{'query':f'怎么处理{i}？'+str(len(state['calls'])),'expected_answer':doc['text'],
                    'must_do':['说明条件'],'must_not_do':['不承诺已完成'],'relevant_document_ids':[doc['document_id']],
                    'question_type':'常规','source_quotes':[{'document_id':doc['document_id'],'quote':doc['text'][:12]}]}
                    for i in range(payload['count'])]}
                if state['mode']=='bad_quote':data['cases'][0]['source_quotes'][0]['quote']='不在原文中的政策'
                if state['mode']=='bad_id':data['cases'][0]['relevant_document_ids']=['invented']
            elif 'ASSIST_TRACE' in prompt:
                evidence=json.loads(body['messages'][0]['content'])['evidence'];ref=next(iter(evidence))
                data={'facts':[{'claim':'本次轨迹有记录','evidence_keys':[ref]}],'issues':[],
                    'hypotheses':[],'suggestions':[{'change_type':'TOP_K_CHANGE','reason':'待验证的排序假设',
                    'evidence_keys':[ref],'verification':'同题复测','side_effects':'增加上下文'}],
                    'limitations':['没有运行回答，不能评价答案质量']}
                if state['mode']=='bad_ref':data['facts'][0]['evidence_keys']=['invented']
            elif '客服质量评估专家' in str(body):data={'relevance':.9,'accuracy':.9,'completeness':.9,'helpfulness':.9}
            text='OK' if not data else json.dumps(data,ensure_ascii=False)
            if state['mode']=='echo_key':text=self.headers.get('x-api-key')
            response={'id':'msg_test','type':'message','role':'assistant','model':body['model'],
                'content':[{'type':'text','text':text}],'stop_reason':'end_turn','stop_sequence':None,
                'usage':{'input_tokens':1,'output_tokens':1}}
            raw=json.dumps(response).encode();self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    try:yield f'http://127.0.0.1:{server.server_port}',state
    finally:server.shutdown();server.server_close()

def ready(service,url,key=None,**options):
    session=service.providers.create(ProviderConfig(base_url=url,model='test-model',**options),key or token_hex(24))
    assert asyncio.run(service.providers.test(session.provider_session_id))['status']=='SUCCESS'
    return service.providers.get(session.provider_session_id)

def knowledge(rag):
    data=rag.knowledge.create([{'document_id':'refund','title':'退款','text':'退款审核通过后，五至七个工作日到账。先核验订单状态，不能声称已完成退款。'}],'真实冻结测试资料')
    return rag.knowledge.build(data.knowledge_dataset_id,1,embedding_model='sha256-lexical-bigram-v1')

def test_knowledge_draft_is_grounded_in_request_immutable_and_idempotent(tmp_path):
    service,_,_=setup(tmp_path);rag=RetrievalService(service);ai=AssistService(rag)
    with assistant_server() as (url,state):
        session=ready(service,url);identifier=str(uuid4());before=len(state['calls'])
        draft=asyncio.run(ai.knowledge(identifier,session.provider_session_id,'销售耳机的电商'))
        assert len(draft.content['documents'])==8 and draft.provider_call_count==1
        assert all(d['metadata']['source']=='AI_GENERATED_SIMULATION' for d in draft.content['documents'])
        assert not rag.store.list('knowledge_datasets') and not rag.store.list('retrieval_evalsets')
        again=asyncio.run(ai.knowledge(identifier,session.provider_session_id,'销售耳机的电商'))
        assert again==draft and len(state['calls'])==before+1
        with pytest.raises(ValueError):asyncio.run(ai.knowledge(identifier,session.provider_session_id,'另一家电商场景'))
        with pytest.raises(ValueError):rag.store.put('ai_drafts',draft)

@pytest.mark.parametrize('mode',['bad_category','echo_key'])
def test_invalid_generation_never_becomes_a_saved_draft_or_leaks_key(tmp_path,mode):
    service,_,_=setup(tmp_path);ai=AssistService(RetrievalService(service));secret=token_hex(24)
    with assistant_server() as (url,state):
        session=ready(service,url,secret);state['mode']=mode
        with pytest.raises(ProviderFailure) as error:asyncio.run(ai.knowledge(str(uuid4()),session.provider_session_id,'销售耳机的电商'))
        assert secret not in str(error.value) and not service.store.list('ai_drafts')
        assert all(secret not in p.read_text() for p in service.store.root.rglob('*.json'))

def test_generated_tests_use_exact_version_quotes_and_need_explicit_save(tmp_path):
    service,_,_=setup(tmp_path);rag=RetrievalService(service);ai=AssistService(rag);index=knowledge(rag)
    with assistant_server() as (url,state):
        session=ready(service,url)
        draft=asyncio.run(ai.tests(str(uuid4()),session.provider_session_id,index.index_id,6,['常规']))
        assert draft.provider_call_count==2 and len(draft.content['cases'])==6
        assert not rag.store.list('retrieval_evalsets')
        ev=rag.create_evalset(index.index_id,'确认后保存',draft.content['cases'])
        assert all(c.source=='ai_generated' and c.partition=='DEBUG' for c in ev.cases)
        assert all(c.generation['knowledge_version']==1 for c in ev.cases)
        other=knowledge(rag)
        with pytest.raises(ValueError):rag.create_evalset(other.index_id,'错配版本',draft.content['cases'])
        altered=json.loads(json.dumps(draft.content['cases']));altered[0]['generation']['knowledge_version']=999
        with pytest.raises(ValueError):rag.create_evalset(index.index_id,'伪造来源',altered)
        baseline=asyncio.run(rag.run(session.provider_session_id,ev.retrieval_eval_set_id))
        old=rag.store.get('knowledge_datasets',index.knowledge_dataset_id,1)
        docs=[{k:d[k] for k in ('document_id','title','text','metadata')} for d in old.documents]
        docs[0]['text']+=' 新增条件：需要订单号。'
        updated=rag.knowledge.create(docs,old.name,old.knowledge_dataset_id)
        target=rag.knowledge.build(updated.knowledge_dataset_id,updated.version,embedding_model='sha256-lexical-bigram-v1')
        change=rag.propose_change(baseline.run_id,'KNOWLEDGE_UPDATE',baseline.retrieval_config.model_dump(),
            '用户确认补充知识，原题与来源不变',[ev.cases[0].case_id],True,target.index_id)
        cloned=rag.store.get('retrieval_evalsets',change.target_eval_set_id)
        assert cloned.cases==ev.cases and cloned.index_id==target.index_id

@pytest.mark.parametrize('mode',['bad_quote','bad_id'])
def test_generated_test_labels_and_literal_source_quotes_are_validated(tmp_path,mode):
    service,_,_=setup(tmp_path);rag=RetrievalService(service);index=knowledge(rag)
    with assistant_server() as (url,state):
        session=ready(service,url);state['mode']=mode
        with pytest.raises(ProviderFailure,match='AI_OUTPUT_INVALID'):
            asyncio.run(AssistService(rag).tests(str(uuid4()),session.provider_session_id,index.index_id,4,['常规']))
        assert not service.store.list('ai_drafts')

def test_generated_cases_run_answers_and_independent_judge_end_to_end(tmp_path):
    service,_,_=setup(tmp_path);rag=RetrievalService(service);index=knowledge(rag)
    with assistant_server() as (url,main),assistant_server() as (judge_url,judge):
        base=ready(service,url);other=ready(service,judge_url)
        bound=service.providers.bind_judge(base.provider_session_id,other.provider_session_id)
        assert asyncio.run(service.providers.test(bound.provider_session_id))['status']=='SUCCESS'
        draft=asyncio.run(AssistService(rag).tests(str(uuid4()),bound.provider_session_id,index.index_id,3,['常规']))
        ev=rag.create_evalset(index.index_id,'生成题回答验收',draft.content['cases'])
        main_before=len(main['calls']);judge_before=len(judge['calls'])
        run=asyncio.run(rag.run(bound.provider_session_id,ev.retrieval_eval_set_id,verify_answers=True))
        assert run.status=='COMPLETE' and run.runtime_end_check['reliable_isolation']
        assert len(run.case_results)==len(run.answer_results)==3
        assert run.provider_call_count==6
        assert len(main['calls'])-main_before==len(judge['calls'])-judge_before==3
        assert all(r.judge_status=='SUCCESS' and r.original_status!='INVALID' for r in run.answer_results)
        assert all(c.source=='ai_generated' for c in rag.store.get('retrieval_evalsets',ev.retrieval_eval_set_id).cases)
        change=rag.propose_change(run.run_id,'TOP_K_CHANGE',{'top_k':5},'仅调整返回数量',
                                 [ev.cases[0].case_id],True)
        rag.apply(change.change_id)
        retest=asyncio.run(rag.run(bound.provider_session_id,ev.retrieval_eval_set_id,
            run_type='RETEST',parent_run_id=run.run_id,change_id=change.change_id,verify_answers=True))
        comparison=rag.compare(run.run_id,retest.run_id)
        analysis=asyncio.run(AssistService(rag).trace(str(uuid4()),bound.provider_session_id,
            ev.cases[0].case_id,comparison_id=comparison.comparison_id))
        for side in ('baseline','retest'):
            assert analysis.sources['comparison']['pair'][side]=={'evidence_reference':side+'.retrieval'}
            assert analysis.sources[side]['retrieval']['case_id']==ev.cases[0].case_id
        original_pair=next(p for p in comparison.case_pairs if p['case_id']==ev.cases[0].case_id)
        assert analysis.sources['comparison']['pair']['baseline_answer']==original_pair['baseline_answer']

def test_trace_reads_server_frozen_evidence_and_never_changes_verdicts(tmp_path):
    service,_,_=setup(tmp_path);rag=RetrievalService(service);ai=AssistService(rag);index=knowledge(rag)
    ev=rag.create_evalset(index.index_id,'轨迹测试',[{'case_id':'refund','query':'退款多久到账？','relevant_document_ids':['refund']}])
    with assistant_server() as (url,state):
        session=ready(service,url)
        run=asyncio.run(rag.run(session.provider_session_id,ev.retrieval_eval_set_id))
        path=rag.store.path('retrieval_runs',run.run_id);before=path.read_bytes()
        draft=asyncio.run(ai.trace(str(uuid4()),session.provider_session_id,'refund',run.run_id))
        assert draft.sources['run']['retrieval']==run.case_results[0]
        assert draft.sources['run']['effective_answer'] is None
        assert draft.sources['run']['verify_answers'] is False
        assert path.read_bytes()==before and not rag.store.list('retrieval_changes')
        state['mode']='bad_ref'
        with pytest.raises(ProviderFailure,match='AI_OUTPUT_INVALID'):asyncio.run(ai.trace(str(uuid4()),session.provider_session_id,'refund',run.run_id))

def test_independent_judge_routes_to_own_address_key_and_shared_budget(tmp_path):
    service,_,_=setup(tmp_path);main_key=token_hex(24);judge_key=token_hex(24)
    with assistant_server() as (url,main),assistant_server() as (judge_url,judge):
        base=ready(service,url,main_key,max_calls=2);other=ready(service,judge_url,judge_key)
        bound=service.providers.bind_judge(base.provider_session_id,other.provider_session_id)
        assert bound.configuration.judge_provider_configuration['base_url']==judge_url
        assert service.providers.get(base.provider_session_id).configuration.judge_provider_session_id is None
        async def run():
            p=ObservedProvider(bound.configuration,main_key,service.providers.judge_credential(bound.provider_session_id))
            try:
                await p.client('general').messages.create(messages=[{'role':'user','content':'Reply OK.'}])
                await p.client('judge').messages.create(messages=[{'role':'user','content':'Reply OK.'}])
                assert p.call_count==2 and len(p.observations)==2
                with pytest.raises(ProviderFailure,match='CALL_BUDGET_EXCEEDED'):
                    await p.client('judge').messages.create(messages=[{'role':'user','content':'Reply OK.'}])
            finally:await p.close()
        asyncio.run(run())
        assert main['calls'][-1]['auth']==main_key and judge['calls'][-1]['auth']==judge_key
        assert all(main_key not in p.read_text() and judge_key not in p.read_text() for p in service.store.root.rglob('*.json'))
        service.providers.delete(other.provider_session_id)
        with pytest.raises(ProviderFailure,match='CREDENTIAL_UNAVAILABLE'):service.providers.judge_credential(bound.provider_session_id)
        rag=RetrievalService(service);index=knowledge(rag)
        ev=rag.create_evalset(index.index_id,'缺少 Judge 的运行',[{'case_id':'x','query':'退款'}])
        # Admission fails before a RUNNING artifact can be created.
        with pytest.raises(ProviderFailure,match='CREDENTIAL_UNAVAILABLE'):
            asyncio.run(rag.run(bound.provider_session_id,ev.retrieval_eval_set_id))
        assert not service.store.list('retrieval_runs')

def test_assist_api_rejects_client_evidence_and_unknown_artifact(tmp_path):
    service,_,_=setup(tmp_path);configure(lambda:service)
    client=TestClient(app)
    response=client.post('/experiments/ai/trace',json={'request_id':str(uuid4()),'provider_session_id':'missing','case_id':'case','run_id':'missing','evidence':{'invented':True}})
    assert response.status_code==422
    assert client.get('/experiments/ai/drafts/missing').status_code==404
