"""Deterministic product narratives; every section carries claim references."""
from collections import Counter
import json,re
from .career_models import CareerBundle, CareerSection, DefenseQuestion

MISSING='待补充'

def short(value,size=55):
    value=str(value or MISSING).strip()
    return value if len(value)<=size else value[:size]+'…'

def generate(e,version=1):
    ctx=e.context
    if ctx is None: raise ValueError('User context required')
    claims={c.claim_id:c for c in e.claims}
    def ids(*types): return [c.claim_id for c in e.claims if c.claim_type in types]
    all_ids=[c.claim_id for c in e.claims if c.source_type!='MISSING']
    def section(sid,title,text,refs=None,follow=None):
        refs=all_ids if refs is None else refs
        return CareerSection(section_id=sid,title=title,text=text,claim_ids=refs,
            risk=list(e.limitations),possible_follow_up=follow or [],safe_wording=text)
    name=ctx.project_name;count=e.baseline['dialog_case_count'];is_rag=e.experiment_type=='RETRIEVAL'
    kind='RAG 知识检索' if is_rag else 'Agent 行为与 Skill'
    intro=f'{name}面向{short(ctx.target_users)}，围绕{short(ctx.user_problem)}开展{kind}评测与单变量实验。'
    decision=e.user_decision.get('reason') if is_rag else e.user_decision.get('selection_reason')
    selected=e.diagnosis.get('selected_case_ids',[]) or e.user_decision.get('selected_case_ids',[])
    root=e.diagnosis.get('root_cause') if is_rag else e.diagnosis.get('user_confirmed_root_cause')
    root=root or MISSING
    diagnosis=f'关注 Case：{", ".join(selected) or MISSING}。用户确认根因：{root}。依据：{e.diagnosis.get("reason") or MISSING}。备选原因/方案：{json.dumps(e.diagnosis.get("alternatives",MISSING),ensure_ascii=False)}。'
    if is_rag:
        change_name=e.change.get('change_type') or MISSING
        before_config=e.change.get('before_config',{});after_config=e.change.get('after_config',{})
        change_text=f'修改类型：{change_name}。'
        for field in ['top_k','query_rewrite','rerank']:
            if before_config.get(field)!=after_config.get(field): change_text+=f" {field}：{before_config.get(field)} → {after_config.get(field)}。"
        change_text+='声明与实际生效的差异保存在 Change 原始证据中；不能凭 Change 标题认定单一干预。'
        r=e.retrieval_evidence
        config=r['config_before'];chunk=r['chunk_strategy'];embed=r['embedding_config']
        design=f"先将 {r['document_count']} 份知识整理为 {r['chunk_count']} 个可检索片段，再按问题找相关内容。每段最多 {chunk['chunk_size']} 字符，相邻重叠 {chunk['chunk_overlap']} 字符。当前使用本地词汇向量，Embedding 模型 {embed.get('model')}，维度 {embed.get('dimension')}；通过本地隔离的 Chroma 集合进行 cosine 检索。返回 Top K = {config['top_k']}；Query Rewrite = {config['query_rewrite']}，Rerank = {config['rerank']}。这些配置来自索引与 Run，选择参数的个人理由仍需补充。"
        sources=dict(Counter(c.get('source') or '未标注' for c in e.baseline['case_sources']))
        criteria=f'{count} 道 Retrieval Cases；标签由输入的相关文档/片段 ID 确定。题目来源分布：{sources}，标签构建过程仍需用户补充。Hit@1/Hit@3 看正确知识是否靠前；MRR 衡量首个相关结果的倒数排名；Recall@K 看覆盖率；Precision@K 看返回结果的相关比例；NDCG@K 看相关知识的排序质量。各指标按有效且有标注的样本分别取分母。'
        metric_lines=[]
        if e.comparison and e.comparison['comparable']:
            pa=r['paired_metrics']['baseline'];pb=r['paired_metrics']['retest']
            for metric in ['hit_at_1','hit_at_3','recall_at_k','precision_at_k','mrr','ndcg_at_k']:
                n=pa.get('denominators',{}).get(metric,0)
                metric_lines.append(f'{metric}：{pa.get(metric)} → {pb.get(metric)}，有效匹配标注分母 {n}')
        else: metric_lines=['尚无可比较的正式 Comparison，不能生成改善结论。']
        ranks='\n'.join(f"- {p['case_id']}（{p['query']}）：Rank {p['before']} → {p['after']}；{p['transition']}；回答 {p['answer_transition']}" for p in r['rank_movements']) or MISSING
        results='\n'.join(metric_lines)+'\n\n'+ranks
        baseline_text=f'检索 Baseline：'+readable_metrics(r['baseline_metrics'])+f'。关注 Case：{", ".join(selected) or MISSING}。'
        current_pairs=e.comparison.get('case_pairs',[])
        counts=dict(Counter(p['transition'] for p in current_pairs))
        answers=dict(Counter(p['answer_transition'] for p in current_pairs))
        results+=f'\n检索变化：{counts}。回答变化：{answers}。检索改善与回答改善分开解释。'
        metric_claims=[c for c in e.claims if c.claim_type=='PAIRED_MRR' and c.allowed_for_resume]
    else:
        change_name='ONE_SKILL_RULE_BODY' if e.change.get('entries') else MISSING
        change_text=readable_change(e.change) if e.change else MISSING
        design=e.answer_evidence['workflow']+'。本次使用冻结的 Agent、角色模型和 Skill 版本，RAG 与 Memory 关闭。'
        criteria=f'{count} 道 Dialog Cases，每个多轮任务只算一题；Intent 独立统计。先检查执行有效性，再判 Hard Rule，再要求 relevance / accuracy / completeness / helpfulness 各自达到 threshold，最后处理 Human Review。配置：{json.dumps(e.answer_evidence["evaluation_config"],ensure_ascii=False)}。'
        baseline_text='Baseline：'+readable_answer_metrics(e.baseline['answer_metrics'])+f'。Intent 样本数：{e.baseline["intent_sample_count"]}，独立统计。关注 Case：{", ".join(selected) or MISSING}。'
        results='回答 Baseline：'+readable_answer_metrics(e.baseline['answer_metrics'])+'。Retest：'+readable_answer_metrics(e.retest.get('answer_metrics',{}))+'。\n'
        results+='\n'.join(f"- {p['case_id']}：机器 {p['machine_status_a']} → {p['machine_status_b']}；有效判定 {p['effective_status_a']} → {p['effective_status_b']}；{p['effective_transition']}" for p in e.comparison.get('case_comparisons',[])) or MISSING
        counts=e.comparison.get('group_metrics',{}).get('dialog_case_metrics',{}).get('transitions',{})
        results+=f'\n匹配有效 Case 的变化：{counts}。没有混合 Intent 和 Dialog 分母。'
        metric_claims=[]
    regression_text='\n'.join('- '+str(p.get('case_id'))+'：'+str(p.get('transition') or p.get('effective_transition'))+'；回答 '+str(p.get('answer_transition','见有效判定')) for p in e.regressions) or '本次保存的 Comparison 未记录退化；不代表未来或所有场景无退化。'
    invalid_text='\n'.join(f"- {r['run_id']} / {r['case_id']}：{r['category']}" for r in e.invalid_cases) or '当前所选证据未记录无效样本；缺失字段不能据此假定成功。'
    limitations='\n'.join('- '+x for x in e.limitations)
    contribution=f'用户确认的工作：{ctx.user_contribution}。角色：{", ".join(ctx.user_roles)}。\nAI Coding / 平台：{ctx.system_contribution}。\n原有能力：{ctx.existing_capabilities}。这是贡献边界的用户自述，不能当作独立工程贡献审计。'
    accepted=('在固定显式实验条件下记录并观察前后结果，可用于形成下一轮验证假设。' if e.comparison.get('comparable') else '当前只支持描述实验流程和已记录结果；控制条件尚不可直接比较。')
    reflection=ctx.reflection if ctx.reflection_confirmed else '待补充：反思候选需要用户确认，未自动写入个人经历。'
    baseline_text+='\n所选 Case 的机器证据：'+readable_bad_cases(e.baseline.get('selected_case_evidence',[]))
    case_specs=[('background','项目背景',f'{intro}\n项目类型：{ctx.project_context}。动机：{ctx.motivation}。目标用户：{ctx.target_users}。问题：{ctx.user_problem}。AI 适用原因（用户确认）：{ctx.why_ai}。'),
        ('role','我的角色与边界',contribution),('solution','产品方案',design),('criteria','如何定义做得好',criteria),
        ('baseline','Baseline',baseline_text),('diagnose','Diagnose',diagnosis),('decision','Decision',decision or MISSING),
        ('change','Change',change_text),('retest','Retest',f'所选 Retest：{e.retest_run_id or MISSING}；状态：{e.retest.get("status",MISSING)}。使用该 Run 已保存的冻结配置和执行顺序。'),
        ('result','Result',results),('regression','What got worse / Remaining problems',regression_text),('invalid','INVALID 与采集缺失',invalid_text),
        ('reviews','Human Review / Rollback',readable_reviews(e.human_reviews)+'\nRollback：'+', '.join(str(c.get('rollback_status')) for c in e.change.get('entries',[]))),
        ('means','What the evidence means',accepted),('limits','What the evidence does NOT prove',limitations),
        ('reflection','Reflection',reflection),('next','Next Step','候选建议，需要用户决定：\n'+'\n'.join('- '+s for s in e.reflection_candidates))]
    case_study=[section(sid,title,text) for sid,title,text in case_specs]
    context_refs=ids('CONTEXT_USER_CONTRIBUTION','CONTEXT_USER_PROBLEM','CONTEXT_TARGET_USERS')
    resume_ai=[section('ai_problem','产品问题与职责',f'围绕{short(ctx.user_problem)}设计{kind}实验；本人负责{short(ctx.user_contribution,85)}。',context_refs+ids('CASE_COUNT'),['你具体负责哪些判断？哪些实现由 AI Coding 完成？']),
        section('ai_eval','评测方法',f'使用 {count} 道任务级测试题记录 Baseline；'+('分开检查检索排名、检索指标与最终回答质量。' if is_rag else '区分 Dialog 与 Intent 指标，并保留 Hard Rule、Judge、INVALID 和人工复核证据。'),ids('CASE_COUNT','CHANGE','BASE_MODEL'),['题目和标签由谁设计？统计分母是什么？'])]
    if decision:
        resume_ai.append(section('ai_change','优化决策',f'依据所选 Case 记录{change_name}修改及理由：{short(decision,75)}；{'通过 Retest 检查改善和退化' if e.retest_run_id else '计划用同一套测试复测，结果待补充'}，结论限于所选受控实验。',ids('USER_DECISION','CHANGE','REGRESSIONS','INVALID_CASES'),['为什么选这个修改？还有哪些备选方案？']))
    if metric_claims:
        m=metric_claims[0]
        resume_ai.append(section('ai_result','观察结果',m.claim_text+('这是本地端点的受控观察' if e.project_identity['provider_classification']=='LOCAL_OR_UNVERIFIED' else '这是一次受控观察')+'，尚不能归因于该修改；退化项与限制见项目复盘。',[m.claim_id]+ids('COMPARABILITY','REGRESSIONS'),['MRR 怎么算？多少个有效样本？能证明因果吗？']))
    general=[section('product_problem','用户问题与设计',f'面向{short(ctx.target_users)}，围绕{short(ctx.user_problem)}拆解测试目标；本人负责{short(ctx.user_contribution,85)}。',context_refs),
        section('product_validation','数据验证',f'使用 {count} 道测试题建立首次验证记录，逐题检查问题并保存{'修改前后的证据' if e.retest_run_id else '首次结果，复测证据待补充'}。',ids('CASE_COUNT','REGRESSIONS','INVALID_CASES')),
        section('product_iteration','迭代与取舍',f'优化判断：{short(decision or MISSING,90)}；保留改善、退化和无效结果，形成可复核的迭代记录。AI / 平台承担：{short(ctx.system_contribution,70)}。',ids('USER_DECISION','CONTEXT_SYSTEM_CONTRIBUTION','REGRESSIONS','INVALID_CASES'))]
    # A bounded spoken narrative; no 8-metric recital. Unconfirmed reflection remains missing.
    outcome=('记录了前后可比较的结果，具体改善和退化以逐题证据为准' if e.comparison.get('comparable') else '完成了已有结果记录，但尚无可直接比较的改善结论')
    if metric_claims:
        m=metric_claims[0];outcome=f'在匹配有效标注子集，观察到 MRR 从 {m.value_before:.3f} 到 {m.value_after:.3f}'
    retest_phrase='再用固定测试复测' if e.retest_run_id else '后续需要用固定测试复测'
    provider_scope='本次使用本地端点，商业模型身份未验证。' if e.project_identity['provider_classification']=='LOCAL_OR_UNVERIFIED' else '模型后端版本未经独立验证。'
    story60=(f'我做的项目是{short(name,30)}，面向{short(ctx.target_users,22)}。起点是{short(ctx.motivation,28)}。'
        f'我负责{short(ctx.user_contribution,30)}，AI Coding 和平台负责{short(ctx.system_contribution,22)}。'
        f'我们用 {count} 道题建立 Baseline，关注{short(",".join(selected),25)}，判断依据是{short(decision,32)}。'
        f'这次只记录{change_name}修改，{retest_phrase}。{outcome}。'
        f'{provider_scope}这仍是离线实验，单次结果不能证明因果，也不能代表线上业务效果。反思：{short(ctx.reflection if ctx.reflection_confirmed else MISSING,25)}。')
    story90=(f'这个项目叫{short(name,30)}，面向{short(ctx.target_users,25)}，关注{short(ctx.user_problem,28)}。动机是{short(ctx.motivation,28)}。'
        f'我负责{short(ctx.user_contribution,40)}，AI Coding 和平台承担{short(ctx.system_contribution,25)}，既有能力是{short(ctx.existing_capabilities,22)}。'
        f'评测集包含 {count} 道任务级题目。'+('检索指标只统计有效且有相关性标签的样本，回答质量另外判断。' if is_rag else '多轮对话只算一题，执行或 Judge 失败标为 INVALID，不计入有效通过率。')+
        f'关注的 Case 是{short(",".join(selected),22)}，根因记录为{short(root,24)}。选择理由是{short(decision,32)}。'
        f'本次记录{change_name}修改，其他显式条件记录，{retest_phrase}并检查对比。{outcome}。'
        f'退化项 {len(e.regressions)} 个，无效或缺失记录 {len(e.invalid_cases)} 条，全部保留在复盘里。'
        f'{provider_scope}这些证据支持受控观察，不能证明严格因果，也不能当作生产用户效果。'
        f'如果重来：{short(ctx.reflection if ctx.reflection_confirmed else MISSING,30)}。')
    architecture=('用户提问后，系统按配置决定是否改写，再从固定知识中找候选，按配置决定是否重新排序。选出的知识用于生成回答，最后分别检查检索结果和回答质量。当前是单一知识客服 Agent，没有完整意图路由和 Memory。' if is_rag else '系统先识别用户问题的类型，再选择对应客服 Agent。Agent 调用业务工具后回答；评测先检查是否执行成功，再检查业务红线、四维质量门槛和人工复核。当前实验关闭知识检索与 Memory。')
    interview=[section('story60','约 60 秒',story60),section('story90','约 90 秒',story90),section('architecture30','约 30 秒架构解释',architecture),section('technical','可展开技术详情',design)]
    # 15 project-specific cards, with five pressure follow-ups. Combined RAG cards
    # cover all metrics/configuration instead of emitting a generic question bank.
    questions=[('Business','为什么做这个项目，为什么需要 AI？',ctx.motivation+'；'+ctx.why_ai,context_refs,False),
        ('Contribution','你这个是不是 AI 帮你写的，你本人到底做了什么？',contribution,ids('CONTEXT_USER_CONTRIBUTION','CONTEXT_SYSTEM_CONTRIBUTION','CONTEXT_EXISTING_CAPABILITIES'),True),
        ('Product Decision',f'为什么关注 {", ".join(selected) or "尚未选择的 Case"}，为什么优先改 {change_name}？',diagnosis+'\n理由：'+(decision or MISSING),ids('USER_DECISION','USER_ROOT_CAUSE','DIAGNOSIS','CHANGE'),False),
        ('Evaluation',f'这 {count} 道题从哪里来？Ground Truth 谁标注？',criteria,ids('CASE_COUNT','RAG_GROUND_TRUTH_SOURCE'),False),
        ('Metrics',f'只有 {count} 道题，为什么这个指标能证明优化有效？','只能描述所选有效样本，不能证明总体效果或因果。'+accepted,ids('CASE_COUNT','COMPARABILITY'),True),
        ('Limitations','你怎么证明变化是这次修改造成的？','当前不能证明。'+limitations,ids('COMPARABILITY','CHANGE'),True),
        ('Business','没有生产效果证据，这算什么产品项目？',f'这是{ctx.project_context}。真实用户和部署仅为用户确认的背景；未提供独立商业效果证据。'+accepted,ids('CONTEXT_PROJECT_CONTEXT','CONTEXT_REAL_USERS','CONTEXT_DEPLOYED'),True),
        ('Limitations','有哪些 Regression、INVALID、Human Review 或 Rollback？',regression_text+'\n'+invalid_text+'\n'+json.dumps(e.human_reviews,ensure_ascii=False),ids('REGRESSIONS','INVALID_CASES','HUMAN_REVIEWS','CHANGE'),False),
        ('Product Decision','如果重新做一次，会怎么改？',reflection,ids('USER_REFLECTION','REGRESSIONS','INVALID_CASES'),False),
        ('Agent','使用什么 Base Model？换模型会怎样？',json.dumps(provider_fact(e),ensure_ascii=False)+'；不同模型需要新实验，当前不能推测结果。',ids('BASE_MODEL'),False)]
    if is_rag:
        r=e.retrieval_evidence
        questions.extend([
            ('RAG','知识来源是什么，Chunk 为什么这么切？',design+'\n选择该切分参数的用户理由：待补充。',ids('RAG_DOCUMENT_COUNT','RAG_CHUNK_COUNT','RAG_CHUNK_STRATEGY'),False),
            ('RAG','Embedding 和 Vector DB 实际用了什么，Top K 如何设置？',design,ids('RAG_EMBEDDING_CONFIG','RAG_VECTOR_STORE','CHANGE'),False),
            ('RAG',f'Query Rewrite / Rerank 哪个改了，为什么没有同时改另一个？',change_text+'\n选择理由：'+(decision or MISSING)+'\n未选择其他方案的理由：待补充。',ids('CHANGE','USER_DECISION'),False),
            ('Metrics','Hit@1、Hit@3、Recall@K、Precision@K、MRR、NDCG 的分母和用途是什么？',criteria+'\n'+results,ids('CASE_COUNT')+[c.claim_id for c in e.claims if c.claim_type.startswith('PAIRED_')],False),
            ('RAG','正确知识 Rank 上升，为什么不等于回答或产品变好了？',results+'\n检索命中只是上下文证据，回答还可能编造、遗漏或违反红线；没有用户/业务实验不能推导产品效果。',ids('CASE_RANK_MOVEMENT','REGRESSIONS','INVALID_CASES'),True)])
    else:
        questions.extend([
            ('Agent','Intent、Routing、Tool Calling 实际 workflow 是什么？',architecture,ids('BASE_MODEL','DIAGNOSIS'),False),
            ('Evaluation','Hard Rule 和自然语言期望怎么区分，四维 Judge 怎么判？',criteria+'\n只有结构化 executable_rules 是确定性规则；自然语言仅是 Judge 与人工复核上下文。',ids('CASE_COUNT','BASELINE_ANSWER_INVALID'),False),
            ('Product Decision','Skill Rule 到底改了什么，Rollback 如何保留证据？',change_text,ids('CHANGE','USER_DECISION'),False),
            ('Evaluation','人工改判能不能把机器红线违规洗掉？',json.dumps(e.human_reviews,ensure_ascii=False)+'\n机器原判保留；Hard Rule 改 PASS 必须显式 override。无效执行或 Judge 失败不能变成有效 PASS。',ids('HUMAN_REVIEWS','INVALID_CASES'),False),
            ('Metrics','通过率提升能不能说明产品变好了？',results+'\n有效 Dialog 分母与 Intent 分开，单次离线实验不证明用户或业务效果。',ids('CASE_COUNT','COMPARABILITY','REGRESSIONS'),True)])
    defense=[]
    for i,(cat,q,outline,refs,pressure) in enumerate(questions):
        evidence_refs=[path for cid in refs for path in claims[cid].evidence_path]
        missing_info=[]
        if MISSING in outline: missing_info.append('需要用户补充。')
        defense.append(DefenseQuestion(question_id='defense_'+str(i+1),category=cat,question=q,
            suggested_answer_outline=outline,claim_ids=refs,supporting_evidence=evidence_refs,risk=e.limitations,
            missing_information=missing_info,pressure=pressure))
    bundle=CareerBundle(evidence_object_id=e.evidence_object_id,evidence_version=e.evidence_version,evidence_hash=e.evidence_hash,
        material_version=version,introduction=intro,sections={'case_study':case_study,'resume_ai':resume_ai,'resume_general':general,'interview':interview},
        defense=defense,contribution_summary=[{'owner':'USER_CONFIRMED','text':ctx.user_contribution,'roles':ctx.user_roles},
        {'owner':'AI_CODING_PLATFORM','text':ctx.system_contribution},{'owner':'EXISTING_CAPABILITY','text':ctx.existing_capabilities}],
        reflection_candidates=e.reflection_candidates,lint=[],label='Draft')
    issues=lint_bundle(e,bundle)
    return bundle.model_copy(update={'lint':issues,'label':label_for(e,issues,False)})

def provider_fact(e):
    return {'requested_configuration':e.baseline['provider_configuration'],'identity':e.project_identity['provider_classification']}

def numbers(text):
    # Chinese numeric assertions are also checked, not just Arabic digits.
    normalized=text.replace('％','%')
    values=set(re.findall(r'(?<![A-Za-z_])\d+(?:\.\d+)?%?',normalized))
    values|=set(re.findall(r'[零一二两三四五六七八九十百千万]+(?=\s*(?:道|条|份|个|人|倍|万|%|元))',normalized))
    return values

def positive_clauses(text):
    return [s for s in re.split(r'[。；\n]',text) if not re.search(r'不能|不证明|无法|不等于|不代表|尚不能|不应|禁止|未经|未验证|尚未验证|没有.*证据|未提供',s)]

def lint_bundle(e,bundle):
    issues=[]
    def issue(code,group,sid,message):
        item={'code':code,'group':group,'section_id':sid,'message':message,'severity':'BLOCK_EVIDENCE_BACKED'}
        if item not in issues: issues.append(item)
    claims={c.claim_id:c for c in e.claims}
    for c in e.claims:
        if c.source_type=='USER_ENTERED_CONTEXT' and re.search(r'(?:\d|[十百千万]).{0,12}(?:用户|提升|准确率|MRR|GMV|留存|DAU)|(?:用户量|提升|准确率|MRR|GMV|留存|DAU).{0,12}\d',c.claim_text,re.I):
            issue('USER_UNVERIFIED_PERFORMANCE_NUMBER','context',c.claim_id,'用户自述的业绩数字没有独立实验或商业证据。')
    for group,sections in bundle.sections.items():
        for s in sections:
            text=s.text
            supported=numbers(s.safe_wording)
            for cid in s.claim_ids:
                if cid not in claims:
                    issue('MISSING_EVIDENCE',group,s.section_id,'引用了不存在的 Claim');continue
                c=claims[cid]
                for value in (c.value_before,c.value_after):
                    if isinstance(value,(int,float)) and not isinstance(value,bool): supported|=numbers(str(value))
            if numbers(text)-supported: issue('UNSUPPORTED_NUMBER',group,s.section_id,'该数字与所引用 Evidence 不一致。')
            if s.source_type=='USER_UNVERIFIED_CLAIM': issue('USER_UNVERIFIED_CLAIM',group,s.section_id,'用户自由编辑仅保存为文案草稿；未自动当作新的实验事实。')
            for clause in positive_clauses(text):
                if re.search(r'证明.{0,25}(导致|因果)|导致.{0,25}(提升|改善)|严格因果|全面提升|无损提升|显著提升|成功归因',clause) and not e.comparison.get('attributable'):
                    issue('UNSUPPORTED_CAUSALITY',group,s.section_id,'当前证据不支持强因果结论。')
                if re.search(r'上线后|已上线|生产效果提升|用户反馈显示|DAU|GMV|留存提升|业务提升|真实线上.*提升',clause):
                    issue('DEMO_PRESENTED_AS_PRODUCTION',group,s.section_id,'没有独立生产或商业效果证据。')
                if e.project_identity['provider_classification']=='LOCAL_OR_UNVERIFIED' and re.search(r'商业模型.*(验证|提升)|OpenAI.*效果提升|DeepSeek.*效果提升',clause):
                    issue('SCRIPTED_PROVIDER_PRESENTED_AS_COMMERCIAL',group,s.section_id,'本地或脚本 Provider 不能冒充商业模型验证。')
                if re.search(r'全部.{0,8}(手写|从零)|手写.{0,8}(全部|数万)|独立手写',clause):
                    issue('PERSONAL_CONTRIBUTION_AMBIGUOUS',group,s.section_id,'个人贡献与 AI Coding 边界不清楚。')
                if re.search(r'历史.{0,25}(本次|当前).{0,10}(提升|指标)',clause): issue('HISTORICAL_METRIC_PRESENTED_AS_CURRENT',group,s.section_id,'历史数字不能当作当前 Run。')
                if re.search(r'可比较.{0,10}(证明|就是).{0,8}可归因',clause): issue('COMPARABLE_ATTRIBUTABLE_CONFUSED',group,s.section_id,'可比较不等于可归因。')
                if re.search(r'INVALID.{0,15}(计入|算作).{0,8}(通过|成功)',clause): issue('INVALID_INCLUDED_IN_SUCCESS_RATE',group,s.section_id,'无效样本不能算作成功。')
                if re.search(r'(原有|已有|原仓库).{0,20}(我开发|本人实现|我手写)',clause): issue('EXISTING_CAPABILITY_CLAIMED_AS_USER_WORK',group,s.section_id,'已有能力不能自动归为个人开发。')
                if re.search(r'AI建议.{0,20}(我决定|我的决策|已确认)',clause) and not e.user_decision: issue('AI_SUGGESTION_CLAIMED_AS_USER_DECISION',group,s.section_id,'未确认建议不能变成用户决策。')
    case={s.section_id:s.text for s in bundle.sections['case_study']}
    if e.regressions:
        if any(p['case_id'] not in case.get('regression','') for p in e.regressions): issue('HIDDEN_REGRESSION','case_study','regression','必须展示所选 Comparison 的退化 Case。')
    if e.invalid_cases:
        if any(r['case_id'] not in case.get('invalid','') for r in e.invalid_cases): issue('HIDDEN_INVALID','case_study','invalid','无效与缺失记录不能删除。')
    if any(l not in case.get('limits','') for l in e.limitations): issue('MISSING_LIMITATION','case_study','limits','实验限制必须完整保留。')
    if not e.retest_run_id:
        for g in ['resume_ai','resume_general','interview']:
            for s in bundle.sections[g]:
                if any(re.search(r'提升|优化成功|改善了',c) for c in positive_clauses(s.text)): issue('MISSING_RETEST',g,s.section_id,'没有 Retest 不能生成改善结论。')
    return issues

def label_for(e,issues,edited):
    if e.experiment_type=='RETRIEVAL':
        usable=e.comparison.get('paired_metrics',{}).get('baseline',{}).get('denominators',{}).get('mrr',0)
    else: usable=e.comparison.get('group_metrics',{}).get('dialog_case_metrics',{}).get('valid_pair_count',0)
    if not usable: return 'Draft'
    if e.context is None or not e.retest_run_id or not e.comparison or not e.comparison.get('comparable'):
        return 'Draft'
    if issues or edited: return 'Mixed'
    return 'Evidence-backed'

def markdown(bundle):
    lines=[f'# {bundle.introduction}',f'状态：{bundle.label}',f'Evidence：{bundle.evidence_object_id} / v{bundle.evidence_version} / {bundle.evidence_hash}',
           'Evidence-backed 仅指陈述有记录来源，不代表因果证明或独立商业验证。']
    for group,sections in bundle.sections.items():
        lines.append('\n## '+{'case_study':'项目复盘','resume_ai':'AI 产品简历','resume_general':'通用产品简历','interview':'面试口述'}[group])
        for s in sections:
            lines.extend(['\n### '+s.title,s.text,'Claim 来源：'+', '.join(s.claim_ids)])
    lines.append('\n## 面试追问证据卡')
    for q in bundle.defense:
        lines.extend(['\n### '+q.question,q.suggested_answer_outline,'Evidence：'+', '.join(q.supporting_evidence),
                      'Risk：'+'；'.join(q.risk),'Missing：'+'；'.join(q.missing_information)])
    if bundle.lint: lines.extend(['\n## 风险检查',json.dumps(bundle.lint,ensure_ascii=False,indent=2)])
    return '\n\n'.join(lines)+'\n'


def readable_metrics(m):
    return '；'.join(f"{key} {m.get(key) if m.get(key) is not None else MISSING}（有效标注分母 {m.get('denominators',{}).get(key,0)}）" for key in ['hit_at_1','hit_at_3','mrr','recall_at_k','precision_at_k','ndcg_at_k'])

def readable_answer_metrics(m):
    if not m: return MISSING
    return f"总题数 {m.get('total',0)}，有效 {m.get('valid',0)}，PASS {m.get('passed',0)}，FAIL {m.get('failed',0)}，INVALID {m.get('invalid',0)}，待人工复核 {m.get('pending_human_reviews',0)}；通过率以有效 Case 为分母"

def readable_bad_cases(rows):
    lines=[]
    for r in rows:
        if 'query' in r:
            lines.append(f"{r['case_id']}：{r.get('query')}；正确知识 Rank {r.get('metrics',{}).get('relevant_rank')}，检索状态 {r.get('status')}。")
        else:
            turns=r.get('turn_evidence',[])
            lines.append(f"{r['case_id']}："+' / '.join(t.get('question','') for t in turns)+f"；机器原判 {r.get('original_status')}，理由 {r.get('original_reason')}。"+'\n回答摘要：'+short(' / '.join(t.get('response','') for t in turns),220))
    return '\n'.join(lines) or MISSING

def readable_change(change):
    lines=[]
    for c in change.get('entries',[]):
        lines.append(f"{c['change_type']} / {c['change_scope']}；实际生效 {c['implemented_status']}；Rollback {c['rollback_status']}。")
        for diff in c.get('observed_diff',[]):
            path=diff['path'];parts=path.split('/')
            filename='/'.join(parts[1:-1])
            left=c['before_snapshot'].get('files',{}).get(filename)
            right=c['after_snapshot'].get('files',{}).get(filename)
            lines.append('修改路径：'+path+'\n修改前规则：'+(left or MISSING)+'\n修改后规则：'+(right or MISSING))
    return '\n'.join(lines) or MISSING

def readable_reviews(records):
    lines=[]
    for r in records:
        result=r.get('effective_result',r)
        lines.append(f"Case {r['case_id']}：Machine {result.get('original_status')} → Human {result.get('human_final_status')}；hard_rule_override={result.get('hard_rule_override')}；理由 {result.get('human_reason')}。机器违规事实：{result.get('hard_rule_violations','见原始 Run')}。")
    return '\n'.join(lines) or '所选版本没有人工复核记录。'
