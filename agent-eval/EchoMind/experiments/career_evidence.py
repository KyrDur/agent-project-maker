"""Normalize only frozen records. Never re-evaluate or write experiments."""
from collections import Counter
from .career_models import CareerEvidenceView,NarrativeFact
from .career_decision import judgments
from .canonical import digest

def resolve(e,pointer):
    key,path=pointer.split('#/',1)
    value=e.model_dump(mode='json') if key=='evidence' else e.source_map[key]['snapshot']
    for part in path.split('/'):
        part=part.replace('~1','/').replace('~0','~')
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value

def normalize(e,focus,target,completions=(),schema_version='2'):
    if schema_version not in {'1','2'}: raise ValueError('Unsupported narrative schema')
    facts={};conflicts=[]
    for source in e.source_map.values():
        if digest(source['snapshot'])!=source['sha256']: raise ValueError('Frozen source hash mismatch')
    def fact(key,value,paths,state='VERIFIED_RECORD',owner='RECORD',scope='SHARED',types=()):
        for p in paths: resolve(e,p)
        ids=[c.claim_id for c in e.claims if c.claim_type in types]
        facts[key]=NarrativeFact(fact_id=key,value=value,evidence_state=state,owner=owner,subject_scope=scope,
                                claim_ids=ids,evidence_paths=paths)
    ctx=e.context
    if ctx is None: raise ValueError('Confirmed project context required')
    for k in ['project_name','user_roles','motivation','target_users','user_problem','why_ai','user_contribution','system_contribution','existing_capabilities','real_users','deployed','reflection']:
        owner='AI_CODING_PLATFORM' if k=='system_contribution' else 'EXISTING_CAPABILITY' if k=='existing_capabilities' else 'USER'
        fact(k,getattr(ctx,k),['evidence#/context/'+k],'USER_CONFIRMED',owner,'WORKBENCH',('CONTEXT_'+k.upper(),))
    fact('count',e.baseline['dialog_case_count'],['evidence#/baseline/dialog_case_count'],types=('CASE_COUNT',))
    fact('decision',e.user_decision.get('reason') or e.user_decision.get('selection_reason') or '',['evidence#/user_decision'],'USER_CONFIRMED' if e.user_decision else 'MISSING','USER',types=('USER_DECISION',))
    fact('change',e.change,['evidence#/change'],types=('CHANGE',))
    for i,c in enumerate(e.claims):
        if schema_version=='2' and c.claim_type=='USER_EXPERIMENT_CONCLUSION':
            fact('experiment_conclusion',c.value_after,[f'evidence#/claims/{i}/value_after'],'USER_CONFIRMED','USER',types=('USER_EXPERIMENT_CONCLUSION',))
    fact('comparison',e.comparison,['evidence#/comparison'],state='VERIFIED_RECORD' if e.comparison else 'MISSING',types=('COMPARABILITY',))
    for k in ['regressions','invalid_cases','human_reviews','limitations']:
        fact(k,getattr(e,k),['evidence#/'+k],types=(k.upper(),))
    selected=e.user_decision.get('selected_case_ids',[]) or e.diagnosis.get('selected_case_ids',[])
    fact('selected',selected,['evidence#/user_decision','evidence#/diagnosis'])
    fact('answers',{'enabled':e.answer_evidence.get('enabled'), 'results':e.answer_evidence.get('results',{}),
                    'metrics':e.answer_evidence.get('metrics',{})},['evidence#/answer_evidence'])
    if e.experiment_type=='RETRIEVAL':
        r=e.retrieval_evidence
        if schema_version=='2' and r.get('knowledge_update'):
            fact('knowledge_update',r['knowledge_update'],['evidence#/retrieval_evidence/knowledge_update'],types=('KNOWLEDGE_UPDATE',))
        for k in ['document_count','chunk_count','chunk_strategy','embedding_config','ground_truth_source','config_before','config_after','rank_movements','paired_metrics']:
            fact(k,r.get(k),['evidence#/retrieval_evidence/'+k],types=('RAG_'+k.upper(),))
        runs=[(key,s['snapshot']) for key,s in e.source_map.items() if s['group']=='retrieval_runs' and s['snapshot']['run_id'] in {e.baseline_run_id,e.retest_run_id}]
        acquisition={}
        for key,run in runs:
            rows=run['case_results'];side=run['run_type'].lower()
            acquisition[side]=[{'case_id':row['case_id'],'initial_candidates':len(row['pre_rerank_results']),
                  'rerank_input':len(row['pre_rerank_results']) if run['retrieval_config']['rerank'] else 0,
                  'post_candidates':len(row['post_rerank_results']),'final_returned':len(row['results']),
                  'rank_scope':row['metrics'].get('rank_scope'),'rank_cutoff':row['metrics'].get('rank_cutoff'),
                  'quality_cutoff':row['metrics'].get('quality_cutoff')} for row in rows]
            for row in rows:
                if row['metrics'].get('rank_cutoff')!=len(row['post_rerank_results']): conflicts.append('排名截点与实际候选池不一致')
                if len(row['results'])>run['retrieval_config']['top_k']: conflicts.append('最终返回结果超出 Top K')
                if row['metrics'].get('quality_cutoff')!=run['retrieval_config']['top_k']: conflicts.append('质量指标截点与 Top K 不一致')
            expected=r.get('config_before') if side=='baseline' else r.get('config_after')
            if expected!=run['retrieval_config']: conflicts.append('归一化配置与原始 Run 冲突')
        change=e.change
        if change and r.get('config_after'):
            observed=[{'path':k,'before':r['config_before'][k],'after':r['config_after'].get(k)}
                      for k in r['config_before'] if r['config_before'][k]!=r['config_after'].get(k)]
            if change.get('before_config')!=r['config_before'] or change.get('after_config')!=r['config_after']:
                conflicts.append('Change 声明配置与真实 Run 配置冲突')
            if change.get('change_type')=='KNOWLEDGE_UPDATE':
                indexed={run['run_type']:run['controls']['index_snapshot']['index_id'] for _,run in runs}
                observed=[{'path':'knowledge_index','before':indexed.get('BASELINE'),'after':indexed.get('RETEST')}]
            if sorted(observed,key=lambda x:x['path'])!=sorted(change.get('observed_diff',[]),key=lambda x:x['path']):
                conflicts.append('Change 实际差异与 Run 冲突')
        fact('acquisition',acquisition,[key+'#/case_results' for key,_ in runs])
        counts=dict(Counter(p['transition'] for p in r['rank_movements']))
        fact('transitions',counts,['evidence#/retrieval_evidence/rank_movements'])
        metrics=r.get('paired_metrics',{})
        for metric in ['hit_at_1','hit_at_3','mrr','recall_at_k','precision_at_k','ndcg_at_k']:
            paths=[c.evidence_path for c in e.claims if c.claim_type=='PAIRED_'+metric.upper()]
            flat=[p for ps in paths for p in ps]
            fact('metric_'+metric,{'before':metrics.get('baseline',{}).get(metric),'after':metrics.get('retest',{}).get(metric),
                 'denominator':metrics.get('baseline',{}).get('denominators',{}).get(metric,0)},flat or ['evidence#/retrieval_evidence/paired_metrics'],
                 types=('PAIRED_'+metric.upper(),))
    else:
        fact('answer_before',e.baseline.get('answer_metrics',{}),['evidence#/baseline/answer_metrics'])
        fact('answer_after',e.retest.get('answer_metrics',{}),['evidence#/retest'])
    existing,items,missing=judgments(e,completions,schema_version)
    for field in ['root_cause','alternatives','interpretation']:
        value,state=existing.get(field,('尚缺少可验证的回答依据','MISSING'))
        match=next((i for i,c in enumerate(items) if c.field==field),None)
        # Completion claims are stored in this immutable view, rather than mutating Evidence.
        if match is None:
            paths=['evidence#/context/reflection'] if field=='interpretation' else ['evidence#/diagnosis']
        else: paths=[f'view#/completions/{match}/text']
        facts[field]=NarrativeFact(fact_id=field,value=value,evidence_state=state,owner='USER',subject_scope='SHARED',evidence_paths=paths)
    if focus=='CUSTOMER_SERVICE_APP':
        missing.append({'field':'app_context','question':'当前确认背景属于评测工作台；客服应用的目标用户、实际使用场景和需求证据尚缺少单独确认。','state':'MISSING'})
    return CareerEvidenceView(schema_version=schema_version,evidence_object_id=e.evidence_object_id,evidence_version=e.evidence_version,evidence_hash=e.evidence_hash,
             project_focus=focus,career_target=target,facts=facts,completions=items,missing_questions=missing,conflicts=list(dict.fromkeys(conflicts)))
