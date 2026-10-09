"""Actual HTTP transport + frozen Chroma; scripted responses are not model-quality evidence."""
import asyncio
from copy import deepcopy
from pathlib import Path
import shutil
import socket
import sys
from types import SimpleNamespace
import pytest
from core.skill_loader import SkillManager
from experiments.service import ExperimentService
from experiments.store import JsonStore
from experiments.providers import ProviderConfig, ProviderFailure
from experiments.retrieval_service import RetrievalService
from experiments.practice_service import PracticeService
from experiments.career_service import CareerService
from experiments.career_evidence import normalize

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'EchoMindFrontend/tests'))
from local_server import provider_server
CONTEXT={'project_name':'Agent Eval 功能验收样例','project_context':'OTHER','motivation':'验证知识更新的证据链',
    'target_users':'功能验收人员','user_problem':'原知识缺少条件','why_ai':'根据知识回答自然语言问题',
    'user_roles':['功能验收'],'user_contribution':'确认模拟资料和验收要求','system_contribution':'平台执行检索和统计',
    'existing_capabilities':'平台已有评测与材料模块','real_users':False,'deployed':False,
    'reflection':'扩大样本，验证退化与随机性。','reflection_confirmed':True,'confirmed':True}

@pytest.fixture
def env(tmp_path):
    shutil.copytree(ROOT/'skills',tmp_path/'skills')
    manager=SkillManager(tmp_path/'skills');manager.load_strict()
    exp=ExperimentService(JsonStore(tmp_path/'store'),manager)
    rag=RetrievalService(exp);exp.retrieval=rag
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    server=provider_server(port)
    session=exp.providers.create(ProviderConfig(provider='openai-compatible',base_url=f'http://127.0.0.1:{port}/v1',model='scripted-practice-test',max_tokens=4096,max_calls=100),'local-fixture-only')
    assert asyncio.run(exp.providers.test(session.provider_session_id))['status']=='SUCCESS'
    docs=[{'document_id':'opened','title':'退货政策','text':'已拆封商品，保持完整包装、不影响二次销售，先核验订单号；定制商品不适用。'}]
    knowledge=rag.knowledge.create(docs,'明确标注的模拟业务知识')
    index=rag.knowledge.build(knowledge.knowledge_dataset_id,1, embedding_model='sha256-lexical-bigram-v1')
    yield SimpleNamespace(exp=exp,rag=rag,practice=PracticeService(rag),sid=session.provider_session_id,docs=docs,k=knowledge,index=index)
    server.shutdown();server.server_close()

def test_chat_grounding_citations_and_frozen_multi_turn_context(env):
    a=asyncio.run(env.practice.chat(env.sid,env.index.index_id,'拆了还能退吗？'))
    b=asyncio.run(env.practice.chat(env.sid,env.index.index_id,'定制商品也可以吗？',conversation_id=a.conversation_id))
    assert a.status==b.status=='SUCCESS' and a.citations[0]['document_id']=='opened'
    assert b.context==[{'role':'user','content':a.message},{'role':'assistant','content':a.answer}]
    assert a.message in b.retrieval['effective_query']
    assert env.practice.conversation(a.conversation_id)==[a,b]
    with pytest.raises(ProviderFailure,match='CHAT_CONFIGURATION_CHANGED'):
        asyncio.run(env.practice.chat(env.sid,env.index.index_id,'改配置',{'top_k':1},a.conversation_id))
    with pytest.raises(ValueError):env.rag.store.put('chat_turns',a)
    assert 'local-fixture-only' not in env.rag.store.path('chat_turns',a.turn_id).read_text()

def test_model_failure_does_not_create_fake_answer(env):
    config=env.exp.providers.get(env.sid).configuration.model_copy(update={'model':'rag-agent-failed'})
    session=env.exp.providers.create(config,'fixture-failure')
    asyncio.run(env.exp.providers.test(session.provider_session_id))
    t=asyncio.run(env.practice.chat(session.provider_session_id,env.index.index_id,'拆了还能退吗？'))
    assert t.status=='FAILED' and not t.answer and not t.citations
    with pytest.raises(ValueError):env.practice.to_case(t.turn_id,'正确回答',['opened'],[],[],'DEBUG',True)

def test_chat_to_case_requires_user_criteria_and_keeps_provenance(env):
    t=asyncio.run(env.practice.chat(env.sid,env.index.index_id,'拆了还能退吗？'))
    with pytest.raises(ValueError):env.practice.to_case(t.turn_id,'',['opened'],[],[],'DEBUG',True)
    with pytest.raises(ValueError):env.practice.to_case(t.turn_id,'先核验',['opened'],[],[],'DEBUG',False)
    case=env.practice.to_case(t.turn_id,'先核验订单和商品状态',['opened'],[],[],'DEBUG',True)
    assert case.source_chat_turn_id==t.turn_id and case.expected_answer!=t.answer
    ev=env.rag.create_evalset(env.index.index_id,'真实对话转测试',[case.model_dump()])
    run=asyncio.run(env.rag.run(env.sid,ev.retrieval_eval_set_id,verify_answers=True))
    assert run.status=='COMPLETE' and run.answer_results[0].judge_status=='SUCCESS'
    evidence=CareerService(env.exp).build('RETRIEVAL',run.run_id)
    assert any(s['group']=='chat_turns' for s in evidence.source_map.values())
    assert not any('平台预设题' in l for l in evidence.limitations)

def knowledge_pair(env):
    cases=[{'case_id':'opened','query':'拆了还能退吗？','relevant_document_ids':['opened'],'expected_answer':'核验商品状态','partition':'HOLDOUT'}]
    ev=env.rag.create_evalset(env.index.index_id,'知识实验',cases)
    base=asyncio.run(env.rag.run(env.sid,ev.retrieval_eval_set_id,verify_answers=True))
    docs=deepcopy(env.docs);docs[0]['text']+=' 非定制商品在七天内可核验退货。'
    k2=env.rag.knowledge.create(docs,'知识实验',env.k.knowledge_dataset_id)
    i2=env.rag.knowledge.build(k2.knowledge_dataset_id,2, embedding_model='sha256-lexical-bigram-v1')
    change=env.rag.propose_change(base.run_id,'KNOWLEDGE_UPDATE',base.retrieval_config.model_dump(),
        '原知识缺少时间条件，补充七天范围；需检查旧题，不更改检索策略。',['opened'],True,i2.index_id)
    change=env.rag.apply(change.change_id)
    after=asyncio.run(env.rag.run(env.sid,change.target_eval_set_id,run_type='RETEST',parent_run_id=base.run_id,
        change_id=change.change_id,verify_answers=True))
    return base,after,change,i2

def test_knowledge_update_preserves_tests_and_retrieval_with_real_version_evidence(env):
    a,b,c,index=knowledge_pair(env)
    comparison=env.rag.compare(a.run_id,b.run_id)
    assert comparison.comparable and comparison.single_recorded_change and not comparison.attributable
    assert a.controls['knowledge_snapshot']['version']==1 and b.controls['knowledge_snapshot']['version']==2
    assert a.controls['eval_set_snapshot']['cases']==b.controls['eval_set_snapshot']['cases']
    assert a.retrieval_config==b.retrieval_config
    assert comparison.case_pairs[0]['partition']=='HOLDOUT'
    assert env.rag.store.get('knowledge_datasets',env.k.knowledge_dataset_id,1).documents[0]['text']==env.docs[0]['text']
    saved=env.practice.conclude(comparison.comparison_id,'REVISE','当前样本过少，需要验证更多边界题。',True)
    career=CareerService(env.exp)
    evidence=career.build('RETRIEVAL',a.run_id,b.run_id,comparison.comparison_id,context=CONTEXT)
    assert evidence.retrieval_evidence['knowledge_update']['edited_ids']==['opened']
    assert any(claim.claim_type=='KNOWLEDGE_UPDATE' for claim in evidence.claims)
    view=normalize(evidence,'EVALUATION_WORKBENCH','AI_EVALUATION_PLATFORM_PM')
    assert not view.conflicts
    assert any(c.claim_type=='USER_EXPERIMENT_CONCLUSION' for c in evidence.claims)
    material=career.generate_v2(evidence.evidence_object_id)
    assert '本轮只更新知识版本' in material.sections['case_study'][0].text or any('本轮只更新知识版本' in s.text for s in material.sections['case_study'])
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from experiments.api import configure, install_validation_handler
    from experiments.practice_api import router
    configure(lambda:env.exp)
    app=FastAPI();app.include_router(router);install_validation_handler(app)
    question=material.defense[0]
    with TestClient(app) as client:
        response=client.post('/experiments/interview-attempts',json={'material_id':material.material_id,
            'question_id':question.question_id,'answer':'我比较了相同题目，知识增加了时间条件。',
            'claim_ids':question.claim_ids[:1],'limitations':'只做了小样本模拟实验。'})
        assert response.status_code==200,response.text
        assert response.json()['checks']['limitations_written']
        invalid=client.post('/experiments/interview-attempts',json={'material_id':material.material_id,
            'question_id':question.question_id,'answer':'没有证据的结论','claim_ids':['invented_claim']})
        assert invalid.status_code==409

def test_knowledge_change_rejects_second_variable_or_other_dataset(env):
    a,b,c,index=knowledge_pair(env)
    with pytest.raises(ValueError):env.rag.propose_change(a.run_id,'KNOWLEDGE_UPDATE',{'top_k':1},'同时修改',['opened'],True,index.index_id)
    other=env.rag.knowledge.create(env.docs,'另一个知识库');other_index=env.rag.knowledge.build(other.knowledge_dataset_id,1, embedding_model='sha256-lexical-bigram-v1')
    with pytest.raises(ValueError):env.rag.propose_change(a.run_id,'KNOWLEDGE_UPDATE',a.retrieval_config.model_dump(),'换库',['opened'],True,other_index.index_id)

def test_missing_knowledge_case_is_explicit_and_becomes_retrievable(env):
    cases=[{'case_id':'new','query':'会员积分一元消费多少积分？','relevant_document_ids':['points'],
            'allow_missing_knowledge':True,'expected_answer':'每一元消费一个积分'}]
    ev=env.rag.create_evalset(env.index.index_id,'缺失知识',cases)
    a=asyncio.run(env.rag.run(env.sid,ev.retrieval_eval_set_id))
    assert a.metrics['hit_at_1']==0
    k=env.rag.knowledge.create(env.docs+[{'document_id':'points','text':'会员积分：每一元消费一个积分，一百积分兑换一元。'}],'补充',env.k.knowledge_dataset_id)
    idx=env.rag.knowledge.build(k.knowledge_dataset_id,2, embedding_model='sha256-lexical-bigram-v1')
    c=env.rag.propose_change(a.run_id,'KNOWLEDGE_UPDATE',a.retrieval_config.model_dump(),'补充积分知识',['new'],True,idx.index_id)
    env.rag.apply(c.change_id)
    b=asyncio.run(env.rag.run(env.sid,c.target_eval_set_id,run_type='RETEST',parent_run_id=a.run_id,change_id=c.change_id))
    assert b.metrics['hit_at_1']==1 and env.rag.compare(a.run_id,b.run_id).comparable
    comparison=env.rag.compare(a.run_id,b.run_id)
    env.practice.conclude(comparison.comparison_id,'REVISE','先补旧题回归，单题不代表整体质量。',True)
    career=CareerService(env.exp)
    e=career.build('RETRIEVAL',a.run_id,b.run_id,comparison.comparison_id,context=CONTEXT)
    m=career.generate_v2(e.evidence_object_id)
    sections={row.section_id:row.text for row in m.sections['case_study']}
    assert '未检索到' in sections['problem'] and 'None' not in sections['problem']
    assert '只更换知识版本及其索引' in sections['control']
    assert '保存的实验结论：继续调整' in sections['reflection']
    assert '复测知识 v2 为 2 份文档' in sections['technical']
    assert 'None' not in '\n'.join(s.text for s in m.sections['interview'])


def test_repetitions_are_distinct_frozen_runs_with_original_intact(env):
    a,_,_,_=knowledge_pair(env)
    original=env.rag.store.path('retrieval_runs',a.run_id).read_bytes()
    report=asyncio.run(env.practice.repeat(a.run_id,env.sid,2))
    assert len(set(report.run_ids))==2 and a.run_id not in report.run_ids
    assert all(env.rag.store.get('retrieval_runs',i).controls==a.controls for i in report.run_ids)
    assert report.summary['hit_at_1']['minimum']==report.summary['hit_at_1']['maximum']==1
    assert env.rag.store.path('retrieval_runs',a.run_id).read_bytes()==original
    with pytest.raises(ValueError):env.rag.store.put('repeat_reports',report)

def test_conversation_artifact_is_workspace_local(env,tmp_path):
    t=asyncio.run(env.practice.chat(env.sid,env.index.index_id,'拆了还能退吗？'))
    other=PracticeService(SimpleNamespace(store=JsonStore(tmp_path/'other-store')))
    with pytest.raises(FileNotFoundError):other.conversation(t.conversation_id)

def test_demo_knowledge_does_not_relabel_user_test_as_platform_preset(env):
    docs=deepcopy(env.docs);docs[0]['metadata']={'purpose':'DEMO_POLICY_NOT_BUSINESS_COMMITMENT'}
    k=env.rag.knowledge.create(docs,'Demo 政策')
    idx=env.rag.knowledge.build(k.knowledge_dataset_id,1, embedding_model='sha256-lexical-bigram-v1')
    ev=env.rag.create_evalset(idx.index_id,'本人确认测试',[{'case_id':'user_case','query':'拆封能退吗？',
        'source':'user_created','relevant_document_ids':['opened']}])
    run=asyncio.run(env.rag.run(env.sid,ev.retrieval_eval_set_id))
    e=CareerService(env.exp).build('RETRIEVAL',run.run_id)
    assert e.project_identity['demo_dataset']
    assert any('Demo 模拟政策' in l for l in e.limitations)
    assert not any('平台预设题' in l for l in e.limitations)


def test_legacy_materials_remain_readable_when_new_evidence_facts_are_added(env):
    a,b,_,_=knowledge_pair(env)
    comparison=env.rag.compare(a.run_id,b.run_id)
    env.practice.conclude(comparison.comparison_id,'REVISE','补充独立测试后再判断。',True)
    career=CareerService(env.exp)
    e=career.build('RETRIEVAL',a.run_id,b.run_id,comparison.comparison_id,context=CONTEXT)
    from experiments.career_narrative import plan
    from experiments.career_renderers import generate
    legacy=normalize(e,'EVALUATION_WORKBENCH','AI_EVALUATION_PLATFORM_PM',schema_version='1')
    narrative=plan(legacy)
    old=generate(e,legacy,narrative,1)
    career.career.put('views',legacy);career.career.put('narratives',narrative);career.career.put('materials',old)
    old_bytes=career.career.path('materials',old.material_id).read_bytes()
    new=career.generate_v2(e.evidence_object_id)
    assert new.generator_version=='agenteval-evidence-renderer-v3'
    assert career.career.get('views',legacy.view_id).schema_version=='1'
    assert career.export(old.material_id)['label']==old.label
    assert career.career.path('materials',old.material_id).read_bytes()==old_bytes
