"""Six public interview themes guide questions, never supply project facts."""
from .career_models import DefenseQuestion
from .retrieval_embeddings import description as embedding_description

SOURCES=['https://www.nowcoder.com/discuss/'+n for n in ['926271539031412736','926271938274627584','846070418883506176','846095175859306496']]

def questions(r):
    from .career_renderers import sentences,clean
    if 'acquisition' in r.f:
        cfg=r.val('config_after') or r.val('config_before')
        chain=f"本次用{embedding_description(r.val('embedding_config'))}召回知识，{'开启模型重排后' if cfg['rerank'] else '按原检索顺序'}返回 Top K={cfg['top_k']}。"+('回答评测没有运行。' if not r.val('answers')['enabled'] else '回答评测结果单独统计。')
        chain_refs=['acquisition','config_before','config_after','embedding_config','answers']
        metric_answer='MRR 衡量首个相关结果在固定候选池中的倒数排名；Top K 是最终返回数量。二者截点不同，不能把候选排名等同于已返回知识。'
        metric_refs=['acquisition','metric_mrr','config_before','config_after']
    else:
        chain='本次是冻结配置的 Agent 行为与 Skill 实验，RAG 与 Memory 未运行。';chain_refs=['answers','limitations']
        metric_answer='本次不是检索排名实验；回答以有效 Case 为统计单位，意图评测另列。';metric_refs=['answer_before','answer_after']
    decision=''.join(sentences(r.val('decision'))[:2]) if r.val('decision') else '尚缺少用户确认的选择理由。'
    rows=[
      ('产品价值','为什么做这个项目，用户是谁？',[(r.val('motivation'),['motivation']),('这个工作台面向'+clean(r.val('target_users')),['target_users'])],['用户原本如何解决这个问题？有没有访谈证据？'],['用户背景为本人确认，尚无独立用户研究。']),
      ('产品价值','为什么需要 AI，是否有更简单的方案？',[(r.val('why_ai'),['why_ai'])],['关键词检索是否足够？'],['尚缺少非 AI 方案的对照证据。']),
      ('技术理解','本次真实执行的链路是什么？',[(chain,chain_refs)],['为什么选择这个 Embedding 和模型？'],['模型选择的个人取舍和后端身份验证尚不完整。']),
      ('技术理解','重排具体改变了什么？' if r.legacy else '本轮修改具体改变了什么？',[r.action()],['候选召回失败时重排还能解决吗？'],['重排针对已有候选排序，不能自动补回缺失知识。']),
      ('评测方法','题目和正确答案从哪里来？',[(f"本次有 {r.val('count')} 道固定题；标签来源和相关知识 ID 保存在题目快照。" ,['count','ground_truth_source'] if 'ground_truth_source' in r.f else ['count'])],['标签由谁审核？题目是否覆盖真实用户？'],['Demo 标签不是线上标注；独立标注审核过程尚缺少证据。']),
      ('评测方法','MRR 和 Top K 的口径为什么不同？',[(metric_answer,metric_refs)],['为什么不只看命中率？'],[]),
      ('评测方法','回答质量验证了什么？',[r.boundary()],['如何控制 Judge 偏差与人工覆盖？'],['未运行的回答评测不能描述为完成步骤。'] if not r.val('answers')['enabled'] else ['Judge 偏差仍需独立对照。']),
      ('优化决策','为什么优先处理这个问题？',[(decision,['decision']),r.discovery()],['怎样判断它值得优先处理？'],[]),
      ('优化决策','你认为根因是什么？',[(('待验证假设：'+str(r.val('root_cause'))) if r.f['root_cause'].evidence_state=='INFERENCE' else '尚缺少可验证的回答依据；当前只有排序现象，根因仍待验证。',['root_cause'])],['用哪组对照排除其他原因？'],['没有根因对照验证记录。']),
      ('优化决策','为什么没有先用其他方案？',[(str(r.val('alternatives')),['alternatives'])],['为何接受成本和等待时间风险？'],['没有记录时请补充真实取舍，不能代写已经比较过方案。'] if r.f['alternatives'].evidence_state=='MISSING' else []),
      ('个人贡献','你、Codex 和原仓库分别做了什么？',[r.contribution(),(clean(sentences(r.val('existing_capabilities'))[0]),['existing_capabilities'])],['举一个你亲自作出的产品判断？'],['个人工作为用户确认；工程实现不能归到本人手写。']),
      ('个人贡献','你本人的关键判断有哪些证据？',[(decision,['decision'])],['没有你，验收标准会缺少什么？'],['反事实问题尚无独立验证，不能自动宣称不可替代。']),
      ('结果与复盘','改善多少，分母是什么？',[r.result()],['这个指标能说明业务收益吗？'],['有限离线样本不代表线上效果，也不是因果证明。']),
      ('结果与复盘','有没有退化、无效结果和真实用户？',[(f"所选证据记录 {len(r.val('regressions'))} 个退化 Case、{len(r.val('invalid_cases'))} 个无效或缺失记录。用户确认{'有' if r.val('real_users') else '没有'}真实用户，{'已' if r.val('deployed') else '未'}上线。",['regressions','invalid_cases','real_users','deployed'])],['扩大样本以后是否仍然成立？'],['用户与部署状态为自述。']),
      ('结果与复盘','下一步怎么验证，重来一次会怎样？',[(str(r.val('interpretation')),['interpretation'])],['重复次数、回答验证和上线门槛怎么定？'],['计划不是已完成步骤；仍需后续实验。']),
    ]
    result=[]
    for i,(category,q,paragraphs,follow,risk) in enumerate(rows):
        s=r.section('q'+str(i),q,paragraphs)
        missing=[r.f[fid].fact_id+'：尚缺少可验证的回答依据' for c in s.citations for fid in c['fact_ids'] if r.f[fid].evidence_state=='MISSING']
        result.append(DefenseQuestion(question_id='q'+str(i),category=category,question=q,suggested_answer_outline=s.text,
          claim_ids=s.claim_ids,supporting_evidence=list(dict.fromkeys(path for c in s.citations for path in c['evidence_paths'])),
          risk=risk,missing_information=missing,possible_follow_up=follow,citations=s.citations,pressure=category in {'优化决策','个人贡献','结果与复盘'}))
    return result
