"""Phase 5 adversarial narrative contracts over actual sealed experiment artifacts."""
import asyncio,json,shutil
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from experiments.career_service import CareerService
from experiments.career_models import ProjectContext,CareerBundle
from experiments.career_render import lint_bundle,generate,markdown,numbers
from experiments.career_api import router
from experiments.api import configure,install_validation_handler
from experiments.store import JsonStore
from experiments.canonical import digest
from test_experiment_service import setup,baseline,applied

CONTEXT={'project_name':'电商客服评测实践','project_context':'PERSONAL_PROJECT','motivation':'客服回答缺少可复核依据',
 'target_users':'电商客服产品设计者','user_problem':'定位错误知识与回答边界','why_ai':'需要检索业务知识并处理自然语言问题',
 'user_roles':['产品设计','评测分析','AI Coding'],'user_contribution':'定义验收要求、检查失败案例并选择修改',
 'system_contribution':'Codex 编写工程代码，平台执行检索和统计，Judge 输出评分','existing_capabilities':'原仓库提供 Agent 和工具',
 'real_users':False,'deployed':False,'reflection':'扩大模糊问题覆盖并重复运行。','reflection_confirmed':True,'confirmed':True}

@pytest.fixture
def agent(tmp_path):
 s,ev,_=setup(tmp_path);a=baseline(s,ev);d,c=applied(s,a);s.runtime.score=.95
 b=asyncio.run(s.run(ev.eval_set_id,'RETEST',a.run_id,d.decision_id,[c.change_id]));comp=s.compare(a.run_id,b.run_id)
 return CareerService(s),a,b,comp

@pytest.fixture
def rag(tmp_path):
 import os
 source=Path(os.environ.get('AGENT_EVAL_GOLDEN_FIXTURES', str(Path(__file__).resolve().parents[3]/'phase4/rag/golden-path-b/sealed')))
 if not (source/'baseline.json').is_file():
  pytest.skip('Requires private historical fixtures: AGENT_EVAL_GOLDEN_FIXTURES')
 store=JsonStore(tmp_path/'store');objects={}
 mapping={'baseline':'retrieval_runs','retest':'retrieval_runs','comparison':'retrieval_comparisons','change':'retrieval_changes',
          'index':'knowledge_indices','knowledge':'knowledge_datasets','evalset':'retrieval_evalsets','provider-session':'provider_sessions'}
 for name,group in mapping.items():
  env=json.loads((source/(name+'.json')).read_text());obj=env['artifact'];objects[name]=obj
  keys={'baseline':'run_id','retest':'run_id','comparison':'comparison_id','change':'change_id','index':'index_id','knowledge':'knowledge_dataset_id','evalset':'retrieval_eval_set_id','provider-session':'provider_session_id'}
  version=obj.get('version') if group in {'knowledge_datasets','retrieval_evalsets'} else None
  target=store.path(group,obj[keys[name]],version);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/(name+'.json'),target)
 return CareerService(SimpleNamespace(store=store)),objects

def build_agent(agent,context=CONTEXT):
 c,a,b,comp=agent
 return c.build('AGENT_BEHAVIOR',a.run_id,b.run_id,comp.comparison_id,context)

def build_rag(rag,context=CONTEXT):
 c,d=rag
 return c.build('RETRIEVAL',d['baseline']['run_id'],d['retest']['run_id'],d['comparison']['comparison_id'],context)

def test_agent_actual_run_and_contribution_boundaries(agent):
 c,a,b,comp=agent;before={p:p.read_bytes() for p in c.store.root.rglob('*.json')}
 e=build_agent(agent);m=c.generate(e.evidence_object_id)
 assert e.baseline['dialog_case_count']==2 and e.baseline['answer_metrics']['valid']==2
 assert e.comparison['attributable'] is False and e.comparison['comparable']
 assert e.diagnosis['ai_suggestions']['root_cause']=='AI hypothesis'
 assert any(cl.source_type=='AI_SUGGESTION' and not cl.allowed_for_resume for cl in e.claims)
 assert any(cl.source_type=='USER_CONFIRMED_DECISION' for cl in e.claims)
 assert [x['owner'] for x in m.contribution_summary]==['USER_CONFIRMED','AI_CODING_PLATFORM','EXISTING_CAPABILITY']
 assert all(p.read_bytes()==raw for p,raw in before.items())
 assert 'RAG 与 Memory 关闭' in markdown(m)

def test_rag_actual_metrics_sources_and_rank_movements(rag):
 c,d=rag;e=build_rag(rag);m=c.generate(e.evidence_object_id)
 assert e.retrieval_evidence['document_count']==8 and e.retrieval_evidence['chunk_count']==8
 assert e.retrieval_evidence['baseline_metrics']==d['baseline']['metrics']
 assert len(e.retrieval_evidence['rank_movements'])==8
 assert len(m.defense)==15 and sum(q.pressure for q in m.defense)>=5
 text=markdown(m)
 for required in ['Chunk','Embedding','Top K','MRR','NDCG','Recall@K','Precision@K','Query Rewrite','Rerank','Ground Truth']:
  assert required in text
 assert e.project_identity['demo_dataset'] and e.project_identity['provider_classification']=='LOCAL_OR_UNVERIFIED'
 assert '商业模型验证' in text
 assert m.label=='Evidence-backed',m.lint
 metric=next(cl for cl in e.claims if cl.claim_type=='PAIRED_MRR')
 assert metric.value_before==d['comparison']['paired_metrics']['baseline']['mrr']
 assert metric.source_ids==['retrieval_runs:'+d['baseline']['run_id'],'retrieval_runs:'+d['retest']['run_id'],'retrieval_comparisons:'+d['comparison']['comparison_id']]
 for claim in e.claims:
  for pointer in claim.evidence_path:
   key,path=pointer.split('#/',1);value=e.source_map[key]['snapshot']
   for segment in path.split('/'): value=value[int(segment)] if isinstance(value,list) else value[segment]
 assert e.historical_context['status']=='NOT_USED_AS_CURRENT'

def test_fact_lock_all_materials_and_explicit_regeneration(rag):
 c,_=rag;e=build_rag(rag);m=c.generate(e.evidence_object_id)
 for group in ['case_study','resume_ai','resume_general','interview']:
  assert m.sections[group]
 assert m.evidence_version==e.evidence_version and m.evidence_hash==e.evidence_hash
 original=c.career.path('materials',m.material_id).read_bytes();fact=c.career.path('evidence',e.evidence_object_id).read_bytes()
 new_ctx={**CONTEXT,'motivation':'新的用户确认动机'}
 e2=build_rag(rag,new_ctx);assert e2.evidence_version==2
 assert c.career.path('materials',m.material_id).read_bytes()==original
 edited=c.edit(m.material_id,'resume_ai','ai_eval',m.sections['resume_ai'][1].text+' 保留逐题记录。')
 assert edited.parent_material_id==m.material_id and edited.label=='Mixed'
 assert c.career.path('evidence',e.evidence_object_id).read_bytes()==fact
 assert c.career.path('materials',m.material_id).read_bytes()==original
 restored=c.regenerate_section(edited.material_id,'resume_ai','ai_eval')
 assert restored.label=='Evidence-backed',restored.lint
 new=c.generate(e2.evidence_object_id);assert new.evidence_version==2 and new.evidence_hash==e2.evidence_hash
 with pytest.raises(ValueError): c.career.put('materials',m)

@pytest.mark.parametrize('kind',['case_study','resume_ai','resume_general','interview'])
def test_unsupported_numbers_and_causality(rag,kind):
 c,_=rag;e=build_rag(rag);m=c.generate(e.evidence_object_id);s=m.sections[kind][0]
 edit=c.edit(m.material_id,kind,s.section_id,'本人手写全部系统，建立80道题，证明修改导致 MRR 提升，上线后 DAU 达到99999。')
 codes={x['code'] for x in edit.lint}
 assert {'UNSUPPORTED_NUMBER','UNSUPPORTED_CAUSALITY','DEMO_PRESENTED_AS_PRODUCTION','PERSONAL_CONTRIBUTION_AMBIGUOUS'}<=codes
 assert edit.label!='Evidence-backed'

@pytest.mark.parametrize('text,code',[
 ('可比较就是可归因。','COMPARABLE_ATTRIBUTABLE_CONFUSED'),
 ('INVALID 算作通过。','INVALID_INCLUDED_IN_SUCCESS_RATE'),
 ('商业模型效果提升已验证。','SCRIPTED_PROVIDER_PRESENTED_AS_COMMERCIAL'),
 ('历史指标作为本次指标提升。','HISTORICAL_METRIC_PRESENTED_AS_CURRENT'),
 ('原仓库已有工具由我手写。','EXISTING_CAPABILITY_CLAIMED_AS_USER_WORK'),
 ('全面提升，没有任何退化。','UNSUPPORTED_CAUSALITY'),
 ('使用八十道测试题。','UNSUPPORTED_NUMBER'),
])
def test_narrative_lint_risks(rag,text,code):
 c,_=rag;e=build_rag(rag);m=c.generate(e.evidence_object_id)
 edited=c.edit(m.material_id,'resume_ai','ai_problem',text)
 assert code in {i['code'] for i in edited.lint}

@pytest.mark.parametrize('field',['confirmed','motivation','user_contribution','system_contribution','existing_capabilities','real_users','deployed'])
def test_context_required_confirmed_explicit(agent,field):
 c,a,b,comp=agent;ctx=deepcopy(CONTEXT)
 if field in {'real_users','deployed'}:ctx.pop(field)
 else:ctx[field]=False if field=='confirmed' else ' '
 with pytest.raises(ValueError): build_agent(agent,ctx)


def test_missing_context_and_missing_retest_are_draft(agent):
 c,a,_,_=agent;e=c.build('AGENT_BEHAVIOR',a.run_id)
 with pytest.raises(ValueError): c.generate(e.evidence_object_id)
 e2=c.build('AGENT_BEHAVIOR',a.run_id,context=CONTEXT);m=c.generate(e2.evidence_object_id)
 assert m.label=='Draft' and e2.missing_evidence
 assert '待补充' in markdown(m)
 assert all(c.claim_type not in {'PAIRED_MRR'} for c in e2.claims)


def test_regression_invalid_limitations_not_hidden(agent):
 c,a,b,comp=agent
 # Existing immutable comparison is kept; a separately sealed comparison fixture
 # supplies adversarial evidence to Phase 5 (not a UI production mutation).
 from experiments.models import Comparison,uid
 pairs=deepcopy(comp.case_comparisons);pairs[0]['effective_transition']='REGRESSED'
 fixture=Comparison.model_validate({**comp.model_dump(),'comparison_id':uid(),'case_comparisons':pairs})
 c.store.put('comparisons',fixture)
 e=c.build('AGENT_BEHAVIOR',a.run_id,b.run_id,fixture.comparison_id,CONTEXT)
 assert len(e.regressions)==1
 m=c.generate(e.evidence_object_id);edited=c.edit(m.material_id,'case_study','regression','没有问题。')
 assert 'HIDDEN_REGRESSION' in {i['code'] for i in edited.lint}
 edited=c.edit(m.material_id,'case_study','limits','没有限制。')
 assert 'MISSING_LIMITATION' in {i['code'] for i in edited.lint}


def test_judge_invalid_and_pending_category_not_success(tmp_path):
 from test_experiment_evidence import ErrorRuntime
 for kind in ['judge','agent']:
  root=tmp_path/kind;root.mkdir();s,ev,_=setup(root,runtime=ErrorRuntime(kind));a=baseline(s,ev);c=CareerService(s)
  e=c.build('AGENT_BEHAVIOR',a.run_id,context=CONTEXT)
  assert e.invalid_cases and e.baseline['answer_metrics']['valid']==0
  m=c.generate(e.evidence_object_id);edit=c.edit(m.material_id,'case_study','invalid','全部通过。')
  assert 'HIDDEN_INVALID' in {i['code'] for i in edit.lint}


def test_speech_lengths_and_reflection_confirmation(rag):
 c,_=rag;ctx={**CONTEXT,'reflection_confirmed':False,'reflection':'我提出的未确认内容'}
 e=build_rag(rag,ctx);m=c.generate(e.evidence_object_id)
 texts={s.section_id:s.text for s in m.sections['interview']}
 assert 160<=len(texts['story60'])<=400,len(texts['story60'])
 assert 240<=len(texts['story90'])<=550,len(texts['story90'])
 assert '我提出的未确认内容' not in texts['story60']+texts['story90']
 assert '待补充' in texts['story60']
 assert m.sections['resume_ai'] and m.sections['resume_general']
 assert all(s.claim_ids for s in m.sections['resume_ai']+m.sections['resume_general'])


def test_review_revision_frozen_to_comparison(agent):
 c,a,b,comp=agent;e=build_agent(agent);before=c.career.path('evidence',e.evidence_object_id).read_bytes()
 c.experiments.review(a.run_id,'a','PASS','外部证据已复核','user')
 e2=build_agent(agent)
 assert e2.answer_evidence==e.answer_evidence and e2.human_reviews==e.human_reviews
 newcomp=c.experiments.compare(a.run_id,b.run_id)
 e3=c.build('AGENT_BEHAVIOR',a.run_id,b.run_id,newcomp.comparison_id,CONTEXT)
 assert e3.human_reviews and e3.baseline['answer_metrics']['passed']==1
 assert c.career.path('evidence',e.evidence_object_id).read_bytes()==before


def test_api_endpoints_and_mismatched_ids(agent):
 c,a,b,comp=agent;configure(lambda:c.experiments)
 app=FastAPI();app.include_router(router);install_validation_handler(app);client=TestClient(app)
 body={'experiment_type':'AGENT_BEHAVIOR','baseline_run_id':a.run_id,'retest_run_id':b.run_id,'comparison_id':comp.comparison_id,'context':CONTEXT}
 res=client.post('/experiments/career/evidence',json=body);assert res.status_code==200,res.text
 e=res.json();m=client.post('/experiments/career/materials',json={'evidence_object_id':e['evidence_object_id']}).json()
 assert client.get('/experiments/career/materials/'+m['material_id']+'/export').json()['markdown']
 assert client.get('/experiments/career/evidence').json()
 assert client.get('/experiments/career/materials').json()
 assert client.get('/experiments/career/evidence/bad..id').status_code==409
 assert client.post('/experiments/career/evidence',json={**body,'retest_run_id':a.run_id}).status_code==409
 assert client.post('/experiments/career/materials/'+m['material_id']+'/edit',json={'group':'resume_ai','section_id':'ai_eval','text':'80道题'}).json()['label']=='Mixed'


def test_secret_values_and_tampered_fact_lock_rejected(agent):
 c,a,b,comp=agent;c.store.forbidden_values=('actual-private-key',)
 with pytest.raises(ValueError): build_agent(agent,{**CONTEXT,'motivation':'actual-private-key'})
 e=build_agent(agent);p=c.career.path('evidence',e.evidence_object_id)
 d=json.loads(p.read_text());d['artifact']['baseline']['dialog_case_count']=80;d['sha256']=digest(d['artifact']);p.write_text(json.dumps(d))
 with pytest.raises(ValueError):c.career.get('evidence',e.evidence_object_id)


def test_unverified_user_performance_numbers_are_not_resume_facts(rag):
 c,_=rag;e=build_rag(rag,{**CONTEXT,'user_contribution':'上线后 GMV 提升99%，达到10000用户。'})
 claim=next(x for x in e.claims if x.claim_type=='CONTEXT_USER_CONTRIBUTION')
 assert not claim.allowed_for_resume
 m=c.generate(e.evidence_object_id)
 assert m.label!='Evidence-backed'
 assert 'USER_UNVERIFIED_PERFORMANCE_NUMBER' in {x['code'] for x in m.lint}


def test_partial_scope_not_whole_set_improvement(rag):
 from experiments.retrieval_models import RetrievalComparison
 from experiments.models import uid
 c,d=rag;comp=c.store.get('retrieval_comparisons',d['comparison']['comparison_id'])
 p=RetrievalComparison.model_validate({**comp.model_dump(),'comparison_id':uid(),'comparison_completeness':'PARTIAL','matched_case_count':7})
 c.store.put('retrieval_comparisons',p)
 e=c.build('RETRIEVAL',d['baseline']['run_id'],d['retest']['run_id'],p.comparison_id,CONTEXT)
 assert any('匹配有效子集' in x for x in e.limitations)
 assert all('匹配有效' in x.claim_text for x in e.claims if x.claim_type.startswith('PAIRED_'))


def test_noncomparable_has_no_allowed_metric_change_claim(rag):
 from experiments.retrieval_models import RetrievalComparison
 from experiments.models import uid
 c,d=rag;comp=c.store.get('retrieval_comparisons',d['comparison']['comparison_id'])
 p=RetrievalComparison.model_validate({**comp.model_dump(),'comparison_id':uid(),'comparable':False,'comparability_reasons':['TEST_CONFIG_DRIFT']})
 c.store.put('retrieval_comparisons',p)
 e=c.build('RETRIEVAL',d['baseline']['run_id'],d['retest']['run_id'],p.comparison_id,CONTEXT)
 assert not any(x.allowed_for_resume for x in e.claims if x.claim_type.startswith('PAIRED_'))
 assert c.generate(e.evidence_object_id).label=='Draft'


def test_pending_is_pending_review_not_judge_or_execution_error(tmp_path):
 s,_,_=setup(tmp_path)
 ev=s.create_eval_set([{'case_id':'pending','input':'退款','judge_method':'human review'}])
 a=baseline(s,ev);e=CareerService(s).build('AGENT_BEHAVIOR',a.run_id,context=CONTEXT)
 assert e.invalid_cases[0]['category']=='pending human review'
 metrics=e.baseline['answer_metrics']
 assert metrics['pending_human_reviews']==1 and metrics['agent_errors']==metrics['judge_errors']==0


def test_hard_rule_original_and_override_permanently_visible(tmp_path):
 s,_,_=setup(tmp_path)
 ev=s.create_eval_set([{'case_id':'a','input':'退款','executable_rules':[{'type':'required_tool','tool':'missing_tool'}]}])
 a=baseline(s,ev);d,ch=applied(s,a)
 b=asyncio.run(s.run(ev.eval_set_id,'RETEST',a.run_id,d.decision_id,[ch.change_id]))
 review=s.review(a.run_id,'a','PASS','人工外部证据核验，保留机器违规事实','user');comp=s.compare(a.run_id,b.run_id)
 c=CareerService(s);e=c.build('AGENT_BEHAVIOR',a.run_id,b.run_id,comp.comparison_id,CONTEXT)
 row=e.answer_evidence['results'][a.run_id][0]
 assert row['original_status']=='FAIL' and row['final_status']=='PASS' and row['hard_rule_violations'] and row['hard_rule_override']
 assert e.human_reviews[0]['original_status']=='FAIL'
 assert 'hard_rule_override' in markdown(c.generate(e.evidence_object_id))


def test_all_invalid_pairs_are_draft_and_exclude_quality(tmp_path):
 from test_experiment_evidence import ErrorRuntime
 s,ev,_=setup(tmp_path,runtime=ErrorRuntime('judge'));a=baseline(s,ev)
 d,ch=applied(s,a);b=asyncio.run(s.run(ev.eval_set_id,'RETEST',a.run_id,d.decision_id,[ch.change_id]));comp=s.compare(a.run_id,b.run_id)
 c=CareerService(s);e=c.build('AGENT_BEHAVIOR',a.run_id,b.run_id,comp.comparison_id,CONTEXT)
 assert e.baseline['answer_metrics']['valid']==e.retest['answer_metrics']['valid']==0
 assert c.generate(e.evidence_object_id).label=='Draft'
