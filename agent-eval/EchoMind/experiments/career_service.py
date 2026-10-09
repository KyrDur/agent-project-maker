"""Read-only evidence aggregation. Rendering never writes experiment conclusions."""
from collections import Counter
from copy import deepcopy
import json,re
from urllib.parse import urlparse
from evaluation.metrics import dialog_metrics
from .models import now
from .canonical import digest
from .store import TERMINAL
from .career_models import EvidenceObject, EvidenceClaim, ProjectContext
from .career_store import CareerStore

METRICS=('hit_at_1','hit_at_3','recall_at_k','precision_at_k','mrr','ndcg_at_k')

class CareerService:
    def __init__(self, experiments):
        self.experiments=experiments
        self.store=experiments.store
        self.career=CareerStore(self.store)

    def build(self, experiment_type, baseline_run_id, retest_run_id=None, comparison_id=None, context=None, parent_evidence_id=None):
        # A single store transaction gives a consistent snapshot of mutable Change/
        # review allocation. Acquisition/sealed records keep their existing semantics.
        with self.store.transaction():
            return self._build(experiment_type,baseline_run_id,retest_run_id,comparison_id,context,parent_evidence_id)

    def _build(self,kind,base_id,retest_id,comp_id,context,parent_id):
        if kind not in {'AGENT_BEHAVIOR','RETRIEVAL'}: raise ValueError('Unknown experiment type')
        ctx=ProjectContext.model_validate(context) if context is not None else None
        sources={};claims=[];missing=[]
        def read(group,identifier):
            obj=self.store.get(group,identifier)
            env=json.loads(self.store.path(group,identifier).read_text())
            key=group+':'+identifier
            sources[key]={'group':group,'id':identifier,'sha256':env['sha256'],'snapshot':env['artifact']}
            return obj,key
        def derived(name,value,parents):
            key='derived:'+name
            sources[key]={'group':'SYSTEM_DERIVED','id':name,'sha256':digest(value),'snapshot':value,'parents':parents}
            return key
        def claim(ctype,text,before=None,after=None,source_type='RUN_EVIDENCE',keys=(),paths=(),resume=False,unit=''):
            identity='claim_'+str(len(claims)+1)
            item=EvidenceClaim(claim_id=identity,claim_type=ctype,claim_text=text,value_before=before,value_after=after,
                unit=unit,source_type=source_type,source_ids=list(keys),evidence_path=list(paths),
                confidence='MISSING' if source_type=='MISSING' else 'USER_CONFIRMED' if source_type in {'USER_ENTERED_CONTEXT','USER_CONFIRMED_DECISION'}
                else 'UNVERIFIED' if source_type in {'HISTORICAL_CONTEXT','AI_SUGGESTION'} else 'DERIVED' if source_type=='SYSTEM_DERIVED' else 'RECORDED',
                allowed_for_resume=resume and source_type not in {'MISSING','AI_SUGGESTION','HISTORICAL_CONTEXT'} and not (source_type=='USER_ENTERED_CONTEXT' and re.search(r'(?:\d|[十百千万]).{0,12}(?:用户|提升|准确率|MRR|GMV|留存|DAU)|(?:用户量|提升|准确率|MRR|GMV|留存|DAU).{0,12}\d',text,re.I)),
                limitations=['观察结果不等于因果证明'] if source_type=='COMPARISON_EVIDENCE' else [])
            claims.append(item);return identity
        group='retrieval_runs' if kind=='RETRIEVAL' else 'runs'
        base,bkey=read(group,base_id)
        if base.run_type!='BASELINE' or base.status not in TERMINAL: raise ValueError('Need sealed baseline')
        after=akey=None
        if retest_id:
            after,akey=read(group,retest_id)
            if after.run_type!='RETEST' or after.parent_run_id!=base_id or after.status not in TERMINAL:
                raise ValueError('Retest does not belong to baseline or is not sealed')
        comp=ckey=None
        if comp_id:
            comp,ckey=read('retrieval_comparisons' if kind=='RETRIEVAL' else 'comparisons',comp_id)
            if not after or (comp.baseline_run_id,comp.retest_run_id)!=(base_id,retest_id): raise ValueError('Comparison identity mismatch')
        parent=None
        if parent_id:
            parent=self.career.get('evidence',parent_id)
            if (parent.experiment_type,parent.baseline_run_id)!=(kind,base_id): raise ValueError('Evidence lineage mismatch')
        prior=[e.evidence_version for e in self.career.list('evidence') if e.experiment_type==kind and e.baseline_run_id==base_id]
        version=max(prior,default=0)+1
        limitations=['当前为有限次数离线运行，模型随机性可能影响结果。',
                     '模型服务内部版本未经验证；可比较不等于可归因，不能证明修改导致效果变化。']
        if not ctx: missing.append('项目背景与贡献边界尚未由用户填写并确认')
        else:
            context_key=derived('user_context',ctx.model_dump(mode='json'),[])
            for field in ['project_name','project_context','motivation','target_users','user_problem','why_ai',
                          'user_roles','user_contribution','system_contribution','existing_capabilities','real_users','deployed']:
                claim('CONTEXT_'+field.upper(),str(getattr(ctx,field)),after=getattr(ctx,field),source_type='USER_ENTERED_CONTEXT',
                      keys=[context_key],paths=[context_key+'#/'+field],resume=field in {'user_contribution','motivation','user_problem','target_users'})
            if not ctx.real_users: limitations.append('用户确认当前没有真实用户，不能声明 DAU、留存或业务提升。')
            else: limitations.append('真实用户为用户自述，当前无独立用户量或业务结果证据。')
            if not ctx.deployed: limitations.append('用户确认当前没有真实上线，不能声明上线后效果。')
            else: limitations.append('部署为用户自述，当前无生产部署和线上效果验证证据。')
            if not ctx.reflection_confirmed: missing.append('反思尚待用户确认')
        provider=base.provider_configuration_snapshot
        host=urlparse(provider.get('base_url','')).hostname
        local=host in {'localhost','127.0.0.1','::1'}
        limitations.append('本次 Provider 是本地端点，模型响应可能来自脚本；不能作为商业模型验证。' if local
                           else '远程 Provider 的真实后端版本与商业模型身份尚未独立验证。')
        pkey=derived('provider_identity',{'configuration':provider,'observations':base.provider_observations,
                      'classification':'LOCAL_OR_UNVERIFIED' if local else 'REMOTE_UNVERIFIED'},[bkey])
        claim('BASE_MODEL','请求模型及各角色配置已记录；响应标识不证明真实后端身份。',after=provider,
              source_type='SYSTEM_DERIVED',keys=[pkey,bkey],paths=[pkey+'#/configuration'],resume=True)
        if not after: missing.append('没有 Retest，不能生成提升或改善结论')
        if not comp: missing.append('没有已保存 Comparison，不能生成前后改善结论')
        elif not comp.comparable: limitations.append('控制条件不可比较，不能将前后指标差异表达为优化效果。')
        elif comp.comparison_completeness=='PARTIAL': limitations.append('结果仅覆盖匹配有效子集，不能声称整套 EvalSet 改善。')
        if comp:
            claim('COMPARABILITY','可比较与可归因是独立事实。',before=comp.comparable,after=comp.attributable,
                  source_type='COMPARISON_EVIDENCE',keys=[ckey],paths=[ckey+'#/comparable',ckey+'#/attributable'])
            raw_warnings=comp.warnings if kind=='RETRIEVAL' else comp.attribution_warnings
            for warning in raw_warnings:
                if warning.startswith('ANSWER_REVIEW_SNAPSHOT_'): continue
                description=WARNING_TEXT.get(warning,'比较记录包含额外告警，需展开证据源核验。')
                limitations.append(description)
        reviews=[];review_keys=[]
        if kind=='RETRIEVAL':
            if comp:
                conclusions=sorted((c for c in self.store.list('experiment_conclusions') if c.comparison_id==comp.comparison_id),key=lambda c:c.created_at)
                if conclusions:
                    conclusion,key=read('experiment_conclusions',conclusions[-1].conclusion_id)
                    claim('USER_EXPERIMENT_CONCLUSION',f'用户决定 {conclusion.decision}：{conclusion.reason}',
                        after=conclusion.model_dump(),source_type='USER_CONFIRMED_DECISION',keys=[key,ckey],paths=[key+'#/reason'],resume=True)
            expected=base.controls['eval_set_snapshot']['cases']
            for case in expected:
                if case.get('source_chat_turn_id'):
                    turn,turnkey=read('chat_turns',case['source_chat_turn_id'])
                    claim('CHAT_TEST_SOURCE',f'测试 {case["case_id"]} 来自真实保存的对话，预期行为由用户确认。',after=turn.turn_id,
                        keys=[turnkey,bkey],paths=[turnkey+'#/message',bkey+'#/controls/eval_set_snapshot/cases'])
            pairs=comp.case_pairs if comp else []
            if comp:
                reviews=comp.answer_review_snapshot.get('records',[])
                for r in reviews:
                    # Snapshot is owned by Comparison; do not upgrade to later reviews.
                    review_keys.append(ckey+'#/answer_review_snapshot/records')
            else:
                for record in self.store.list('retrieval_reviews'):
                    if record.run_id in {base_id,retest_id}:
                        _,key=read('retrieval_reviews',record.review_id);reviews.append(record.model_dump(mode='json'));review_keys.append(key)
            index_id=base.controls.get('index_id') or base.controls['eval_set_snapshot']['index_id']
            index,ikey=read('knowledge_indices',index_id)
            knowledge,kkey=read('knowledge_datasets',index.knowledge_dataset_id+'--v'+str(index.knowledge_version))
            retrieval={'knowledge_dataset_id':knowledge.knowledge_dataset_id,'knowledge_version':knowledge.version,
                'knowledge_source':knowledge.metadata or {'document_metadata':[d.get('metadata',{}) for d in knowledge.documents]},
                'document_count':len(knowledge.documents),'chunk_count':len(index.chunks),'chunk_strategy':index.chunk_config.model_dump(),
                'embedding_config':index.embedding_snapshot,'vector_store':'Chroma PersistentClient / isolated local collection',
                'index_configuration':index.index_configuration,'retrieval_strategy':'local cosine candidate pool, optional query rewrite / LLM rerank',
                'config_before':base.retrieval_config.model_dump(),'config_after':after.retrieval_config.model_dump() if after else None,
                'ground_truth_source':[{'case_id':c['case_id'],'source':c.get('source'),'relevant_document_ids':c.get('relevant_document_ids',[]),
                                       'relevant_chunk_ids':c.get('relevant_chunk_ids',[]),**({'generation':c['generation']} if c.get('generation') else {})} for c in expected],
                'rank_movements':[{ 'case_id':p['case_id'],'query':p['query'],'before':(p['baseline'] or {}).get('metrics',{}).get('relevant_rank'),
                    'after':(p['retest'] or {}).get('metrics',{}).get('relevant_rank'),'transition':p['transition'],'answer_transition':p['answer_transition']} for p in pairs],
                'baseline_metrics':base.metrics,'retest_metrics':after.metrics if after else {},
                'paired_metrics':comp.paired_metrics if comp else {}}
            knowledge_change=self.store.get('retrieval_changes',after.change_id) if after and after.change_id else None
            if knowledge_change and knowledge_change.change_type=='KNOWLEDGE_UPDATE':
                target,tk=read('knowledge_indices',after.controls['index_snapshot']['index_id'])
                updated,uk=read('knowledge_datasets',target.knowledge_dataset_id+'--v'+str(target.knowledge_version))
                before_docs={d['document_id']:d for d in knowledge.documents}
                after_docs={d['document_id']:d for d in updated.documents}
                update={'before_version':knowledge.version,'after_version':updated.version,
                    'added_ids':sorted(set(after_docs)-set(before_docs)),
                    'removed_ids':sorted(set(before_docs)-set(after_docs)),
                    'before_document_count':len(knowledge.documents),'after_document_count':len(updated.documents),
                    'before_chunk_count':len(index.chunks),'after_chunk_count':len(target.chunks),
                    'edited_ids':sorted(k for k in before_docs.keys()&after_docs.keys() if before_docs[k]['content_hash']!=after_docs[k]['content_hash'])}
                retrieval['knowledge_update']=update
                claim('KNOWLEDGE_UPDATE',f'知识版本 {knowledge.version} → {updated.version}；新增 {len(update["added_ids"])}、修订 {len(update["edited_ids"])}、移除 {len(update["removed_ids"])} 份文档。',
                    before=knowledge.version,after=updated.version,source_type='SYSTEM_DERIVED',
                    keys=[kkey,uk,ikey,tk],paths=[kkey+'#/documents',uk+'#/documents'],resume=True)
            rdkey=derived('retrieval_details',retrieval,[bkey,ikey,kkey,*([akey] if akey else []),*([ckey] if ckey else [])])
            for field in ['document_count','chunk_count','chunk_strategy','embedding_config','vector_store','retrieval_strategy','ground_truth_source']:
                claim('RAG_'+field.upper(),f'{field}：{retrieval[field]}',after=retrieval[field],source_type='SYSTEM_DERIVED',keys=[rdkey,ikey,kkey,bkey],
                      paths=[rdkey+'#/'+field],resume=field in {'document_count','chunk_count'})
            for metric in METRICS:
                av=base.metrics.get(metric);bv=after.metrics.get(metric) if after else None
                claim('BASELINE_'+metric.upper(),f'Baseline {metric}：{av if av is not None else "待补充"}',after=av,keys=[bkey],paths=[bkey+'#/metrics/'+metric],unit='ratio')
                if after: claim('RETEST_'+metric.upper(),f'Retest {metric}：{bv if bv is not None else "待补充"}',after=bv,keys=[akey],paths=[akey+'#/metrics/'+metric],unit='ratio')
                if comp:
                    pa=comp.paired_metrics['baseline'].get(metric);pb=comp.paired_metrics['retest'].get(metric)
                    count=comp.paired_metrics['baseline'].get('denominators',{}).get(metric,0)
                    safe=comp.comparable and count>0 and pa is not None and pb is not None
                    claim('PAIRED_'+metric.upper(),f'匹配有效标注子集观察到 {metric} 从 {pa} 到 {pb}；分母 {count}。',pa,pb,
                        'COMPARISON_EVIDENCE',[bkey,akey,ckey],[ckey+'#/paired_metrics/baseline/'+metric,ckey+'#/paired_metrics/retest/'+metric,
                         ckey+'#/paired_metrics/baseline/denominators/'+metric],resume=safe,unit='ratio')
            demo=any(c.get('source')=='demo' for c in expected) or any(d.get('metadata',{}).get('purpose')=='DEMO_POLICY_NOT_BUSINESS_COMMITMENT' for d in knowledge.documents)
            if any(c.get('source')=='ai_generated' for c in expected) or any(d.get('metadata',{}).get('source')=='AI_GENERATED_SIMULATION' for d in knowledge.documents):
                limitations.append('知识或测试由 AI 生成并经用户确认，用于模拟实践，不代表真实商家业务验证。')
            answer_sets={}
            for run,key in [(base,bkey),*([(after,akey)] if after else [])]:
                answers={r.case_id:r.to_dict() for r in run.answer_results}
                if comp:
                    side='baseline_answer' if run.run_id==base_id else 'retest_answer'
                    answers={p['case_id']:p[side] for p in pairs if p.get(side)}
                else:
                    for r in sorted(reviews,key=lambda r:r['revision']):
                        if r['run_id']==run.run_id: answers[r['case_id']]=r['effective_result']
                answer_sets[run.run_id]=list(answers.values())
            from evaluation.models import CaseResult
            metrics={rid:dialog_metrics([CaseResult.model_validate(r) for r in rs]) for rid,rs in answer_sets.items()}
            answers={'enabled':base.verify_answers,'results':answer_sets,'metrics':metrics,
                     'evaluation_config':base.controls.get('evaluation_config',{}),'evaluation_protocol':base.controls.get('evaluation_protocol',{}),
                     'workflow':'Query → optional Rewrite → frozen Retrieval → optional Rerank → Context → single knowledge Agent → Answer → Phase 2 Evaluation',
                     'limitations':['当前 Retrieval Answer 路径没有 Intent Router、原多 Agent 编排或 Memory。']}
            limitations.extend(answers['limitations'])
            regressions=[p for p in pairs if p['transition']=='RETRIEVAL_REGRESSED' or p['answer_transition']=='PASS→FAIL']
            invalid=[]
            for run in [base,*([after] if after else [])]:
                acquired={r['case_id']:r for r in run.case_results}
                for cid in run.execution_order:
                    r=acquired.get(cid)
                    if r is None or r['status']!='SUCCESS': invalid.append({'run_id':run.run_id,'case_id':cid,'category':'missing result' if r is None else 'retrieval/provider error','detail':r})
                for r in answer_sets[run.run_id]:
                    if r.get('final_status',r['original_status'])=='INVALID': invalid.append({'run_id':run.run_id,'case_id':r['case_id'],'category':invalid_category(r),'detail':r})
            change={}
            if after and after.change_id:
                ch,chkey=read('retrieval_changes',after.change_id);change=ch.model_dump(mode='json')
                decision={'reason':ch.reason,'selected_case_ids':ch.selected_case_ids,'confirmed_at':ch.confirmed_at,'source_type':'USER_CONFIRMED_DECISION'}
                claim('USER_DECISION',ch.reason,after=decision,source_type='USER_CONFIRMED_DECISION',keys=[chkey],paths=[chkey+'#/reason'],resume=True)
            else: decision={};missing.append('没有用户确认的检索修改记录')
            diagnosis={'selected_case_ids':decision.get('selected_case_ids',[]),'root_cause':'待补充：检索 Change reason 不等于已确认根因',
                       'ai_suggestions':[],'alternatives':'待补充'}
            missing.extend(['知识来源背景需用户补充','标签构建过程需用户补充','根因与备选方案需用户补充'])
        else:
            expected=base.eval_set_snapshot['case_snapshot'];demo=any(c.get('source')=='platform_preset' for c in expected)
            pairs=comp.case_comparisons if comp else [];retrieval={}
            for r in self.store.list('reviews'):
                cap=comp.review_revision_a if comp and r.run_id==base_id else comp.review_revision_b if comp else None
                if r.run_id in {base_id,retest_id} and (cap is None or r.revision<=cap):
                    _,key=read('reviews',r.review_id);reviews.append(r.model_dump(mode='json'));review_keys.append(key)
            effective={run.run_id:[r.to_dict() for r in self.experiments.effective_results(run,
                       comp.review_revision_a if comp and run.run_id==base_id else comp.review_revision_b if comp else None)]
                       for run in [base,*([after] if after else [])]}
            metrics={run.run_id:dialog_metrics(self.experiments.effective_results(run,
                       comp.review_revision_a if comp and run.run_id==base_id else comp.review_revision_b if comp else None))
                       for run in [base,*([after] if after else [])]}
            answers={'enabled':True,'results':effective,'metrics':metrics,'intent_metrics':{'baseline':base.intent_metrics,'retest':after.intent_metrics if after else {}},
                     'evaluation_config':base.evaluation_config_snapshot,'evaluation_protocol':base.evaluation_protocol_snapshot,
                     'workflow':'Query → Intent → Routing → Agent / tools → Answer → execution validity / Hard Rule / four quality thresholds / Human Review'}
            limitations.append('本 Agent/Skill 实验关闭 RAG、Query Rewrite、Rerank 和 Memory，不能代表完整在线客服。')
            regressions=[p for p in pairs if p['effective_transition']=='REGRESSED']
            invalid=[]
            for run in [base,*([after] if after else [])]:
                rows={r['case_id']:r for r in effective[run.run_id]}
                for c in run.eval_set_snapshot['case_snapshot']:
                    r=rows.get(c['case_id'])
                    if r is None or r['final_status']=='INVALID': invalid.append({'run_id':run.run_id,'case_id':c['case_id'],'category':'missing result' if r is None else invalid_category(r),'detail':r})
            decision={};diagnosis={};change={}
            did=after.decision_id if after else None
            if not did:
                ds=[d for d in self.store.list('decisions') if d.related_run_id==base_id and d.status=='CONFIRMED']
                if ds: did=sorted(ds,key=lambda d:d.created_at)[-1].decision_id
            if did:
                d,dkey=read('decisions',did)
                if d.related_run_id!=base_id: raise ValueError('Decision not related to baseline')
                diagnosis={'user_confirmed_root_cause':d.user_confirmed_root_cause,'reason':d.root_cause_reason,
                    'ai_suggestions':{'root_cause':d.root_cause_suggestion,'strategy':d.strategy_suggestion},'alternatives':d.alternatives,
                    'selected_case_ids':d.selected_case_ids}
                if d.status=='CONFIRMED':
                    decision=d.model_dump(mode='json')
                    claim('USER_DECISION',d.selection_reason,after={'strategy':d.selected_strategy,'reason':d.selection_reason},source_type='USER_CONFIRMED_DECISION',keys=[dkey],paths=[dkey+'#/selection_reason'],resume=True)
                    claim('USER_ROOT_CAUSE',d.user_confirmed_root_cause,after=d.user_confirmed_root_cause,source_type='USER_CONFIRMED_DECISION',keys=[dkey],paths=[dkey+'#/user_confirmed_root_cause'])
                for field in ['root_cause_suggestion','strategy_suggestion']:
                    if getattr(d,field): claim('AI_SUGGESTION',getattr(d,field),after=getattr(d,field),source_type='AI_SUGGESTION',keys=[dkey],paths=[dkey+'#/'+field])
            if not decision: missing.append('没有用户确认 Decision，不能把 AI 建议写成用户判断')
            if after:
                entries=[]
                for cid in after.applied_change_ids:
                    ch,chkey=read('changes',cid);entries.append(ch.model_dump(mode='json'))
                change={'entries':entries}
        if demo:
            if kind=='RETRIEVAL' and not any(c.get('source')=='demo' for c in expected):
                limitations.append('知识库包含 Demo 模拟政策，不代表真实商家承诺；测试题来源以各题记录为准。')
            else:
                limitations.append('EvalSet 包含 Demo / 平台预设题，不能写成真实用户反馈或全部由用户原创。')
        if not ctx or not ctx.reflection_confirmed: reflection='待补充：用户确认后的反思'
        else:
            reflection=ctx.reflection
            claim('USER_REFLECTION',reflection,after=reflection,source_type='USER_ENTERED_CONTEXT',keys=[context_key],paths=[context_key+'#/reflection'])
        detail={'baseline':{'run_id':base_id,'status':base.status,'dialog_case_count':len(expected),'intent_sample_count':len(base.eval_set_snapshot.get('intent_case_snapshot',[])) if kind=='AGENT_BEHAVIOR' else 0,
                    'case_sources':[{'case_id':c['case_id'],'source':c.get('source')} for c in expected],
                    'selected_case_evidence':[r for r in (base.case_results if kind=='RETRIEVAL' else [r.to_dict() for r in base.case_results]) if (r.get('case_id') if isinstance(r,dict) else r.case_id) in diagnosis.get('selected_case_ids',[])],
                    'answer_metrics':metrics.get(base_id,{}),'retrieval_metrics':base.metrics if kind=='RETRIEVAL' else {},'provider_configuration':provider},
                'retest':{'run_id':retest_id,'status':after.status,'answer_metrics':metrics.get(retest_id,{}),'retrieval_metrics':after.metrics if kind=='RETRIEVAL' else {}} if after else {},
                'comparison':comp.model_dump(mode='json') if comp else {},'answer_evidence':answers,
                'regressions':regressions,'invalid_cases':invalid,'human_reviews':reviews,'change':change,'diagnosis':diagnosis}
        detail_key=derived('experiment_summary',detail,[bkey,*([akey] if akey else []),*([ckey] if ckey else []),*review_keys])
        claim('CASE_COUNT',f'本次使用 {len(expected)} 道任务级测试题。',after=len(expected),source_type='SYSTEM_DERIVED',keys=[detail_key,bkey],paths=[detail_key+'#/baseline/dialog_case_count'],resume=True,unit='cases')
        for side in ['baseline','retest']:
            if detail[side]:
                for field,value in detail[side]['answer_metrics'].items():
                    if isinstance(value,(int,float)) or value is None:
                        claim(side.upper()+'_ANSWER_'+field.upper(),f'{side} 回答 {field}：{value if value is not None else "待补充"}',after=value,
                              source_type='SYSTEM_DERIVED',keys=[detail_key],paths=[detail_key+'#/'+side+'/answer_metrics/'+field])
        for name,value in [('regressions',regressions),('invalid_cases',invalid),('human_reviews',reviews),('change',change),('diagnosis',diagnosis)]:
            claim(name.upper(),f'{name}：'+(str(len(value)) if isinstance(value,list) else '见来源记录'),after=value,
                  source_type='HUMAN_REVIEW' if name=='human_reviews' else 'SYSTEM_DERIVED',keys=[detail_key],paths=[detail_key+'#/'+name])
        for i,p in enumerate(retrieval.get('rank_movements',[])):
            claim('CASE_RANK_MOVEMENT',f"{p['case_id']} 正确知识 Rank：{p['before']} → {p['after']}；{p['transition']}，回答 {p['answer_transition']}。",
                  p['before'],p['after'],'COMPARISON_EVIDENCE',[ckey,rdkey],[rdkey+f'#/rank_movements/{i}'])
        claim('HISTORICAL_CONTEXT','未将历史电商 Agent 指标作为当前实验结果。',source_type='HISTORICAL_CONTEXT')
        for field in missing: claim('MISSING',field,source_type='MISSING')
        result=dict(evidence_version=version,evidence_hash='',parent_evidence_id=parent_id,experiment_type=kind,
            baseline_run_id=base_id,retest_run_id=retest_id,comparison_id=comp_id,
            project_identity={'name':ctx.project_name if ctx else '待补充','project_context':ctx.project_context if ctx else '待补充','provider_classification':'LOCAL_OR_UNVERIFIED' if local else 'REMOTE_UNVERIFIED','demo_dataset':demo},
            problem_definition={'motivation':ctx.motivation if ctx else '待补充','target_users':ctx.target_users if ctx else '待补充','user_problem':ctx.user_problem if ctx else '待补充','why_ai':ctx.why_ai if ctx else '待补充'},
            baseline=detail['baseline'],diagnosis=diagnosis,user_decision=decision,change=change,retest=detail['retest'],comparison=detail['comparison'],
            retrieval_evidence=retrieval,answer_evidence=answers,regressions=regressions,invalid_cases=invalid,human_reviews=reviews,
            limitations=list(dict.fromkeys(limitations)),user_contribution={'description':ctx.user_contribution if ctx else '待补充','roles':ctx.user_roles if ctx else []},
            system_contribution={'description':ctx.system_contribution if ctx else '待补充','existing_capabilities':ctx.existing_capabilities if ctx else '待补充'},
            historical_context={'status':'NOT_USED_AS_CURRENT','claims':[]},missing_evidence=missing,source_map=sources,claims=claims,context=ctx,
            reflection_candidates=['扩大测试覆盖并重复运行，验证观察是否稳定。',
                *(['针对已出现的退化 Case 分析取舍，不把改善当作无损提升。'] if regressions else []),
                *(['区分采集失败和质量失败，先补齐无效或缺失结果。'] if invalid else []),
                *(['在独立中文测试上比较当前检索模型与其他方案，验证效果和局限。'] if kind=='RETRIEVAL' else [])],generated_at=now())
        evidence=EvidenceObject(**result)
        data=evidence.model_dump(mode='json');data['evidence_hash']=digest({k:v for k,v in data.items() if k!='evidence_hash'})
        return self.career.put('evidence',EvidenceObject.model_validate(data))

    def generate(self, identifier):
        from .career_render import generate
        with self.store.transaction():
            evidence=self.career.get('evidence',identifier)
            if evidence.context is None: raise ValueError('User context confirmation required')
            versions=[m.material_version for m in self.career.list('materials') if m.evidence_object_id==identifier]
            bundle=generate(evidence,max(versions,default=0)+1)
            return self.career.put('materials',bundle)

    def generate_v2(self, identifier, project_focus='EVALUATION_WORKBENCH', career_target='AI_EVALUATION_PLATFORM_PM', completions=(), speech_rate=240):
        from .career_evidence import normalize
        from .career_narrative import plan
        from .career_renderers import generate
        with self.store.transaction():
            evidence=self.career.get('evidence',identifier)
            view=normalize(evidence,project_focus,career_target,completions)
            narrative=plan(view,speech_rate)
            version=max([m.material_version for m in self.career.list('materials') if m.evidence_object_id==identifier],default=0)+1
            bundle=generate(evidence,view,narrative,version)
            # Failed format / factual checks never masquerade as a formal material.
            if bundle.lint: raise ValueError('Generation quality check failed: '+', '.join(i['code'] for i in bundle.lint))
            self.career.put('views',view)
            self.career.put('narratives',narrative)
            return self.career.put('materials',bundle)

    def preview_v2(self, identifier, project_focus='EVALUATION_WORKBENCH', career_target='AI_EVALUATION_PLATFORM_PM', completions=()):
        from .career_evidence import normalize
        return normalize(self.career.get('evidence',identifier),project_focus,career_target,completions)

    def export(self, identifier, group=None):
        from .career_render import markdown
        from .career_renderers import markdown_v2
        with self.store.transaction():
            bundle=self.career.get('materials',identifier)
            if bundle.view_id:
                from .career_readiness import assess
                ev=self.career.get('evidence',bundle.evidence_object_id)
                view=self.career.get('views',bundle.view_id);plan=self.career.get('narratives',bundle.narrative_id)
                issues,readiness=assess(ev,view,plan,bundle)
                bundle=bundle.model_copy(update={'lint':issues,'readiness':readiness,'label':'Mixed' if issues else bundle.label})
                text=markdown_v2(bundle,group)
            else:
                if group: raise ValueError('Independent exports require v2 generation')
                text=markdown(bundle)
            return {'filename':'career-'+bundle.material_id+('-'+group if group else '')+'.md','markdown':text,'label':bundle.label,
                    'evidence_object_id':bundle.evidence_object_id,'evidence_version':bundle.evidence_version,'readiness':bundle.readiness}

    def edit(self, identifier, group, section_id, text, edit_type='WORDING'):
        from .career_render import lint_bundle, label_for
        from .career_models import CareerBundle
        from .models import uid
        if edit_type not in {'WORDING','USER_UNVERIFIED_CLAIM'} or not text.strip() or len(text)>10000: raise ValueError('Invalid wording edit')
        with self.store.transaction():
            original=self.career.get('materials',identifier);evidence=self.career.get('evidence',original.evidence_object_id)
            data=original.model_dump(mode='json')
            if group not in data['sections']: raise ValueError('Unknown section')
            section=next((s for s in data['sections'][group] if s['section_id']==section_id),None)
            if section is None: raise ValueError('Unknown section')
            old=section['text'];section['text']=text;section['source_type']='USER_UNVERIFIED_CLAIM'
            if original.view_id: section['citations']=[]
            data.update(material_id=uid(),created_at=now(),parent_material_id=identifier,
                material_version=max([m.material_version for m in self.career.list('materials') if m.evidence_object_id==original.evidence_object_id],default=0)+1)
            data['user_edits'].append({'group':group,'section_id':section_id,'before':old,'after':text,'edit_type':edit_type,'fact_lock_unchanged':True})
            bundle=CareerBundle.model_validate(data)
            if bundle.view_id:
                from .career_readiness import assess
                issues,readiness=assess(evidence,self.career.get('views',bundle.view_id),self.career.get('narratives',bundle.narrative_id),bundle)
                bundle=bundle.model_copy(update={'readiness':readiness})
            else: issues=lint_bundle(evidence,bundle)
            return self.career.put('materials',CareerBundle.model_validate({**bundle.model_dump(),'lint':issues,'label':label_for(evidence,issues,True)}))

    def regenerate_section(self,identifier,group,section_id):
        from .career_render import generate, lint_bundle, label_for
        from .career_models import CareerBundle
        from .models import uid
        with self.store.transaction():
            old=self.career.get('materials',identifier);ev=self.career.get('evidence',old.evidence_object_id)
            if old.view_id:
                from .career_renderers import generate as generate_new
                fresh=generate_new(ev,self.career.get('views',old.view_id),self.career.get('narratives',old.narrative_id),old.material_version+1)
            else: fresh=generate(ev,old.material_version+1)
            section=next((s for s in fresh.sections.get(group,[]) if s.section_id==section_id),None)
            if section is None: raise ValueError('Unknown section')
            data=old.model_dump(mode='json');data['sections'][group]=[section.model_dump() if s['section_id']==section_id else s for s in data['sections'][group]]
            data['user_edits']=[e for e in data['user_edits'] if not(e['group']==group and e['section_id']==section_id)]
            data.update(material_id=uid(),parent_material_id=identifier,created_at=now(),material_version=max([m.material_version for m in self.career.list('materials') if m.evidence_object_id==ev.evidence_object_id],default=0)+1)
            candidate=CareerBundle.model_validate(data)
            if old.view_id:
                from .career_readiness import assess
                issues,readiness=assess(ev,self.career.get('views',old.view_id),self.career.get('narratives',old.narrative_id),candidate)
                data.update(readiness=readiness,lint=issues,label='Mixed' if issues else fresh.label)
            else:
                issues=lint_bundle(ev,candidate)
                data.update(lint=issues,label=label_for(ev,issues,bool(data['user_edits'])))
            return self.career.put('materials',CareerBundle.model_validate(data))


def invalid_category(row):
    if row.get('review_status')=='PENDING': return 'pending human review'
    if row.get('execution_status')!='SUCCESS': return 'execution/provider failure'
    if row.get('judge_status')=='FAILED': return 'judge failure'
    return 'evaluation failure'


WARNING_TEXT={
 'SINGLE_RUN_RANDOMNESS':'当前为有限次数离线运行，模型随机性可能影响结果。',
 'SINGLE_RUN_RANDOMNESS_NOT_CAUSAL_PROOF':'当前为有限次数离线运行，模型随机性可能影响结果。',
 'MODEL_BACKEND_REVISION_UNKNOWN':'模型服务内部版本未经验证；可比较不等于可归因，不能证明修改导致效果变化。',
 'MODEL_BACKEND_REVISION_UNVERIFIED':'模型服务内部版本未经验证；可比较不等于可归因，不能证明修改导致效果变化。',
 'RETRIEVAL_IMPROVEMENT_IS_NOT_ANSWER_IMPROVEMENT':'知识排名改善不等于回答质量改善，更不等于线上业务效果改善。',
 'PARTIAL_PAIRED_METRICS_ONLY_NO_WHOLE_EVALSET_CLAIM':'结果仅覆盖匹配有效子集，不能声称整套 EvalSet 改善。',
 'PARTIAL_MATCHED_VALID_CASES_ONLY':'结果仅覆盖匹配有效子集，不能声称整套 EvalSet 改善。',
 'REDUCED_RUNTIME_KNOWLEDGE_DISABLED':'本 Agent/Skill 实验关闭 RAG、Query Rewrite、Rerank 和 Memory，不能代表完整在线客服。',
 'RESPONSE_MODEL_IDENTIFIER_CHANGED':'前后返回模型标识发生变化；实际服务版本无法核验。',
 'RESPONSE_MODEL_IDENTIFIER_DIFFERS_FROM_REQUEST':'返回模型标识与请求不同，不能假定真实后端身份。',
 'TOOL_CALL_CAPABILITY_UNKNOWN':'工具能力尚未验证，本次工具链可能失败。',
 'TOOL_CALL_CAPABILITY_FAILED':'工具探针失败，本次工具链仍存在不确定性。',
 'UNEXPLAINED_APPLY_OR_ROLLBACK':'两次运行间存在未纳入本次实验的修改或恢复操作。',
}
