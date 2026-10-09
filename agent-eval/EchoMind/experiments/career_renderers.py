"""Purpose-specific prose from a checked plan. No clipping and no model calls."""
from .retrieval_embeddings import description as embedding_description
import re
from .canonical import digest
from .career_models import CareerBundle,CareerSection

TITLES={'case_study':'项目复盘','resume_ai':'AI 产品经理简历','resume_general':'通用产品经理简历','interview':'面试讲稿'}

def sentences(text):
    # Select whole propositions, never a character budget or incomplete substring.
    return [x.strip() for x in re.split(r'(?<=[。！？])',str(text)) if x.strip()]

def clean(text):
    return str(text).strip().rstrip('。；;')+'。'

def timing(text,rate):
    units=len(re.findall(r'[\u4e00-\u9fff]|[A-Za-z0-9]+',text))
    return {'spoken_units':units,'estimated_seconds':round(units*60/rate),
            'estimated_range_seconds':[round(units*60/300),round(units*60/180)],'units_per_minute':rate,
            'basis':'工程估算，中文字符与英文词各计一单位；请以实际试读为准'}

class Renderer:
    def __init__(self,e,v,p): self.e=e;self.v=v;self.p=p;self.f=v.facts;self.legacy=v.schema_version=='1'
    def val(self,key,default=None): return self.f[key].value if key in self.f else default
    def section(self,sid,title,paragraphs,speech=False):
        text='\n\n'.join(t for t,refs in paragraphs)
        refs=list(dict.fromkeys(k for t,ks in paragraphs for k in ks))
        citations=[{'text_span':t,'fact_ids':ks,'claim_ids':list(dict.fromkeys(c for k in ks for c in self.f[k].claim_ids)),
                    'evidence_paths':list(dict.fromkeys(path for k in ks for path in self.f[k].evidence_paths))} for t,ks in paragraphs]
        return CareerSection(section_id=sid,title=title,text=text,claim_ids=list(dict.fromkeys(c for k in refs for c in self.f[k].claim_ids)),
                    citations=citations,safe_wording=text,timing=timing(text,self.p.speech_rate) if speech else {})
    def usable(self):
        comp=self.val('comparison',{})
        return bool(comp.get('comparable') and self.e.retest_run_id and not self.v.conflicts)
    def result(self,brief=False):
        if not self.usable(): return '当前没有条件一致且证据完整的有效对比，不能宣称优化有效。',['comparison']
        if 'metric_mrr' not in self.f:
            a=self.val('answer_before');b=self.val('answer_after')
            return f"回答评测前后分别有 {a.get('valid',0)} 与 {b.get('valid',0)} 个有效 Case，通过数分别为 {a.get('passed',0)} 与 {b.get('passed',0)}。无效结果与意图样本不混入通过率分母。",['answer_before','answer_after','comparison']
        h=self.val('metric_hit_at_1');m=self.val('metric_mrr');c=self.val('transitions')
        scope='匹配有效子集' if self.val('comparison').get('comparison_completeness')=='PARTIAL' else '本次离线样本'
        text=f"在{scope}中，首位命中率 Hit@1 从 {h['before']:.2f} 变为 {h['after']:.2f}，按固定候选池计算的 MRR 从 {m['before']} 变为 {m['after']:.2f}，对应有效标注分母分别是 {h['denominator']} 和 {m['denominator']}。"
        if not brief: text+=f"逐题比较显示 {c.get('RETRIEVAL_IMPROVED',0)} 道排名改善、{c.get('RETRIEVAL_UNCHANGED',0)} 道不变、{c.get('RETRIEVAL_REGRESSED',0)} 道退化。"
        return text,['metric_hit_at_1','metric_mrr','transitions','comparison','acquisition']
    def discovery(self):
        if 'rank_movements' not in self.f: return '我从保存的失败案例及原始判定中定位本轮要检查的问题。',['selected','answer_before']
        ranks=self.val('rank_movements');selected=self.val('selected',[])
        row=next((r for r in ranks if r['case_id'] in selected),ranks[0] if ranks else None)
        if not row: return '尚缺少可复核的典型问题与排名记录。',['rank_movements']
        if self.legacy:
            return f"“{row['query']}”对应的正确知识在初测候选池排第 {row['before']} 位，复测排第 {row['after']} 位。这说明本轮关注的是候选排序；它还不是回答质量结论。",['rank_movements','selected','answers']
        before='未检索到' if row['before'] is None else f"排第 {row['before']} 位"
        after='未检索到' if row['after'] is None else f"排第 {row['after']} 位"
        scope='本轮验证知识补充后的检索变化；回答判定单独查看。' if self.val('change',{}).get('change_type')=='KNOWLEDGE_UPDATE' else '本轮记录候选排序变化；它还不是回答质量结论。'
        return f"“{row['query']}”对应的正确知识在初测候选池{before}，复测{after}。{scope}",['rank_movements','selected','answers','change']
    def action(self):
        ch=self.val('change',{})
        names={'RERANK_TOGGLE':'知识重排开关','QUERY_REWRITE_TOGGLE':'问题改写开关','TOP_K':'返回数量'}
        if self.e.experiment_type=='RETRIEVAL':
            a=self.val('config_before',{});b=self.val('config_after') or {}
            diff=[k for k in a if a[k]!=b.get(k)] if b else []
            title=names.get(ch.get('change_type'),'检索配置')
            if ch.get('change_type')=='KNOWLEDGE_UPDATE':
                text='本轮只更新知识版本，保留原测试题、预期行为与检索配置；实际文档变化和版本见修改证据。'
            elif diff==['rerank']: text=f"本轮只把{title}从关闭改为开启，让模型对已召回的候选知识重新排序。"
            elif diff==['query_rewrite']: text=f"本轮只把{title}从关闭改为开启，先改变检索使用的问题表达。"
            else: text='本轮记录的配置变化为：'+ '、'.join(f'{k}：{a[k]} → {b[k]}' for k in diff)+'。' if diff else '尚没有已生效的修改记录。'
            return text,['change','config_before','config_after']
        return '本轮修改以保存的 Skill 实际差异为准，具体规则及生效范围见修改证据。',['change']
    def contribution(self):
        roles=self.e.context.user_roles
        # No inference of personal engineering from the role label "AI Coding".
        product=[r for r in roles if r!='AI Coding']
        system='工程代码与测试由 Codex 完成，实验执行和统计由平台完成。' if 'Codex' in self.val('system_contribution') else clean(sentences(self.val('system_contribution'))[0])
        return '我在项目中承担'+ '、'.join(product)+'；'+system,['user_roles','user_contribution','system_contribution']
    def value(self):
        if self.v.project_focus=='CUSTOMER_SERVICE_APP':
            return '本材料选择电商客服应用视角，目前只能用检索实验讨论知识支撑问题；客服用户需求与业务场景还缺少独立确认。',['answers','why_ai']
        return clean(self.val('user_problem')),['user_problem']
    def boundary(self,brief=False):
        if self.e.experiment_type=='RETRIEVAL' and not self.val('answers')['enabled']:
            pairs=self.val('comparison',{}).get('case_pairs',[])
            answer_note=f"{len(pairs)} 道回答比较均不可比较。" if pairs and all(row['answer_transition']=='NOT_COMPARABLE' for row in pairs) else '回答结果无法前后比较。'
            text='本次没有运行回答评测，'+answer_note+'检索排名改善不能证明回答质量、业务效果或严格因果改善。'
        else: text='检索与回答分别解释；已采集的回答结果见评测证据，执行错误、Judge 失败和待人工复核均不能伪装成成功。' if self.e.experiment_type=='RETRIEVAL' else '结果来自离线 Agent 实验；本次未运行完整 RAG 和 Memory。'
        if not brief: text+='可比较只是控制条件检查通过；单次前后观察仍不能证明严格因果。'
        return text,['answers','comparison','limitations']
    def technique(self):
        if 'acquisition' not in self.f: return self.boundary()
        r=self.e.retrieval_evidence;a=self.val('config_before');b=self.val('config_after')
        pools=self.val('acquisition');lines=[]
        for side,label in [('baseline','Baseline'),('retest','Retest')]:
            rows=pools.get(side,[]);cfg=a if side=='baseline' else b
            if not cfg or not rows: continue
            values=lambda k:' / '.join(str(n) for n in sorted({x[k] for x in rows}))
            lines.append(f"{label}：候选数量上限 {cfg['candidate_pool_size']}，实际初始召回 {values('initial_candidates')} 条；重排输入 {values('rerank_input')} 条；最终 Top K 为 {cfg['top_k']}，实际返回 {values('final_returned')} 条。Query Rewrite {'开启' if cfg['query_rewrite'] else '关闭'}，Rerank {'开启' if cfg['rerank'] else '关闭'}。")
        scale=f"知识规模为 {r['document_count']} 份文档、{r['chunk_count']} 个片段"
        update=self.val('knowledge_update',{})
        if update:
            scale=f"初测知识 v{update['before_version']} 为 {r['document_count']} 份文档、{r['chunk_count']} 个片段；复测知识 v{update['after_version']}"
            if 'after_document_count' in update: scale+=f" 为 {update['after_document_count']} 份文档、{update['after_chunk_count']} 个片段"
            else: scale+=f" 新增 {len(update['added_ids'])}、移除 {len(update['removed_ids'])} 份文档"
        lines.append(f"{scale}；切分上限 {r['chunk_strategy']['chunk_size']} 字符、重叠 {r['chunk_strategy']['chunk_overlap']} 字符。使用{embedding_description(r['embedding_config'])}、{r['embedding_config'].get('dimension')} 维、cosine 检索。模型名称不代表效果提升，结果仅限本次测试。")
        lines.append('MRR 与首位命中率按固定候选池统计；Recall@K、Precision@K 和 NDCG@K 按最终返回结果统计。因此候选池 Rank 5 或 8 可以存在，但不代表知识已进入 Top K。')
        return '\n'.join(lines),['acquisition','config_before','config_after','document_count','chunk_count','chunk_strategy','embedding_config','metric_mrr']
    def technical_paragraphs(self):
        text,refs=self.technique()
        if 'acquisition' not in self.f: return [(text,refs)]
        lines=text.split('\n');parts=[]
        for line in lines:
            if line.startswith('Baseline'): keys=['acquisition','config_before']
            elif line.startswith('Retest'): keys=['acquisition','config_after']
            elif line.startswith(('知识规模','初测知识')): keys=['document_count','chunk_count','chunk_strategy','embedding_config']+(['knowledge_update'] if 'knowledge_update' in self.f else [])
            else: keys=['acquisition','metric_mrr','config_before','config_after']
            parts.append((line,keys))
        return parts
    def reflection(self):
        if self.f['interpretation'].evidence_state=='MISSING': return '后续验证计划尚待本人确认。',['interpretation']
        propositions=sentences(self.val('interpretation'))
        chosen=next((t for t in propositions if '验证' in t or '重复运行' in t),propositions[0])
        chosen=re.sub(r'^实验上会','下一步计划',chosen)
        return clean(chosen),['interpretation']
    def case_study(self):
        d=self.discovery();result=self.result();action=self.action()
        control='固定原题、标签、模型、切分与检索配置，只更换知识版本及其索引；以实际差异和可比较性检查验证实验条件。' if not self.legacy and self.val('change',{}).get('change_type')=='KNOWLEDGE_UPDATE' else '固定题目、标签和索引；除已记录的修改外保持其他配置一致，以实际差异及可比较性检查验证实验条件。'
        reflection_paragraphs=[]
        root=self.f['root_cause'];alt=self.f['alternatives'];interpret=self.f['interpretation']
        roottext='根因尚未确认，当前只记录排序现象；原因仍是待验证假设，需要另做对照检验。' if root.evidence_state=='MISSING' else '待验证根因假设：'+clean(root.value)
        alttext='尚未记录备选方案比较，不能补写当时已经比较过 Query Rewrite 或 Embedding。' if alt.evidence_state=='MISSING' else '用户补充的方案取舍：'+clean(alt.value)
        reflection='下一步验证计划尚待用户补充；生成器不代替用户作出决定。' if interpret.evidence_state=='MISSING' else clean(interpret.value)
        if 'experiment_conclusion' in self.f:
            conclusion=self.val('experiment_conclusion');label={'KEEP':'保留修改','REVISE':'继续调整','REVERT':'采用初测版本'}[conclusion['decision']]
            reflection_paragraphs.append(('保存的实验结论：'+label+'。'+clean(conclusion['reason']),['experiment_conclusion']))
        reflection_paragraphs.append((reflection,['interpretation']))
        sections=[self.section('value','要解决的产品问题',[(clean(self.val('motivation')),['motivation']),self.value(),('这个工作台面向'+clean(self.val('target_users')),['target_users'])]),
          self.section('ownership','我的工作与协作边界',[(clean(self.val('user_contribution')),['user_contribution']),(clean(self.val('system_contribution')),['system_contribution']),(clean(self.val('existing_capabilities')),['existing_capabilities'])]),
          self.section('problem','问题发现',[d]),
          self.section('decision','个人判断与方案取舍',[(clean(self.val('decision')) if self.val('decision') else '尚无用户确认的修改理由。',['decision']),(roottext,['root_cause']),(alttext,['alternatives'])]),
          self.section('control','修改与验证方法',[action,(control+('匹配结果不完整，结论仅限已完成的有效子集。' if self.val('comparison',{}).get('comparison_completeness')=='PARTIAL' else ''),['change','comparison'])]),
          self.section('results','观察结果',[result]),
          self.section('limits','结果边界',[self.boundary(),(f"当前记录有 {len(self.val('regressions'))} 个退化 Case、{len(self.val('invalid_cases'))} 个无效或缺失记录；{'有' if self.val('real_users') else '没有'}真实用户、{'已' if self.val('deployed') else '未'}上线（用户自述）。",['regressions','invalid_cases','real_users','deployed'])]),
          self.section('reflection','复盘与下一步',reflection_paragraphs),
          self.section('technical','技术证据说明',self.technical_paragraphs())]
        by_beat=dict(zip(['value','ownership','discovery','judgment','control','result','boundary','reflection'],sections[:-1]))
        return [by_beat[beat] for beat in self.p.material_orders['case_study']]+[sections[-1]]
    def resume_ai(self):
        result,refs=self.result(True);contrib,c=self.contribution();action,a=self.action()
        emphasis={'AI_APPLICATION_PM':'将客服知识检索作为 AI 应用能力验证场景，区分检索、回答和业务结果。',
          'AI_EVALUATION_PLATFORM_PM':'以评测可信度和实验条件检查组织产品验证，区分记录完整性与因果证据。',
          'GENERAL_PM':'围绕用户难以解释 AI Demo 效果的问题，组织阶段验收与迭代验证。'}[self.v.career_target]
        return [self.section('ai_problem','产品职责',[(contrib,c),(emphasis,['user_problem','why_ai','comparison','answers'])]),
          self.section('ai_eval','实验与结果',[(action,a),(result,refs),(self.boundary(True)[0],self.boundary(True)[1])]),
          self.section('ai_next','贡献边界与后续验证',[self.reflection(),(f"基于原有 Agent 与检索能力推进产品实践；当前{'没有' if not self.val('real_users') else '有用户自述的'}真实用户，{'尚未上线' if not self.val('deployed') else '部署为用户自述'}。",['existing_capabilities','real_users','deployed'])])]
    def resume_general(self):
        # Resume prose selects the user-value conclusion and one experiment;
        # it does not copy the entire decision form or technical metric list.
        problem_units=sentences(self.val('user_problem'))
        problem=next((t for t in problem_units if '帮助用户' in t),problem_units[0])
        action,action_refs=self.action()
        h=self.val('metric_hit_at_1')
        if h and self.usable():
            outcome=f"在 {h['denominator']} 道有效标注题中，正确知识排在首位的比例从 {h['before']*100:g}% 变为 {h['after']*100:g}%；这是离线检索观察，尚无回答质量或业务收益结论。"
            result_refs=['metric_hit_at_1','comparison','answers']
        else: outcome,result_refs=self.result(True)
        return [self.section('pm_problem','用户问题与项目推进',[(clean(problem),['user_problem']),self.contribution()]),
          self.section('pm_decision','决策与验证',[(action,action_refs),(outcome,result_refs)]),
          self.section('pm_reflection','下一步验证计划',[self.reflection()])]
    def interviews(self):
        name=self.val('project_name');app=self.v.project_focus=='CUSTOMER_SERVICE_APP'
        opening=f'我做的项目是{name}，用电商客服场景练习如何发现 AI 问题、验证修改并解释结果。' if not app else '这次我从电商客服知识检索切入，检查哪些知识能被正确找到；客服应用需求尚待补充。'
        contribution,c=self.contribution();row=next((r for r in self.val('rank_movements',[]) if r['case_id'] in self.val('selected',[])),None)
        finding=(f"我关注的‘{row['query']}’，正确知识初测"+('未检索到。' if row['before'] is None else f"排第 {row['before']} 位。")) if row else '我从初测的逐题记录中检查问题。'
        if self.legacy and row: finding=f"我关注的‘{row['query']}’，正确知识初测排第 {row['before']} 位。"
        action,a=self.action();h=self.val('metric_hit_at_1');m=self.val('metric_mrr')
        result=(f"本次 {h['denominator']} 道有效标注题的首位命中率，从 {h['before']*100:g}% 变为 {h['after']*100:g}%。" if h and self.usable() else self.result(True)[0])
        rrefs=['metric_hit_at_1','comparison'] if h else self.result(True)[1]
        reason='我的判断是先检验模型重排能否让已召回的正确知识靠前，而不是同时更换多个组件。' if self.e.change.get('change_type')=='RERANK_TOGGLE' else '选择依据以本人确认的修改理由为准，尚未确认的原因不能作为实验结论。'
        # Short version leads with value and ownership. Medium is a single decision story;
        # long version explains verification and scope. These are independent compositions.
        thirty=[(opening,['project_name','why_ai']), (contribution,c),
                 ('我把重点放在可追溯的实验，而不是只展示一个能运行的 Demo。当前结果属于离线验证，还不能代表业务收益。',['user_problem','comparison','limitations'])]
        sixty=[(opening,['project_name','why_ai']),(contribution,c),(finding,['selected','rank_movements'] if row else ['selected']),
               (reason,['decision','change']),(action,a),(result,rrefs),('这次观察只说明知识排序变化，没有证明回答或业务变好。更完整的验证还需要补充。',['answers','comparison','limitations'])]
        ninety=[(opening,['project_name','why_ai']),(contribution,c),
                 (finding+'我先看逐题证据，再决定本轮修改对象。',['selected','rank_movements','decision'] if row else ['selected','decision']),
                 (reason,['decision','change']),(action,a),(('复测固定知识、题目与其他配置，同时检查改善、不变和退化的案例，避免只挑一题展示。' if self.legacy else '知识更新复测固定原题、模型与检索配置，保留各知识版本；逐题结果与后续回归需求分别记录。' if self.val('change',{}).get('change_type')=='KNOWLEDGE_UPDATE' else '复测固定知识、题目与其他配置，逐题检查改善、不变和退化。'),['change','comparison','regressions']),
                 (result+(f"候选池口径的 MRR 从 {m['before']} 变为 {m['after']:.2f}。" if m and self.usable() else ''),rrefs+(['metric_mrr'] if m else [])),
                 (self.boundary(True)[0],self.boundary(True)[1]),
                 ('我的反思是：'+clean(sentences(self.val('interpretation'))[0]) if self.f['interpretation'].evidence_state!='MISSING' else '根因与下一步计划仍需补充证据，不能用一次好结果代替长期验证。',['interpretation','root_cause'])]
        # The plan selects the logical order; the renderer independently chooses
        # each version's language and evidence density.
        def organize(key,parts,beats):
            mapped={}
            for beat,part in zip(beats,parts): mapped.setdefault(beat,[]).append(part)
            return [part for beat in self.p.material_orders[key] for part in mapped.get(beat,[])]
        thirty=organize('story30',thirty,['value','ownership','boundary'])
        sixty=organize('story60',sixty,['value','ownership','discovery','judgment','judgment','result','reflection'])
        ninety=organize('story90',ninety,['value','ownership','discovery','judgment','judgment','control','result','boundary','reflection'])
        return [self.section('story30','30 秒介绍',thirty,True),self.section('story60','60 秒讲稿',sixty,True),self.section('story90','90 秒讲稿',ninety,True),
          self.section('architecture30','技术链路说明',self.technical_paragraphs()+[self.boundary()])]

def content(e,v,p):
    from .interview_intelligence import questions
    r=Renderer(e,v,p)
    groups={'case_study':r.case_study(),'resume_ai':r.resume_ai(),'resume_general':r.resume_general(),'interview':r.interviews()}
    if v.project_focus=='CUSTOMER_SERVICE_APP':
        # Never borrow workbench users/responsibilities to portray a launched app.
        notice=r.section('scope','应用主线缺口',[('当前用户确认背景属于评测工作台；以下检索证据可以讨论应用能力，但不能代表客服应用产品已经上线或经过用户验证。',['user_problem','real_users','deployed','answers'])])
        groups['case_study']=[notice,*[s for s in groups['case_study'] if s.section_id not in {'value','ownership'}]]
        groups['resume_ai']=[notice,*groups['resume_ai'][1:]]
        groups['resume_general']=[notice,*groups['resume_general'][1:]]
    return groups,questions(r),r

def generate(e,v,p,version):
    from .career_readiness import assess
    groups,defense,r=content(e,v,p)
    bundle=CareerBundle(evidence_object_id=e.evidence_object_id,evidence_version=e.evidence_version,evidence_hash=e.evidence_hash,
      material_version=version,generator_version='evidence-narrative-renderer-v2' if v.schema_version=='1' else 'agenteval-evidence-renderer-v3',view_id=v.view_id,view_hash=p.view_hash,
      narrative_id=p.narrative_id,narrative_hash=digest(p.model_dump(mode='json')),
      introduction=e.context.project_name,sections=groups,defense=defense,
      contribution_summary=[{'owner':f.owner,'text':f.value} for k,f in v.facts.items() if k in {'user_contribution','system_contribution','existing_capabilities'}],
      reflection_candidates=e.reflection_candidates,lint=[],label='Draft')
    issues,readiness=assess(e,v,p,bundle)
    return bundle.model_copy(update={'lint':issues,'readiness':readiness,'label':'Mixed' if issues else 'Draft' if v.missing_questions or not r.usable() else 'Evidence-backed'})

def markdown_v2(bundle,group=None,appendix=True):
    if group not in {None,*TITLES,'defense'}: raise ValueError('Unknown export group')
    lines=['# '+bundle.introduction,'材料状态：'+bundle.label+'。准备度仅检查材料完整性，不预测面试通过率。']
    refs=[]
    def prose(text,citations):
        output=text
        for citation in citations:
            span=citation['text_span']
            # Edited text loses machine citation; do not imply it is verified.
            if span not in output: continue
            refs.append(citation);number=len(refs)
            output=output.replace(span,span+f' [^{number}]',1)
        return output
    for name,sections in bundle.sections.items():
        if group and group!=name: continue
        lines+=['\n## '+TITLES[name]]
        for s in sections:
            rendered=prose(s.text,s.citations)
            if name.startswith('resume_'): lines+=['- **'+s.title+'**：'+rendered.replace('\n\n',' ')]
            else: lines+=['\n### '+s.title,rendered]
            if s.timing: lines+= [f"口述估计：约 {s.timing['estimated_seconds']} 秒；语速区间估计 {s.timing['estimated_range_seconds']} 秒，请实际试读。"]
    if group in {None,'defense'}:
        lines+=['\n## 面试追问证据卡']
        for q in bundle.defense:
            lines+=['\n### '+q.category+' · '+q.question,prose(q.suggested_answer_outline,q.citations),
                    '下一层追问：'+'；'.join(q.possible_follow_up),'证据缺口 / 边界：'+('；'.join(q.missing_information+q.risk) or '本回答限于所选实验记录，不代表更大样本或线上验证。')]
    lines+=['\n## 材料准备度']
    for name,checks in bundle.readiness.items():
        if group and group!=name: continue
        lines.append(name+'：'+'；'.join(k+'='+v['status']+('（'+v['reason']+'）' if v['reason'] else '') for k,v in checks.items()))
    if bundle.user_edits: lines+=['自由编辑内容未经证据核验，导出为文案草稿。']
    if appendix:
        lines+=['\n## 证据附录（正文引用 → Claim → 原始路径）',f'Evidence {bundle.evidence_object_id} / v{bundle.evidence_version} / {bundle.evidence_hash}',
                f'View {bundle.view_id} / {bundle.view_hash}；Narrative {bundle.narrative_id} / {bundle.narrative_hash}']
        for i,c in enumerate(refs,1):
            lines.append(f"[^{i}]: 规范化 Claim：{', '.join(c['fact_ids'])}；原 Claim：{', '.join(c['claim_ids']) or '见 View 规范化 Claim'}；路径："+'；'.join(c['evidence_paths']))
    return '\n\n'.join(lines)+'\n'
