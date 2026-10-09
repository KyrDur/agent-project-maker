"""Deterministic factual / format gates; preparation hints are not success scores."""
import re
from .canonical import digest
from .career_evidence import resolve

DIMENSIONS=('completeness','evidence_integrity','ownership_clarity','metric_literacy','decision_depth','interview_clarity','followup_resilience')

def assess(e,v,p,bundle):
    issues=[]
    def issue(code,message): issues.append({'code':code,'message':message})
    if bundle.evidence_hash!=e.evidence_hash or bundle.view_hash!=digest(v.model_dump(mode='json')) or bundle.narrative_hash!=digest(p.model_dump(mode='json')):
        raise ValueError('Narrative binding mismatch')
    for key,f in v.facts.items():
        for pointer in f.evidence_paths:
            if pointer.startswith('view#/'):
                value=v.model_dump(mode='json')
                for part in pointer.split('#/',1)[1].split('/'): value=value[int(part)] if isinstance(value,list) else value[part]
            else: resolve(e,pointer)
    from .career_renderers import content
    expected_groups,expected_defense,_=content(e,v,p)
    for group,sections in bundle.sections.items():
        expected={s.section_id:s for s in expected_groups[group]}
        for section in sections:
            if section.source_type!='USER_UNVERIFIED_CLAIM' and (section.section_id not in expected or
                    section.text!=expected[section.section_id].text or section.citations!=expected[section.section_id].citations):
                issue('EVIDENCE_TEXT_MISMATCH','机器文案与当前绑定的事实规划不一致。')
    if bundle.defense!=expected_defense:
        # Artifact timestamps are incidental; compare the immutable propositions.
        def values(cards): return [{k:v for k,v in q.model_dump().items() if k!='created_at'} for q in cards]
        if values(bundle.defense)!=values(expected_defense): issue('DEFENSE_FACT_MISMATCH','追问回答与事实不一致。')
    text='\n'.join(s.text for ss in bundle.sections.values() for s in ss)+'\n'+'\n'.join(q.suggested_answer_outline for q in bundle.defense)
    for pattern,code in [(r'…|\.\.\.', 'INCOMPLETE_TEXT'),(r'我负责我|本人负责我|我提出我|[。！？][。，]', 'BROKEN_GRAMMAR'),
                         (r'claim_\d+', 'CLAIM_DUMP_IN_BODY'),(r'"(?:top_k|rerank|claim_id)"\s*:', 'RAW_JSON_IN_BODY'),
                         (r'证明(?:本次|修改|重排|Rerank).*?(?:导致|因果)|可比较就是可归因','UNSUPPORTED_CAUSALITY'),
                         (r'我(?:手写|独立实现|编写了)(?:全部|完整)(?:代码|系统)','PERSONAL_CONTRIBUTION_AMBIGUOUS')]:
        if re.search(pattern,text): issue(code,'内容需核实或重新组织表达。')
    if not e.answer_evidence.get('enabled') and re.search(r'(?:回答质量|业务效果)(?:已经|已|显著)?(?:提高了|提升了|改善了)',text):
        issue('UNSUPPORTED_ANSWER_GAIN','没有回答比较，不得宣称回答或业务收益。')
    for field in ('user_contribution','motivation','user_problem'):
        value=v.facts[field].value
        if re.search(r'(?:DAU|GMV|留存|收入|上线后|用户量).{0,20}\d|\d.{0,10}(?:用户|业绩)',value,re.I):
            issue('USER_UNVERIFIED_PERFORMANCE_NUMBER','用户背景中的业绩数字尚无系统证据。')
    for conflict in v.conflicts: issue('CONFIGURATION_CONFLICT',conflict)
    for group,sections in bundle.sections.items():
        for s in sections:
            if not s.text.strip(): issue('EMPTY_SECTION',group+'/'+s.section_id)
            if s.source_type!='USER_UNVERIFIED_CLAIM':
                for c in s.citations:
                    if c['text_span'] not in s.text or not c['fact_ids'] or any(k not in v.facts for k in c['fact_ids']):
                        issue('UNRESOLVED_CITATION',group+'/'+s.section_id)
                if not s.citations: issue('MISSING_CITATION',group+'/'+s.section_id)
    for q in bundle.defense:
        if not q.supporting_evidence and not q.missing_information: issue('DEFENSE_WITHOUT_EVIDENCE',q.question_id)
    if bundle.user_edits: issue('FREE_EDIT_UNVERIFIED','自由编辑不成为已验证的实验事实；需回到证据核验。')
    readiness={}
    for group in [*bundle.sections,'defense']:
        checks={d:{'status':'READY','reason':''} for d in DIMENSIONS}
        if not e.retest_run_id or not e.comparison or not e.comparison.get('comparable'):
            checks['completeness']={'status':'DRAFT','reason':'缺少可比较的复测结论'}
        if v.project_focus=='CUSTOMER_SERVICE_APP': checks['ownership_clarity']={'status':'NEEDS_INPUT','reason':'客服应用背景不能借用工作台背景'}
        if v.missing_questions:
            checks['decision_depth']={'status':'NEEDS_INPUT','reason':'；'.join(q['field'] for q in v.missing_questions)}
            checks['followup_resilience']={'status':'NEEDS_INPUT','reason':'根因与方案取舍需补充真实判断，不能虚构'}
        if v.facts['root_cause'].evidence_state=='INFERENCE':
            checks['decision_depth']={'status':'NEEDS_VERIFICATION','reason':'已补充根因假设，尚未经对照验证'}
        if issues:
            checks['evidence_integrity']={'status':'NEEDS_VERIFICATION','reason':'；'.join(i['code'] for i in issues)}
        if any(i['code'] in {'INCOMPLETE_TEXT','BROKEN_GRAMMAR','RAW_JSON_IN_BODY'} for i in issues):
            checks['interview_clarity']={'status':'DRAFT','reason':'表达质量检查未通过'}
        readiness[group]=checks
    return issues,readiness
