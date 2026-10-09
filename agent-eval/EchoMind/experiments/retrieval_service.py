"""Knowledge → real retrieval → one confirmed intervention → paired evidence."""
import asyncio
import time
from pathlib import Path
from evaluation.config import DEFAULT_CONFIG
from evaluation.metrics import dialog_metrics
from .canonical import digest, text_hash, evaluation_protocol
from .models import now, uid
from .providers import ProviderFailure
from .provider_transport import ObservedProvider
from .retrieval_models import (RetrievalCase, RetrievalEvalSet, RetrievalConfig, RetrievalRun,
                               RetrievalChange, RetrievalComparison, RetrievalReview)
from .retrieval_knowledge import FrozenKnowledge
from .retrieval_metrics import case_metrics, aggregate, transition, answer_transition
from .retrieval_runtime import pipeline_snapshot, rewrite, rerank, evaluate_answer, retrieve_context

CHANGE_FIELDS={'TOP_K_CHANGE':'top_k','QUERY_REWRITE_TOGGLE':'query_rewrite','RERANK_TOGGLE':'rerank'}

def config_diff(before,after):
    a=before.model_dump() if hasattr(before,'model_dump') else before
    b=after.model_dump() if hasattr(after,'model_dump') else after
    return [{'path':key,'before':a[key],'after':b[key]} for key in sorted(a) if a[key]!=b[key]]

def implementation_snapshot():
    files=['retrieval_knowledge.py','retrieval_embeddings.py','retrieval_lexical_v1.py','retrieval_runtime.py','retrieval_metrics.py','retrieval_service.py']
    return {name:text_hash((Path(__file__).parent/name).read_text()) for name in files}

def knowledge_control_reasons(before,after):
    allowed={'eval_set_hash','eval_set_snapshot','knowledge_snapshot','chunk_snapshot_hash','index_snapshot','embedding_snapshot'}
    reasons=[k.upper()+'_CHANGED' for k in set(before)|set(after) if k not in allowed and before.get(k)!=after.get(k)]
    a,b=before['eval_set_snapshot'],after['eval_set_snapshot']
    if a['cases']!=b['cases']: reasons.append('TEST_SEMANTICS_CHANGED')
    a,b=before['index_snapshot'],after['index_snapshot']
    if (a['knowledge_dataset_id']!=b['knowledge_dataset_id'] or b['knowledge_version']<=a['knowledge_version']
        or a['chunk_config']!=b['chunk_config']): reasons.append('KNOWLEDGE_UPDATE_SCOPE_CHANGED')
    a={k:v for k,v in before['embedding_snapshot'].items() if k!='index_generation'}
    b={k:v for k,v in after['embedding_snapshot'].items() if k!='index_generation'}
    if a!=b: reasons.append('EMBEDDING_CHANGED')
    return reasons

class RetrievalService:
    def __init__(self,experiments):
        self.experiments=experiments
        self.store=experiments.store
        self.providers=experiments.providers
        self.knowledge=FrozenKnowledge(self.store)
        with self.store.transaction():
            for run in self.store.list('retrieval_runs'):
                if run.status=='RUNNING':
                    try: lease=self.store.acquire_run_lease(run.run_id,'retrieval_runs')
                    except BlockingIOError: continue
                    try:
                        self.store.put('retrieval_runs',run.model_copy(update={'status':'FAILED','finished_at':now(),
                            'runtime_end_check':{'reliable_isolation':False,'reasons':['PROCESS_INTERRUPTED']},
                            'warnings':[ *run.warnings,'PROCESS_INTERRUPTED']}))
                    finally: lease.close()

    def create_evalset(self,index_id,name,cases,evalset_id=None,allow_missing_labels=False):
        index=self.store.get('knowledge_indices',index_id)
        self.knowledge.verify(index)
        cases=[RetrievalCase.model_validate(c) for c in cases]
        docs={c['document_id'] for c in index.chunks}; chunks={c['chunk_id'] for c in index.chunks}
        if any((set(c.relevant_document_ids)-docs or set(c.relevant_chunk_ids)-chunks)
               and not (c.allow_missing_knowledge or allow_missing_labels) for c in cases):
            raise ValueError('Relevant knowledge does not exist in selected frozen index')
        for case in cases:
            if case.source_chat_turn_id: self.store.get('chat_turns',case.source_chat_turn_id)
            if case.source=='ai_generated' or case.generation:
                draft=self.store.get('ai_drafts',case.generation.get('draft_id',''))
                original=next((c for c in draft.content.get('cases',[]) if c['case_id']==case.case_id),None)
                if (draft.kind!='TESTS' or (draft.sources.get('index_id')!=index_id and not allow_missing_labels)
                    or original is None or case.generation!=original['generation']):
                    raise ValueError('Generated case must retain its frozen source')
        with self.store.transaction():
            version=self.store.get('retrieval_evalsets',evalset_id).version+1 if evalset_id else 1
            identity={'index_id':index_id,'cases':[c.model_dump() for c in sorted(cases,key=lambda c:c.case_id)]}
            ev=RetrievalEvalSet(retrieval_eval_set_id=evalset_id or uid(),version=version,name=name,
                               index_id=index_id,cases=cases,eval_set_hash=digest(identity))
            return self.store.put('retrieval_evalsets',ev)

    def controls(self,ev,index,provider_config,verify_answers):
        return {'eval_set_hash':ev.eval_set_hash,'eval_set_snapshot':ev.model_dump(mode='json'),
                'knowledge_snapshot':self.store.get('knowledge_datasets',index.knowledge_dataset_id,index.knowledge_version).model_dump(mode='json'),
                'chunk_snapshot_hash':index.chunk_snapshot_hash,'index_snapshot':index.model_dump(mode='json'),
                'embedding_snapshot':index.embedding_snapshot,'distance_metric':'cosine',
                'retrieval_implementation':implementation_snapshot(),'pipeline':pipeline_snapshot(provider_config),
                'evaluation_config':DEFAULT_CONFIG.model_dump(), 'evaluation_protocol':evaluation_protocol(),
                'evaluation_protocol_hash':digest(evaluation_protocol()),'verify_answers':verify_answers,
                'execution_order':sorted(c.case_id for c in ev.cases),
                'rank_policy':'FIRST_RELEVANT_MRR_AT_FIXED_CANDIDATE_POOL_THEN_RECALL; DUPLICATE_DOCUMENT_CHUNKS_NO_EXTRA_CREDIT',
                'metric_protocol':{'fixed_pool_metrics':['hit_at_1','hit_at_3','mrr'],
                                   'returned_top_k_metrics':['recall_at_k','precision_at_k','ndcg_at_k'],
                                   'label_policy':'USER_BINARY_LABELS; ONE_GRANULARITY_PER_CASE; DOCUMENT_DUPLICATES_NO_EXTRA_CREDIT'},
                'cache':{'cache_enabled':False,'cache_namespace':None,'cache_policy':'DISABLED'}}

    def propose_change(self,baseline_run_id,change_type,after_config,reason,selected_case_ids,user_confirmed,target_index_id=None):
        before=self.store.get('retrieval_runs',baseline_run_id)
        if before.run_type!='BASELINE' or before.status not in {'COMPLETE','PARTIAL'}:
            raise ValueError('Change needs an acquired Baseline')
        if not user_confirmed or not reason.strip(): raise ValueError('Explicit confirmation and reason required')
        known={r['case_id'] for r in before.case_results}
        if not selected_case_ids or len(selected_case_ids)!=len(set(selected_case_ids)) or set(selected_case_ids)-known:
            raise ValueError('Select actual Baseline Cases')
        after=RetrievalConfig.model_validate(after_config)
        changes=config_diff(before.retrieval_config,after)
        target_eval_set_id=None
        if change_type=='KNOWLEDGE_UPDATE':
            old=self.store.get('knowledge_indices',before.controls['index_snapshot']['index_id'])
            target=self.store.get('knowledge_indices',target_index_id)
            self.knowledge.verify(target)
            if (changes or target.knowledge_dataset_id!=old.knowledge_dataset_id
                or target.knowledge_version<=old.knowledge_version or target.chunk_config!=old.chunk_config):
                raise ValueError('Knowledge update must preserve retrieval and chunk configuration')
            expected={k:v for k,v in old.embedding_snapshot.items() if k!='index_generation'}
            if expected!={k:v for k,v in target.embedding_snapshot.items() if k!='index_generation'}:
                raise ValueError('Embedding changed with knowledge')
            ev=before.controls['eval_set_snapshot']
            if any(c.get('relevant_chunk_ids') for c in ev['cases']):
                raise ValueError('Knowledge update comparison requires stable document-level labels')
            target_ev=self.create_evalset(target.index_id,ev['name'],ev['cases'],allow_missing_labels=True)
            target_eval_set_id=target_ev.retrieval_eval_set_id
            changes=[{'path':'knowledge_index','before':old.index_id,'after':target.index_id}]
        elif target_index_id or len(changes)!=1 or changes[0]['path']!=CHANGE_FIELDS.get(change_type):
            raise ValueError('Only one declared retrieval variable is permitted')
        change=RetrievalChange(baseline_run_id=baseline_run_id,change_type=change_type,reason=reason.strip(),
            target_index_id=target_index_id,target_eval_set_id=target_eval_set_id,
            selected_case_ids=selected_case_ids,user_confirmed=True,confirmed_at=now(),before_config=before.retrieval_config,
            after_config=after,declared_diff=changes)
        with self.store.transaction(): return self.store.put('retrieval_changes',change)

    def apply(self,change_id):
        with self.store.transaction():
            change=self.store.get('retrieval_changes',change_id)
            if change.implemented_status=='APPLIED': return change
            base=self.store.get('retrieval_runs',change.baseline_run_id)
            if base.retrieval_config!=change.before_config: raise ValueError('Baseline config drift')
            observed=config_diff(base.retrieval_config,RetrievalConfig.model_validate(change.after_config.model_dump()))
            if change.change_type=='KNOWLEDGE_UPDATE':
                target=self.store.get('knowledge_indices',change.target_index_id)
                self.knowledge.verify(target)
                observed=[{'path':'knowledge_index','before':base.controls['index_snapshot']['index_id'],'after':target.index_id}]
            if observed!=change.declared_diff: raise ValueError('Declared/observed diff mismatch')
            applied=change.model_copy(update={'implemented_status':'APPLIED','applied_at':now(),'observed_diff':observed,
                'application_evidence':{'scope':'FROZEN_RETEST_CONFIGURATION','before_hash':digest(change.before_config.model_dump()),
                                        'effective_after_snapshot':change.after_config.model_dump(),
                                        'after_hash':digest(change.after_config.model_dump())}})
            return self.store.put('retrieval_changes',applied)

    async def preview_rewrite(self,session_id,query):
        session=self.providers.get(session_id)
        if session.text_connection_status!='READY': raise ProviderFailure('CONNECTION_NOT_VERIFIED')
        provider=ObservedProvider(session.configuration,self.providers.credential(session_id),self.providers.judge_credential(session_id))
        try:
            return {'original_query':query,'rewritten_query':await rewrite(provider,query),
                    'configuration':pipeline_snapshot(session.configuration)['rewrite'],
                    'observations':provider.observations,'is_applied_change':False}
        finally: await provider.close()

    async def run(self,provider_session_id,retrieval_eval_set_id,version=None,run_type='BASELINE',
                  parent_run_id=None,change_id=None,retrieval_config=None,verify_answers=False):
        session=self.providers.get(provider_session_id)
        key=self.providers.credential(provider_session_id)
        judge_key=self.providers.judge_credential(provider_session_id)
        if session.text_connection_status!='READY': raise ProviderFailure('CONNECTION_NOT_VERIFIED')
        ev=self.store.get('retrieval_evalsets',retrieval_eval_set_id,version)
        index=self.store.get('knowledge_indices',ev.index_id)
        self.knowledge.verify(index)
        config=RetrievalConfig.model_validate(retrieval_config or {})
        controls=self.controls(ev,index,session.configuration,verify_answers)
        if run_type=='RETEST':
            base=self.store.get('retrieval_runs',parent_run_id)
            change=self.store.get('retrieval_changes',change_id)
            latest=self.store.get('knowledge_datasets',index.knowledge_dataset_id)
            if latest.version!=index.knowledge_version:
                raise ValueError('Knowledge version changed; create a new Baseline')
            knowledge_change=change.change_type=='KNOWLEDGE_UPDATE'
            matching_controls=(not knowledge_control_reasons(base.controls,controls)) if knowledge_change else controls==base.controls
            if knowledge_change and (index.index_id!=change.target_index_id or ev.retrieval_eval_set_id!=change.target_eval_set_id):
                raise ValueError('Retest knowledge not bound to confirmed change')
            if (base.run_type!='BASELINE' or base.status not in {'COMPLETE','PARTIAL'}
                or change.baseline_run_id!=parent_run_id or change.implemented_status!='APPLIED'
                or not matching_controls or session.configuration.model_dump()!=base.provider_configuration_snapshot
                or base.verify_answers!=verify_answers):
                raise ValueError('Retest must retain frozen Baseline controls and one applied Change')
            if retrieval_config is not None and config!=change.after_config: raise ValueError('Unrecorded retrieval config change')
            config=change.after_config
        elif parent_run_id or change_id:
            raise ValueError('Baseline cannot inherit a Change')
        run=RetrievalRun(run_type=run_type,parent_run_id=parent_run_id,change_id=change_id,
                         provider_session_id=provider_session_id,provider_configuration_snapshot=session.configuration.model_dump(),
                         provider_readiness_snapshot={'text_connection_status':session.text_connection_status,
                             'tool_call_capability':session.tool_call_capability},controls=controls,retrieval_config=config,
                         execution_order=controls['execution_order'],verify_answers=verify_answers,
                         warnings=['SINGLE_RUN_RANDOMNESS','MODEL_BACKEND_REVISION_UNKNOWN',
                                   'LOCAL_LEXICAL_EMBEDDING_NOT_NEURAL_SEMANTIC_MODEL','GROUNDED_ANSWER_NO_ROUTER_OR_MEMORY'])
        with self.store.transaction():
            lease=self.store.acquire_run_lease(run.run_id,'retrieval_runs')
            self.store.put('retrieval_runs',run)
        provider=ObservedProvider(session.configuration,key,judge_key)
        results=[];answers=[];boundary={'reliable_isolation':True,'frozen_index_verified':True,'cache_used':False,
                                       'shared_online_chroma_accessed':False,'reasons':[]}
        status='COMPLETE'
        try:
            for case in sorted(ev.cases,key=lambda c:c.case_id):
                row=await retrieve_context(self.knowledge,index,provider,case.query,config,controls['pipeline'],case.context)
                row.update(case_id=case.case_id,relevant_document_ids=case.relevant_document_ids,
                           relevant_chunk_ids=case.relevant_chunk_ids,partition=case.partition)
                row['metrics']=case_metrics(case,row['results'],config.top_k,row['post_rerank_results'])
                if row['status']!='SUCCESS':
                    row['metrics']={**row['metrics'],**{k:None for k in ('hit_at_1','hit_at_3','recall_at_k','precision_at_k','mrr','ndcg_at_k')},
                                    'relevant_rank':None,'unavailable_reason':'INVALID_RETRIEVAL'}
                rank=row['metrics']['relevant_rank']
                row['retrieval_status']=('INVALID' if row['status']!='SUCCESS' else 'UNLABELED' if row['metrics']['mrr'] is None
                    else 'TOP_1_HIT' if rank==1 else 'LOWER_RANK_HIT' if rank is not None else 'NOT_RETRIEVED')
                results.append(row)
                if verify_answers:
                    answers.append(await evaluate_answer(provider,case,row,controls['evaluation_config']))
            await asyncio.to_thread(self.knowledge.verify,index)
        except asyncio.CancelledError:
            status='PARTIAL';boundary['reasons'].append('ACQUISITION_INTERRUPTED')
            # Incompleteness is not itself an experiment-control drift. Preserve
            # finished pairs only when the frozen index still verifies.
            try: await asyncio.to_thread(self.knowledge.verify,index)
            except Exception: boundary.update(reliable_isolation=False,reasons=['FROZEN_INDEX_VERIFICATION_FAILED'])
        except Exception:
            status='FAILED';boundary.update(reliable_isolation=False,reasons=['FROZEN_INDEX_OR_RUNTIME_FAILURE'])
        finally:
            await provider.close()
            boundary['provider_errors']=provider.errors
            if implementation_snapshot()!=controls['retrieval_implementation'] or digest(evaluation_protocol())!=controls['evaluation_protocol_hash']:
                boundary.update(reliable_isolation=False,reasons=[*boundary['reasons'],'IMPLEMENTATION_OR_EVALUATION_PROTOCOL_DRIFT'])
                status='FAILED'
            if not boundary['reliable_isolation']:
                from evaluation.models import CaseResult
                for row in results:
                    row.update(status='INVALID',retrieval_status='INVALID',error='RUNTIME_ISOLATION_UNVERIFIED')
                    row['metrics']={**row['metrics'],**{k:None for k in ('hit_at_1','hit_at_3','recall_at_k','precision_at_k','mrr','ndcg_at_k')},
                                    'relevant_rank':None,'unavailable_reason':'RUNTIME_ISOLATION_UNVERIFIED'}
                answers=[CaseResult.model_validate({**a.model_dump(),'original_status':'INVALID',
                    'original_reason':'冻结索引或运行边界未能验证，不能形成有效质量结论。',
                    'judge_status':'NOT_RUN','scores':{},'evaluation_error':'RUNTIME_ISOLATION_UNVERIFIED'}) for a in answers]
            finished=run.model_copy(update={'status':status,'finished_at':now(),'case_results':results,'answer_results':answers,
                'metrics':aggregate(results,len(ev.cases)),'answer_metrics':dialog_metrics(answers) if verify_answers else {},
                'provider_observations':provider.observations,'provider_call_count':provider.call_count,'runtime_end_check':boundary})
            try:
                with self.store.transaction(): finished=self.store.put('retrieval_runs',finished)
            finally: lease.close()
        return finished

    def effective_answers(self,run):
        answers={r.case_id:r for r in run.answer_results}
        for review in sorted(self.store.list('retrieval_reviews'),key=lambda r:r.revision):
            if review.run_id==run.run_id: answers[review.case_id]=review.effective_result
        return list(answers.values())

    def review(self,run_id,case_id,status,reason):
        with self.store.transaction():
            run=self.store.get('retrieval_runs',run_id)
            if run.status not in {'COMPLETE','PARTIAL'}: raise ValueError('Review requires acquired Run')
            current=next((r for r in self.effective_answers(run) if r.case_id==case_id),None)
            if current is None: raise ValueError('Answer Case not found')
            effective=current.review(status,reason)
            revision=max([r.revision for r in self.store.list('retrieval_reviews') if r.run_id==run_id],default=0)+1
            return self.store.put('retrieval_reviews',RetrievalReview(run_id=run_id,case_id=case_id,revision=revision,effective_result=effective))

    def view(self,run_id):
        run=self.store.get('retrieval_runs',run_id)
        answers=self.effective_answers(run)
        return {'run':run.model_dump(mode='json'),'effective_answer_results':[r.to_dict() for r in answers],
                'answer_metrics':dialog_metrics(answers) if run.verify_answers else {}}

    def compare(self,baseline_run_id,retest_run_id):
        before=self.store.get('retrieval_runs',baseline_run_id);after=self.store.get('retrieval_runs',retest_run_id)
        reasons=[]; single=False
        if before.run_type!='BASELINE' or after.run_type!='RETEST' or after.parent_run_id!=before.run_id:
            reasons.append('RUN_RELATION_MISMATCH')
        if before.status not in {'COMPLETE','PARTIAL'} or after.status not in {'COMPLETE','PARTIAL'}:
            reasons.append('RUN_NOT_ACQUIRED')
        if before.provider_configuration_snapshot!=after.provider_configuration_snapshot: reasons.append('PROVIDER_CONFIG_CHANGED')
        if before.execution_order!=after.execution_order: reasons.append('EXECUTION_ORDER_CHANGED')
        change=self.store.get('retrieval_changes',after.change_id) if after.change_id else None
        knowledge_change=change and change.change_type=='KNOWLEDGE_UPDATE'
        if knowledge_change: reasons.extend(knowledge_control_reasons(before.controls,after.controls))
        else:
            for key in sorted(set(before.controls)|set(after.controls)):
                if before.controls.get(key)!=after.controls.get(key): reasons.append(key.upper()+'_CHANGED')
        if not all(r.runtime_end_check.get('reliable_isolation') for r in (before,after)):
            reasons.append('RUNTIME_ISOLATION_UNVERIFIED')
        if after.change_id:
            try:
                change=self.store.get('retrieval_changes',after.change_id)
                actual=config_diff(before.retrieval_config,after.retrieval_config)
                single=(change.implemented_status=='APPLIED' and change.baseline_run_id==before.run_id
                        and len(actual)==1 and actual==change.declared_diff==change.observed_diff
                        and actual[0]['path']==CHANGE_FIELDS.get(change.change_type)
                        and change.application_evidence.get('effective_after_snapshot')==after.retrieval_config.model_dump())
                if knowledge_change:
                    actual=[{'path':'knowledge_index','before':before.controls['index_snapshot']['index_id'],
                             'after':after.controls['index_snapshot']['index_id']}]
                    single=(change.implemented_status=='APPLIED' and change.baseline_run_id==before.run_id
                            and before.retrieval_config==after.retrieval_config and actual==change.declared_diff==change.observed_diff
                            and after.controls['index_snapshot']['index_id']==change.target_index_id
                            and after.controls['eval_set_snapshot']['retrieval_eval_set_id']==change.target_eval_set_id)
            except (FileNotFoundError,ValueError): pass
        if not single: reasons.append('UNRECORDED_OR_MULTI_COMPONENT_CHANGE')
        comparable=not reasons
        left={r['case_id']:r for r in before.case_results};right={r['case_id']:r for r in after.case_results}
        answers_a={r.case_id:r for r in self.effective_answers(before)};answers_b={r.case_id:r for r in self.effective_answers(after)}
        expected=sorted(set(before.execution_order)|set(after.execution_order));pairs=[]
        paired_a=[];paired_b=[]
        for case_id in expected:
            a=left.get(case_id);b=right.get(case_id)
            movement,reason=transition(a,b,'CONTROL_CONDITIONS_CHANGED' if reasons else None)
            if movement!='NOT_COMPARABLE': paired_a.append(a);paired_b.append(b)
            pairs.append({'case_id':case_id,'query':(a or b or {}).get('query'),
                          'transition':movement,'reason':reason,'baseline':a,'retest':b,
                          'partition':(a or b or {}).get('partition','DEBUG'),
                          'baseline_answer':answers_a[case_id].to_dict() if case_id in answers_a else None,
                          'retest_answer':answers_b[case_id].to_dict() if case_id in answers_b else None,
                          'answer_transition':answer_transition(answers_a.get(case_id),answers_b.get(case_id),
                              reason if reasons or a is None or b is None else None)})
        matched=len(set(left)&set(right)&set(expected))
        reviews=[r.model_dump() for r in self.store.list('retrieval_reviews') if r.run_id in {before.run_id,after.run_id}]
        comparison=RetrievalComparison(baseline_run_id=before.run_id,retest_run_id=after.run_id,comparable=comparable,
            comparability_reasons=reasons,comparison_completeness='FULL' if matched==len(expected) else 'PARTIAL',
            expected_case_count=len(expected),matched_case_count=matched,single_recorded_change=single,
            attribution_status='INSUFFICIENT_EVIDENCE' if comparable else 'CONTROL_CONDITIONS_CHANGED',
            warnings=['SINGLE_RUN_RANDOMNESS','MODEL_BACKEND_REVISION_UNKNOWN','RETRIEVAL_IMPROVEMENT_IS_NOT_ANSWER_IMPROVEMENT',
                      *(['PARTIAL_PAIRED_METRICS_ONLY_NO_WHOLE_EVALSET_CLAIM'] if matched<len(expected) else []),
                      'ANSWER_REVIEW_SNAPSHOT_'+digest(reviews)],
            case_pairs=pairs,metrics_before=aggregate(before.case_results,len(expected)),metrics_after=aggregate(after.case_results,len(expected)),
            paired_metrics={'baseline':aggregate(paired_a),'retest':aggregate(paired_b),'scope':'MATCHED_VALID_LABELED_CASE_PAIRS'},
            answer_review_snapshot={'records':reviews,'hash':digest(reviews)})
        with self.store.transaction(): return self.store.put('retrieval_comparisons',comparison)
