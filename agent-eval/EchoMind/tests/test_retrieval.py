"""Real private Chroma + scripted local HTTP: no fabricated retrieval results."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
from secrets import token_hex
import pytest
from fastapi.testclient import TestClient
from core.skill_loader import SkillManager
from experiments.service import ExperimentService
from experiments.store import JsonStore
from experiments.providers import ProviderConfig
from experiments.retrieval_service import RetrievalService,config_diff
from experiments.retrieval_models import RetrievalCase,RetrievalConfig,RetrievalRun
from experiments.retrieval_knowledge import chunks_for,ChunkConfig,embed
from experiments.retrieval_metrics import case_metrics,aggregate,transition,answer_transition
from experiments.canonical import digest
from evaluation.models import CaseResult

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'EchoMindFrontend/tests'))
from local_server import provider_server

DOCS=[{'document_id':'opened','text':'已拆封商品 七天无理由退货条件 保持完整包装 不影响二次销售 先核验订单号 商品状态。'},
      {'document_id':'refund','text':'退款审核通过 原付款方式 到账时间 五至七个工作日。'},
      {'document_id':'delivery','text':'配送物流超时 查询运单 联系承运人核验延迟。'},
      {'document_id':'invoice','text':'电子发票 申请 抬头 税号 邮箱 订单完成后可下载。'},
      {'document_id':'password','text':'忘记密码 登录 账户重置 绑定手机号 验证码 不索要明文密码。'},
      {'document_id':'points','text':'会员积分 消费 兑换 一元消费一个积分 一百积分兑换一元。'},
      {'document_id':'address','text':'修改收货地址 揽收前可以修改 揽收后核验拦截。'},
      {'document_id':'warranty','text':'保修质量故障 售后维修 非人为原因 提供订单号和照片。'}]
QUERIES=['拆了还能退吗？','钱什么时候回到卡里？','包裹咋还没动？','报销的凭证怎么弄？',
         '进不去账户了怎么办？','花的钱有奖励吗？','送错地方能改吗？','买的坏了找谁？']
CASES=[{'case_id':f'rag_{i+1}','query':q,'relevant_document_ids':[d['document_id']],
        'expected_answer':d['text'],'source':'demo'} for i,(d,q) in enumerate(zip(DOCS,QUERIES))]

@pytest.fixture(scope='module')
def fixture(tmp_path_factory):
    path=tmp_path_factory.mktemp('retrieval')
    shutil.copytree(ROOT/'skills',path/'skills')
    manager=SkillManager(path/'skills');manager.load_strict()
    exp=ExperimentService(JsonStore(path/'store'),manager)
    rag=RetrievalService(exp)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    http=provider_server(port);url=f'http://127.0.0.1:{port}/v1'
    key=token_hex(24)
    session=exp.providers.create(ProviderConfig(provider='openai-compatible',base_url=url,model='phase4-rag',max_tokens=4096,max_calls=200),key)
    assert asyncio.run(exp.providers.test(session.provider_session_id))['status']=='SUCCESS'
    dataset=rag.knowledge.create(DOCS,'Demo retrieval')
    index=rag.knowledge.build(dataset.knowledge_dataset_id,1, embedding_model='sha256-lexical-bigram-v1')
    ev=rag.create_evalset(index.index_id,'Demo retrieval',CASES)
    yield rag,session.provider_session_id,dataset,index,ev,key
    http.shutdown();http.server_close()

@pytest.fixture(scope='module')
def pair(fixture):
    rag,sid,_,_,ev,_=fixture
    a=asyncio.run(rag.run(sid,ev.retrieval_eval_set_id,retrieval_config={'top_k':1},verify_answers=True))
    c=rag.propose_change(a.run_id,'QUERY_REWRITE_TOGGLE',{**a.retrieval_config.model_dump(),'query_rewrite':True},
                         '观察口语化 query 未命中，尝试保留原意的改写；可能引入意图漂移。',['rag_1'],True)
    c=rag.apply(c.change_id)
    b=asyncio.run(rag.run(sid,ev.retrieval_eval_set_id,run_type='RETEST',parent_run_id=a.run_id,change_id=c.change_id,verify_answers=True))
    return a,b,c

def test_knowledge_version_immutable_and_new_revision(fixture):
    rag,_,_,_,_,_=fixture
    d=rag.knowledge.create(DOCS,'immutable')
    path=rag.store.path('knowledge_datasets',d.knowledge_dataset_id,1);raw=path.read_bytes()
    with pytest.raises(ValueError):rag.store.put('knowledge_datasets',d)
    changed=deepcopy(DOCS);changed[0]['text']+=' 新条件。'
    v2=rag.knowledge.create(changed,'immutable',d.knowledge_dataset_id)
    assert v2.version==2 and v2.knowledge_hash!=d.knowledge_hash
    assert path.read_bytes()==raw and rag.store.get('knowledge_datasets',d.knowledge_dataset_id).version==2
    assert len(d.documents[0]['content_hash'])==64 and d.documents[0]['updated_at']

def test_chunk_ids_stable_and_full_content_sensitive(fixture):
    _,_,d,i,_,_=fixture
    assert chunks_for(d,i.chunk_config)==i.chunks
    modified=d.model_copy(update={'documents':[{**d.documents[0],'text':d.documents[0]['text']+'改变结尾'}]})
    chunks=chunks_for(modified,i.chunk_config)
    assert chunks[0]['chunk_id']!=i.chunks[0]['chunk_id'] and chunks[0]['text_hash']!=i.chunks[0]['text_hash']
    assert len(chunks[0]['chunk_id'])==64

def test_chunking_normalization_and_overlap(fixture):
    _,_,d,_,_,_=fixture
    doc=d.model_copy(update={'documents':[{**d.documents[0],'text':'ＡＢ '*60}]})
    cs=chunks_for(doc,ChunkConfig(chunk_size=50,chunk_overlap=10))
    assert len(cs)>1 and cs[0]['text'][-10:]==cs[1]['text'][:10]
    assert 'Ａ' not in cs[0]['text']
    with pytest.raises(ValueError):ChunkConfig(chunk_size=50,chunk_overlap=50)

@pytest.mark.parametrize('field',['knowledge_snapshot','chunk_snapshot_hash','embedding_snapshot','index_snapshot'])
def test_baseline_retest_fixed_snapshots(pair,field):
    a,b,_=pair
    assert a.controls[field]==b.controls[field]

def test_independent_chroma_namespace_and_shared_online_collection(fixture):
    rag,_,d,index,_,_=fixture
    second=rag.knowledge.create(DOCS,'independent');other=rag.knowledge.build(second.knowledge_dataset_id,1, embedding_model='sha256-lexical-bigram-v1')
    assert index.collection_name!=other.collection_name and index.index_generation!=other.index_generation
    client=rag.knowledge.client()
    online=client.get_or_create_collection('knowledge_base',embedding_function=None)
    online.upsert(ids=['pollution'],documents=['退款 '+('新知识 '*100)],embeddings=[embed('退款')])
    result=rag.knowledge.search(index,'退款',20)
    assert 'pollution' not in [r['chunk_id'] for r in result]
    assert len(result)==len(index.chunks)

def test_cache_disabled_and_no_cross_run_artifact_pollution(fixture,pair):
    rag,_,_,index,_,_=fixture
    a,b,_=pair
    expected={'cache_enabled':False,'cache_namespace':None,'cache_policy':'DISABLED'}
    assert a.controls['cache']==b.controls['cache']==expected
    assert not a.runtime_end_check['cache_used'] and not b.runtime_end_check['shared_online_chroma_accessed']
    # Query twice, alter only an unrelated file named like a legacy cache.
    before=rag.knowledge.search(index,'退款',5)
    (rag.store.root/'legacy_cache.json').write_text('{"fake":"result"}')
    assert rag.knowledge.search(index,'退款',5)==before
    with pytest.raises(ValueError):RetrievalConfig(cache_enabled=True)

def results(ids):return [{'document_id':d,'chunk_id':f'c{i}'} for i,d in enumerate(ids)]

@pytest.mark.parametrize('ids,rank,hit1,hit3',[(['good','bad'],1,1,1),(['bad','bad','good'],3,0,1),(['bad'],None,0,0)])
def test_hit_and_first_relevant_rank(ids,rank,hit1,hit3):
    m=case_metrics(RetrievalCase(case_id='c',query='q',relevant_document_ids=['good']),results(ids),3)
    assert (m['relevant_rank'],m['hit_at_1'],m['hit_at_3'])==(rank,hit1,hit3)

def test_hit3_and_mrr_use_full_fixed_pool_even_when_top_k_is_one():
    c=RetrievalCase(case_id='c',query='q',relevant_document_ids=['good'])
    pool=results(['bad','good','other'])
    m=case_metrics(c,pool[:1],1,pool)
    assert m['hit_at_1']==0 and m['hit_at_3']==1 and m['mrr']==.5
    assert m['relevant_rank']==2 and m['returned_relevant_rank'] is None
    assert m['recall_at_k']==m['precision_at_k']==m['ndcg_at_k']==0

def test_recall_precision_mrr_ndcg_multi_document_dedup():
    import math
    c=RetrievalCase(case_id='c',query='q',relevant_document_ids=['a','b'])
    m=case_metrics(c,results(['a','a','b']),3)
    assert m['recall_at_k']==1 and m['precision_at_k']==2/3 and m['mrr']==1
    assert m['ndcg_at_k']==pytest.approx((1+1/math.log2(4))/(1+1/math.log2(3)))
    m=case_metrics(c,results(['x','a']),3)
    assert m['recall_at_k']==.5 and m['precision_at_k']==1/3 and m['mrr']==.5

def test_chunk_ground_truth():
    c=RetrievalCase(case_id='c',query='q',relevant_chunk_ids=['c1'])
    m=case_metrics(c,results(['a','a']),3)
    assert m['ground_truth_granularity']=='chunk' and m['relevant_rank']==2 and m['mrr']==.5
    with pytest.raises(ValueError):RetrievalCase(case_id='c',query='q',relevant_document_ids=['a'],relevant_chunk_ids=['c0'])

def test_unlabeled_unavailable_and_invalid_excluded():
    c=RetrievalCase(case_id='c',query='q')
    m=case_metrics(c,results(['a']),3)
    assert m['mrr'] is None and m['unavailable_reason']=='NO_RELEVANCE_LABELS'
    a=aggregate([{'status':'SUCCESS','metrics':m},{'status':'INVALID','metrics':dict.fromkeys(m,1)}])
    assert a['mrr'] is None and a['denominators']['mrr']==0 and a['invalid']==1

def test_rewrite_actual_http_evidence_and_golden_improvement(fixture,pair):
    rag,_,_,_,_,_=fixture;a,b,c=pair
    assert a.status==b.status=='COMPLETE'
    assert len(a.case_results)==len(b.case_results)==8
    assert any(r['metrics']['relevant_rank']!=1 for r in a.case_results)
    assert any(r['effective_query']!=r['query'] for r in b.case_results)
    assert all(r['rewrite_status']=='SUCCESS' and r['rewrite_config']['prompt_hash'] for r in b.case_results)
    comparison=rag.compare(a.run_id,b.run_id)
    assert comparison.comparable and comparison.single_recorded_change and not comparison.attributable
    assert any(p['transition']=='RETRIEVAL_IMPROVED' for p in comparison.case_pairs)
    assert b.metrics['hit_at_1']>a.metrics['hit_at_1'] and b.metrics['mrr']>a.metrics['mrr']
    assert all(r['latency_ms']>=0 and len(r['pre_rerank_results'])==8 for r in b.case_results)

@pytest.mark.parametrize('model,config,answers,stage',[('rag-rewrite-failed',{'query_rewrite':True},False,'rewrite'),
    ('rag-rerank-failed',{'rerank':True},False,'rerank'),('rag-judge-failed',{},True,'judge'),('rag-agent-failed',{},True,'agent')])
def test_real_provider_failure_invalid(fixture,model,config,answers,stage):
    rag,sid,_,_,ev,_=fixture
    config_provider=rag.providers.get(sid).configuration.model_copy(update={'model':model})
    session=rag.providers.create(config_provider,token_hex(24));asyncio.run(rag.providers.test(session.provider_session_id))
    run=asyncio.run(rag.run(session.provider_session_id,ev.retrieval_eval_set_id,retrieval_config=config,verify_answers=answers))
    if stage in {'rewrite','rerank'}:
        assert all(r['status']=='INVALID' and r[stage+'_status']=='FAILED' and not r['results'] for r in run.case_results)
        assert run.metrics['valid']==0 and run.metrics['mrr'] is None
    else:
        assert all(r.final_status=='INVALID' and not r.scores for r in run.answer_results)
        assert all(r.judge_status=='FAILED' if stage=='judge' else r.execution_status=='FAILED' for r in run.answer_results)

@pytest.mark.parametrize('kind,field,value',[('TOP_K_CHANGE','top_k',3),('QUERY_REWRITE_TOGGLE','query_rewrite',True),('RERANK_TOGGLE','rerank',True)])
def test_each_change_one_effective_variable(fixture,pair,kind,field,value):
    rag=fixture[0];base=pair[0]
    after={**base.retrieval_config.model_dump(),field:value}
    change=rag.propose_change(base.run_id,kind,after,'依据 Case 证据',['rag_1'],True)
    applied=rag.apply(change.change_id)
    assert applied.observed_diff==applied.declared_diff==[{'path':field,'before':base.retrieval_config.model_dump()[field],'after':value}]
    assert rag.apply(change.change_id)==applied
    with pytest.raises(ValueError):rag.store.put('retrieval_changes',applied)

@pytest.mark.parametrize('reason,confirmed',[('',True),('  ',True),('has reason',False)])
def test_change_requires_reason_and_human_confirmation(fixture,pair,reason,confirmed):
    base=pair[0]
    with pytest.raises(ValueError):fixture[0].propose_change(base.run_id,'TOP_K_CHANGE',{'top_k':4},reason,['rag_1'],confirmed)

def test_multiple_changes_and_noop_rejected(fixture,pair):
    base=pair[0]
    for config in [{'top_k':4,'query_rewrite':True},{'top_k':1}]:
        with pytest.raises(ValueError):fixture[0].propose_change(base.run_id,'TOP_K_CHANGE',config,'reason',['rag_1'],True)

def test_rerank_actual_http_keeps_pre_post_order_and_scores(fixture):
    rag,sid,_,_,ev,_=fixture
    run=asyncio.run(rag.run(sid,ev.retrieval_eval_set_id,retrieval_config={'rerank':True,'top_k':3}))
    assert run.status=='COMPLETE' and run.provider_call_count==8
    for row in run.case_results:
        assert row['rerank_status']=='SUCCESS' and len(row['pre_rerank_results'])==len(row['post_rerank_results'])==8
        assert {r['chunk_id'] for r in row['pre_rerank_results']}=={r['chunk_id'] for r in row['post_rerank_results']}
        assert all(0<=r['rerank_score']<=1 for r in row['post_rerank_results'])

def test_unrecorded_retest_rejected(fixture,pair):
    rag,sid,_,_,ev,_=fixture;a,_,c=pair
    with pytest.raises(ValueError,match='Unrecorded'):
        asyncio.run(rag.run(sid,ev.retrieval_eval_set_id,run_type='RETEST',parent_run_id=a.run_id,change_id=c.change_id,
                           retrieval_config={'query_rewrite':True,'top_k':5},verify_answers=True))

def test_natural_language_expectations_not_keyword_hard_rules(fixture):
    rag,sid,_,index,_,_=fixture
    ev=rag.create_evalset(index.index_id,'natural expectations',[{'case_id':'natural','query':'退款',
        'relevant_document_ids':['refund'],'must_not_do':['退款']}])
    run=asyncio.run(rag.run(sid,ev.retrieval_eval_set_id,verify_answers=True))
    assert not run.answer_results[0].hard_rule_violations

def test_hard_rule_and_human_override_keep_original_machine_evidence(fixture):
    rag,sid,_,index,_,_=fixture
    ev=rag.create_evalset(index.index_id,'hard rule',[{'case_id':'hard','query':'退款',
        'relevant_document_ids':['refund'],'executable_rules':[{'type':'required_tool','tool':'check_billing_fields'}]}])
    run=asyncio.run(rag.run(sid,ev.retrieval_eval_set_id,verify_answers=True))
    item=run.answer_results[0]
    assert item.original_status=='FAIL' and item.hard_rule_violations and item.judge_status=='NOT_REQUIRED'
    review=rag.review(run.run_id,item.case_id,'PASS','人工核对后覆盖规则适用范围，保留原违规')
    assert review.effective_result.hard_rule_override and review.effective_result.original_status=='FAIL'
    assert review.effective_result.hard_rule_violations==item.hard_rule_violations

@pytest.mark.parametrize('key',['knowledge_snapshot','chunk_snapshot_hash','embedding_snapshot','cache','evaluation_protocol_hash','pipeline','retrieval_implementation','execution_order'])
def test_control_change_blocks_comparison_and_does_not_claim_attribution(fixture,pair,key):
    rag=fixture[0];a,b,_=pair
    fake=b.model_copy(update={'run_id':str(__import__('uuid').uuid4()),'controls':{**b.controls,key:{'changed':True}}})
    rag.store.put('retrieval_runs',fake)
    comp=rag.compare(a.run_id,fake.run_id)
    assert not comp.comparable and not comp.attributable and key.upper()+'_CHANGED' in comp.comparability_reasons
    assert all(p['transition']=='NOT_COMPARABLE' for p in comp.case_pairs)

@pytest.mark.parametrize('before,after,expected',[(0.,1.,'RETRIEVAL_IMPROVED'),(1.,0.,'RETRIEVAL_REGRESSED'),(.5,.5,'RETRIEVAL_UNCHANGED')])
def test_rank_based_transition_ignores_vector_score(before,after,expected):
    def row(m):return {'status':'SUCCESS','metrics':{'mrr':m,'recall_at_k':m},'results':[{'score':12345}]}
    assert transition(row(before),row(after))[0]==expected
    assert transition(row(before),None)==('NOT_COMPARABLE','MISSING_RESULT')

def test_partial_does_not_erase_completed_valid_pairs(fixture,pair):
    rag=fixture[0];a,b,_=pair
    partial=b.model_copy(update={'run_id':str(__import__('uuid').uuid4()),'status':'PARTIAL','case_results':b.case_results[:-1],
                                'answer_results':b.answer_results[:-1]})
    rag.store.put('retrieval_runs',partial)
    comp=rag.compare(a.run_id,partial.run_id)
    assert comp.comparable and comp.comparison_completeness=='PARTIAL' and comp.matched_case_count==7
    assert comp.case_pairs[-1]['transition']=='NOT_COMPARABLE' and comp.case_pairs[-1]['reason']=='MISSING_RESULT'
    assert sum(p['transition']!='NOT_COMPARABLE' for p in comp.case_pairs)==7
    assert comp.paired_metrics['baseline']['denominators']['mrr']==7

@pytest.mark.parametrize('a,b,expected',[('FAIL','PASS','FAIL→PASS'),('PASS','FAIL','PASS→FAIL'),('PASS','PASS','PASS→PASS'),('FAIL','FAIL','FAIL→FAIL'),('INVALID','PASS','NOT_COMPARABLE')])
def test_answer_transitions_independent_of_retrieval(a,b,expected):
    def answer(status):return CaseResult(case_id='c',execution_status='SUCCESS' if status!='INVALID' else 'FAILED',judge_status='NOT_REQUIRED',original_status=status,original_reason='evidence')
    assert answer_transition(answer(a),answer(b))==expected
    retrieval={'status':'SUCCESS','metrics':{'mrr':0.,'recall_at_k':0.}}
    improved={'status':'SUCCESS','metrics':{'mrr':1.,'recall_at_k':1.}}
    assert transition(retrieval,improved)[0]=='RETRIEVAL_IMPROVED'
    assert answer_transition(answer('FAIL'),answer('FAIL'))=='FAIL→FAIL'

def test_answer_actual_phase2_evidence_and_review_preserves_machine(fixture,pair):
    rag=fixture[0];a,b,_=pair
    assert any(x.original_status=='FAIL' for x in a.answer_results) and all(x.original_status=='PASS' for x in b.answer_results)
    assert b.answer_results[0].turn_evidence[0].tools_used==['frozen_retrieval']
    assert b.answer_results[0].turn_evidence[0].tool_traces[0]['index_id']==b.controls['index_snapshot']['index_id']
    item=next(x for x in a.answer_results if x.original_status=='FAIL')
    with pytest.raises(ValueError):rag.review(a.run_id,item.case_id,'PASS','')
    before=rag.store.path('retrieval_runs',a.run_id).read_bytes()
    reviewed=rag.review(a.run_id,item.case_id,'PASS','核对知识后人工纠正质量判断')
    assert reviewed.effective_result.original_status=='FAIL' and reviewed.effective_result.final_status=='PASS'
    assert rag.store.path('retrieval_runs',a.run_id).read_bytes()==before
    assert rag.view(a.run_id)['answer_metrics']['passed']==a.answer_metrics['passed']+1

def test_knowledge_change_requires_new_baseline(fixture):
    rag,sid,_,_,_,_=fixture
    d=rag.knowledge.create(DOCS,'new versions');i=rag.knowledge.build(d.knowledge_dataset_id,1, embedding_model='sha256-lexical-bigram-v1')
    ev=rag.create_evalset(i.index_id,'versions',CASES)
    a=asyncio.run(rag.run(sid,ev.retrieval_eval_set_id))
    c=rag.apply(rag.propose_change(a.run_id,'TOP_K_CHANGE',{'top_k':4},'more candidates',['rag_1'],True).change_id)
    rag.knowledge.create([{**d,'text':d['text']+'新条件'} for d in DOCS],'new versions',d.knowledge_dataset_id)
    with pytest.raises(ValueError,match='Knowledge version changed'):
        asyncio.run(rag.run(sid,ev.retrieval_eval_set_id,run_type='RETEST',parent_run_id=a.run_id,change_id=c.change_id))

def test_private_index_tampering_detected(fixture):
    rag=fixture[0]
    d=rag.knowledge.create(DOCS,'tamper');i=rag.knowledge.build(d.knowledge_dataset_id,1, embedding_model='sha256-lexical-bigram-v1')
    col=rag.knowledge.client().get_collection(i.collection_name,embedding_function=None)
    col.update(ids=[i.chunks[0]['chunk_id']],documents=['tampered knowledge'],embeddings=[embed('tampered knowledge')])
    with pytest.raises(ValueError,match='drift'):rag.knowledge.verify(i)

def test_actual_interruption_keeps_completed_pairs_comparable(fixture,pair,monkeypatch):
    import experiments.retrieval_runtime as module
    rag,sid,_,_,ev,_=fixture;a,_,change=pair
    original=module.rewrite;count=0
    async def interrupted(provider,query):
        nonlocal count
        count+=1
        if count==3: raise asyncio.CancelledError()
        return await original(provider,query)
    monkeypatch.setattr(module,'rewrite',interrupted)
    run=asyncio.run(rag.run(sid,ev.retrieval_eval_set_id,run_type='RETEST',parent_run_id=a.run_id,
                            change_id=change.change_id,verify_answers=True))
    assert run.status=='PARTIAL' and len(run.case_results)==2 and run.runtime_end_check['reliable_isolation']
    comp=rag.compare(a.run_id,run.run_id)
    assert comp.comparable and comp.comparison_completeness=='PARTIAL'
    assert sum(p['transition']!='NOT_COMPARABLE' for p in comp.case_pairs)==2
    assert sum(p['answer_transition']!='NOT_COMPARABLE' for p in comp.case_pairs)==2

def test_end_guard_drift_invalidates_all_acquired_quality(fixture,monkeypatch):
    import experiments.retrieval_service as module
    rag,sid,_,_,ev,_=fixture
    original=module.implementation_snapshot;count=0
    def changed():
        nonlocal count
        count+=1
        return original() if count==1 else {'changed':'implementation'}
    monkeypatch.setattr(module,'implementation_snapshot',changed)
    run=asyncio.run(rag.run(sid,ev.retrieval_eval_set_id,verify_answers=True))
    assert run.status=='FAILED' and not run.runtime_end_check['reliable_isolation']
    assert all(r['status']=='INVALID' and r['metrics']['mrr'] is None for r in run.case_results)
    assert all(r.final_status=='INVALID' and r.evaluation_error and not r.scores for r in run.answer_results)
    assert run.metrics['valid']==0 and run.answer_metrics['valid']==0

def test_review_unknown_answer_rejected(fixture,pair):
    with pytest.raises(ValueError,match='Answer Case not found'):fixture[0].review(pair[0].run_id,'not-an-answer','PASS','reason')

def test_key_not_written_anywhere_and_terminal_immutable(fixture,pair):
    rag,_,_,_,_,key=fixture
    for p in rag.store.root.rglob('*'):
        if p.is_file():assert key.encode() not in p.read_bytes()
    with pytest.raises(ValueError):rag.store.put('retrieval_runs',pair[0])
    assert 'credential' not in json.dumps(pair[0].model_dump()).lower()

def test_restart_missing_key_and_interrupted_run(fixture,pair):
    rag=fixture[0];a=pair[0]
    run=a.model_copy(update={'run_id':str(__import__('uuid').uuid4()),'status':'RUNNING'})
    rag.store.put('retrieval_runs',run)
    restored=ExperimentService(JsonStore(rag.store.root),rag.experiments.skills.manager)
    RetrievalService(restored)
    assert restored.store.get('retrieval_runs',run.run_id).status=='FAILED'
    assert restored.providers.public(restored.providers.get(a.provider_session_id))['credential_status']=='UNAVAILABLE'

def test_retrieval_api_contract_and_safe_validation(fixture):
    from experiments.api import configure
    from experiments.app import app
    rag,sid,_,index,ev,key=fixture
    rag.experiments.retrieval=rag;configure(lambda:rag.experiments)
    client=TestClient(app,raise_server_exceptions=True)
    response=client.post('/experiments/retrieval-runs',json={'provider_session_id':sid,'retrieval_eval_set_id':ev.retrieval_eval_set_id})
    assert response.status_code==200
    run=response.json();assert run['experiment_type']=='RETRIEVAL'
    assert client.get('/experiments/retrieval-runs/'+run['run_id']).json()['run']['runtime_scope']=='RAG_RETRIEVAL_ENABLED'
    assert client.post('/experiments/retrieval-runs',json={'api_key':key}).status_code==422
    assert key not in client.post('/experiments/retrieval-runs',json={'api_key':key}).text
    assert client.get('/experiments/knowledge-indices/'+index.index_id).status_code==200
    assert client.get('/experiments/retrieval-history').status_code==200
