"""Reuse recorded decisions; ask only for three genuinely missing judgments."""
from .career_models import DecisionCompletion

QUESTIONS={
 'root_cause':'你认为检索或回答问题的可能原因是什么？依据是什么？没有对照验证时会保留为待验证假设。',
 'alternatives':'你是否考虑过 Query Rewrite、调整 Embedding 或其他方案？为什么本轮没有选它们？没有考虑过也可以如实说明。',
 'interpretation':'复测后，你怎样理解结果？哪些结论还需要进一步验证？',
}

def judgments(e, completions, schema_version='2'):
    items=[DecisionCompletion.model_validate(c) for c in completions]
    if len({c.field for c in items})!=len(items): raise ValueError('Duplicate judgment field')
    # Do not overwrite the judgment already frozen in Decision / user context.
    existing={}
    root=e.diagnosis.get('user_confirmed_root_cause')
    if root and not str(root).startswith('待补充'): existing['root_cause']=(root,'INFERENCE')
    alt=e.diagnosis.get('alternatives')
    if alt and alt!='待补充': existing['alternatives']=(alt,'USER_CONFIRMED')
    if e.context and e.context.reflection_confirmed: existing['interpretation']=(e.context.reflection,'USER_CONFIRMED')
    for c in items:
        if c.field in existing: raise ValueError('Existing judgment cannot be overwritten; create explicit new Evidence context instead')
        existing[c.field]=(c.text,c.evidence_state)
    questions=dict(QUESTIONS)
    if schema_version=='1': questions['root_cause']=questions['root_cause'].replace('检索或回答问题','排序问题')
    missing=[{'field':k,'question':q,'state':'MISSING'} for k,q in questions.items() if k not in existing]
    return existing,items,missing[:3]
