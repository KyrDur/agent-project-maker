<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { contextDefaults } from '../career-workspace.js'
import EvidenceDetails from '../components/EvidenceDetails.vue'
import InterviewPractice from '../components/InterviewPractice.vue'
const career=inject('career'),work=inject('workspace'),{state}=career
const restoring=ref(true)
const context=ref(contextDefaults()),editKey=ref(''),editText=ref(''),notice=ref(''),roles=ref('')
const focus=ref('EVALUATION_WORKBENCH'),target=ref('AI_EVALUATION_PLATFORM_PM'),speechRate=ref(240),judgments=ref({}),judgmentsConfirmed=ref(false),exportGroup=ref('')
const options=()=>({project_focus:focus.value,career_target:target.value,speech_rate:Number(speechRate.value),completions:Object.entries(judgments.value).filter(([k,v])=>v?.trim()).map(([field,text])=>({field,text,evidence_state:field==='root_cause'?'INFERENCE':'USER_CONFIRMED',temporal_scope:'RETROSPECTIVE',confirmed:true}))})
watch(()=>state.view,v=>{if(v){focus.value=v.project_focus;target.value=v.career_target;judgments.value=Object.fromEntries((v.completions||[]).map(c=>[c.field,c.text]));judgmentsConfirmed.value=!!v.completions?.length}})
async function inspect(){await career.preview({project_focus:focus.value,career_target:target.value})}
async function generate(){if(Object.values(judgments.value).some(v=>v?.trim())&&!judgmentsConfirmed.value){notice.value='请确认补充判断属实，根因只作为待验证假设保存。';return}await career.generateV2(options())}
const tabs=['Evidence','Case Study','Resume','Interview','Defense']
onMounted(async()=>{try{await career.restore()}catch{notice.value='材料入口暂时无法恢复，请从历史记录重试。'}finally{restoring.value=false}})
watch(()=>state.evidence,e=>{context.value=e?.context?{...e.context}:contextDefaults();roles.value=context.value.user_roles.join('、')},{immediate:true})
const selected=computed(()=>career.selection())
const ready=computed(()=>['project_name','motivation','target_users','user_problem','why_ai','user_contribution','system_contribution','existing_capabilities'].every(k=>context.value[k]?.trim()) && roles.value.trim() && typeof context.value.real_users==='boolean' && typeof context.value.deployed==='boolean' && context.value.confirmed)
const verified=computed(()=>state.evidence?.claims.filter(c=>['RECORDED','DERIVED','USER_CONFIRMED'].includes(c.confidence))||[])
const resumeClaims=id=>state.evidence?.claims.filter(c=>id.includes(c.claim_id))||[]
function begin(group,s){editKey.value=group+':'+s.section_id;editText.value=s.text}
async function save(group,s){await career.edit(group,s.section_id,editText.value);editKey.value=''}
async function confirm(){context.value.user_roles=roles.value.split(/[、,，\n]/).map(s=>s.trim()).filter(Boolean);await career.build(context.value)}
async function copy(){try{const data=await career.export(exportGroup.value||null);await navigator.clipboard.writeText(data.markdown);notice.value='Markdown 已复制'}catch{notice.value='复制失败，请使用导出 Markdown'}}
async function download(){const data=await career.export(exportGroup.value||null);const blob=new Blob([data.markdown],{type:'text/markdown;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=data.filename;a.click();URL.revokeObjectURL(url);notice.value='Markdown 已导出'}
const groups=computed(()=>state.tab==='Case Study'?['case_study']:state.tab==='Resume'?['resume_ai','resume_general']:state.tab==='Interview'?['interview']:[])
const dimensionLabels={completeness:'叙事完整性',evidence_integrity:'事实可追溯性',ownership_clarity:'个人贡献边界',metric_literacy:'指标口径',decision_depth:'决策依据',interview_clarity:'口述清晰度',followup_resilience:'深入追问准备'}
const statusLabels={READY:'已具备',NEEDS_INPUT:'待本人补充',NEEDS_VERIFICATION:'待验证',DRAFT:'草稿'}
const heading={resume_ai:'AI 产品版',resume_general:'通用产品版',case_study:'项目复盘',interview:'面试口述'}
</script>
<template>
 <div class="page-heading"><div><p class="eyebrow">EVIDENCE → CAREER</p><h1>把做过的实验，说清楚。</h1><p>每一句关键结论都有来源，缺少的事实由你补充。</p></div></div>
 <section class="panel"><h2>选择当前实验的证据</h2><p>{{selected.experiment_type==='RETRIEVAL'?'RAG 检索实验':'Agent 行为实验'}} · Baseline {{selected.baseline_run_id || '尚未选择'}} · {{selected.comparison_id?'已有对比':'尚无对比，只能生成事实草稿'}}</p>
  <button class="primary" :disabled="restoring || !selected.baseline_run_id || !!work.state.busy" @click="career.build()">整理当前实验事实</button>
  <p class="muted">旧材料保持原样。实验或背景变化后，请显式创建新 Evidence，再重新生成材料。</p>
  <details><summary>打开历史证据 / 材料</summary><div class="button-row"><button v-for="e in state.evidenceHistory" :key="e.evidence_object_id" class="secondary" :disabled="!!work.state.busy" @click="career.openEvidence(e.evidence_object_id)">{{e.project_name}} · Evidence v{{e.evidence_version}}</button><button v-for="m in state.materialHistory" :key="m.material_id" class="secondary" :disabled="!!work.state.busy" @click="career.openMaterial(m.material_id)">材料 v{{m.material_version}} · {{m.label}} · Evidence v{{m.evidence_version}}</button></div></details>
 </section>
 <template v-if="state.evidence">
  <nav class="button-row career-tabs" aria-label="材料类型"><button v-for="t in tabs" :key="t" :class="state.tab===t?'primary':'secondary'" @click="state.tab=t">{{t}}</button></nav>
  <p class="note">锁定 Evidence v{{state.evidence.evidence_version}} · {{state.material?.label || 'Draft'}}。Evidence-backed 表示陈述有记录来源，不代表因果证明或商业验证。</p>
  <template v-if="state.tab==='Evidence'">
   <div class="intro-cards"><section><h3>有来源的事实</h3><strong>{{verified.length}}</strong></section><section><h3>不能证明什么</h3><strong>{{state.evidence.limitations.length}}</strong></section><section><h3>待补充</h3><strong>{{state.evidence.missing_evidence.length}}</strong></section></div>
   <section class="panel"><h2>我能安全说什么</h2><ul><li v-for="c in state.evidence.claims.filter(c=>c.allowed_for_resume)" :key="c.claim_id">{{c.claim_text}} <small>· {{c.source_type}}</small></li></ul><details><summary>全部事实与来源</summary><div v-for="c in state.evidence.claims" :key="c.claim_id" class="builder-card"><p>{{c.claim_text}} · {{c.source_type}}</p><EvidenceDetails :data="c" title="Claim 证据路径" /></div></details></section>
   <section class="panel"><h2>我不能证明什么</h2><ul><li v-for="l in state.evidence.limitations" :key="l">{{l}}</li></ul><h3>退化与无效结果</h3><p>退化 Case：{{state.evidence.regressions.length}}；无效 / 缺失记录：{{state.evidence.invalid_cases.length}}</p><p v-for="r in state.evidence.regressions" :key="r.case_id">{{r.case_id}} · {{r.transition || r.effective_transition}}</p><p v-for="r in state.evidence.invalid_cases" :key="r.run_id+r.case_id+r.category">{{r.case_id}} · {{r.category}}</p></section>
   <section class="panel"><h2>确认项目背景和贡献边界</h2><p>这里由你提供事实。AI Coding、平台执行与已有能力需要分别说明。</p>
    <fieldset :disabled="!!work.state.busy"><label>项目名称<input v-model="context.project_name" /></label><label>项目类型<select aria-label="项目类型" v-model="context.project_context"><option value="PERSONAL_PROJECT">个人项目</option><option value="INTERNSHIP">实习项目</option><option value="COURSE">课程项目</option><option value="COMPETITION">比赛项目</option><option value="OTHER">其他</option></select></label>
     <label>为什么做这个项目<textarea v-model="context.motivation" rows="2" /></label><label>目标用户<input v-model="context.target_users" /></label><label>要解决的用户问题<textarea v-model="context.user_problem" rows="2" /></label><label>为什么需要 AI / Agent / RAG<textarea v-model="context.why_ai" rows="2" /></label>
     <label>我的角色（用顿号分隔）<input v-model="roles" placeholder="如：产品设计、评测设计、AI Coding" /></label><label>我主导的判断与工作<textarea v-model="context.user_contribution" rows="3" /></label><label>AI Coding / 平台完成的工作<textarea v-model="context.system_contribution" rows="3" /></label><label>原项目已有的能力<textarea v-model="context.existing_capabilities" rows="2" /></label>
     <div class="form-row"><label>是否有真实用户<select aria-label="是否有真实用户" v-model="context.real_users"><option :value="null">请选择</option><option :value="false">没有</option><option :value="true">有（仅记录自述，不证明用户量）</option></select></label><label>是否真实上线<select aria-label="是否真实上线" v-model="context.deployed"><option :value="null">请选择</option><option :value="false">没有</option><option :value="true">有（仅记录自述，不证明线上效果）</option></select></label></div>
     <details><summary>反思建议 · 确认后才进入面试稿</summary><ul><li v-for="r in state.evidence.reflection_candidates" :key="r">{{r}}</li></ul></details><label>如果重来一次，我会怎么做<textarea v-model="context.reflection" rows="2" /></label><label class="check"><input type="checkbox" v-model="context.reflection_confirmed" :disabled="!context.reflection.trim()" />我确认这段反思符合我的判断</label><label class="check"><input type="checkbox" v-model="context.confirmed" />我确认以上项目背景与贡献边界属实</label>
     <button class="primary" :disabled="!ready" @click="confirm">确认事实并创建新 Evidence 版本</button>
    </fieldset><p v-if="state.evidence.context" class="note positive">本 Evidence 已绑定用户确认背景。</p><ul><li v-for="m in state.evidence.missing_evidence" :key="m">{{m}}</li></ul>
   </section>
   <EvidenceDetails :data="{hash:state.evidence.evidence_hash,source_map:state.evidence.source_map}" title="高级 Evidence Source / Fact Lock" />
  </template>
  <section class="panel" v-if="state.evidence.context"><h2>选择叙事主线与求职定位</h2><p>新材料使用当前锁定证据和所选叙事。旧材料仍可从历史记录打开，不会被覆盖。生成过程不调用收费模型。</p>
   <div class="form-row"><label>项目主线<select v-model="focus"><option value="EVALUATION_WORKBENCH">Agent 评测与优化工作台</option><option value="CUSTOMER_SERVICE_APP">电商客服应用（背景不足时标缺口）</option></select></label><label>求职定位<select v-model="target"><option value="AI_EVALUATION_PLATFORM_PM">AI 评测 / 平台产品经理</option><option value="AI_APPLICATION_PM">AI 应用产品经理</option><option value="GENERAL_PM">通用产品经理</option></select></label><label>口述语速（单位 / 分钟）<input v-model="speechRate" type="number" min="180" max="300" /></label></div>
   <button class="secondary" :disabled="!!work.state.busy" @click="inspect">检查证据与待补判断</button>
   <template v-if="state.view"><h3>只补充真正缺少的判断</h3><p>已有修改理由和已确认反思会复用。补充内容单独保存，不改原实验；根因始终标为待验证假设。</p><p v-if="!state.view.missing_questions.length">当前没有需要补充的判断。</p>
   <label v-for="q in state.view.missing_questions.filter(q=>q.field!=='app_context')" :key="q.field">{{q.question}}<textarea v-model="judgments[q.field]" rows="3" /></label><p v-for="q in state.view.missing_questions.filter(q=>q.field==='app_context')" :key="q.field" class="note warning">{{q.question}}</p>
   <details v-if="state.view.completions.length"><summary>已保存的补充判断</summary><p v-for="c in state.view.completions" :key="c.field">{{c.field}} · {{c.evidence_state}} · {{c.text}}</p></details>
   <label class="check" v-if="Object.values(judgments).some(v=>v?.trim())"><input type="checkbox" v-model="judgmentsConfirmed" />我确认这些是本人补充的判断；根因尚待验证</label></template>
  </section>
  <section class="panel"><div class="button-row"><button class="primary" :disabled="!state.evidence.context || !!work.state.busy" @click="generate">基于此 Evidence 生成全套材料</button><label v-if="state.material?.view_id">导出范围<select aria-label="导出范围" v-model="exportGroup"><option value="">全套材料</option><option value="case_study">项目复盘</option><option value="resume_ai">AI PM 简历</option><option value="resume_general">通用 PM 简历</option><option value="interview">面试讲稿</option><option value="defense">追问证据卡</option></select></label><button v-if="state.material" class="secondary" @click="copy">复制 Markdown</button><button v-if="state.material" class="secondary" @click="download">导出 Markdown</button></div><p v-if="notice" role="status">{{notice}}</p><p v-if="!state.evidence.context">请先填写并确认项目背景和贡献边界。</p></section>
  <template v-if="state.material">
   <section class="panel" v-if="state.material.view_id"><h2>面试材料准备度</h2><p>这是材料内部完整性检查，不预测面试通过率。Draft 可以导出，但应保留待补充标记。</p><details v-for="(checks,name) in state.material.readiness" :key="name"><summary>{{heading[name]||'追问证据卡'}}</summary><p v-for="(check,key) in checks" :key="key">{{dimensionLabels[key]||key}} · {{statusLabels[check.status]||check.status}} · {{check.reason}}</p></details><EvidenceDetails :data="state.view?.facts" title="规范化 Claim 与原始证据路径" /></section>

   <section v-if="state.material.lint.length" class="panel"><h2>材料风险检查 · {{state.material.label}}</h2><p v-for="(l,i) in state.material.lint" :key="i" class="note warning">{{l.code}} · {{l.message}}</p></section>
   <template v-for="g in groups" :key="g"><section class="panel"><h2>{{heading[g]}}</h2><article v-for="s in state.material.sections[g]" :key="s.section_id" class="builder-card" :data-testid="'career-'+g+'-'+s.section_id"><h3>{{s.title}}</h3><p class="note warning" v-if="s.source_type==='USER_UNVERIFIED_CLAIM'">当前为自由编辑文案，原机器引用不证明修改稿属实。</p><p class="career-text">{{s.text}}</p><details v-if="s.source_type==='USER_UNVERIFIED_CLAIM'"><summary>对照机器原稿</summary><p class="career-text">{{s.safe_wording}}</p></details><p v-if="s.timing?.estimated_seconds" class="muted">按所选语速估计约 {{s.timing.estimated_seconds}} 秒；请实际试读。</p><details v-if="s.citations?.length"><summary>逐条事实引用</summary><div v-for="(cite,i) in s.citations" :key="i"><p>{{cite.text_span}}</p><EvidenceDetails :data="cite" title="引用的 Claim / 原始路径" /></div></details>
    <details><summary>Evidence Inspector · 来源 / 风险 / 追问</summary><p>安全措辞：{{s.safe_wording}}</p><ul><li v-for="risk in s.risk" :key="risk">{{risk}}</li><li v-for="q in s.possible_follow_up" :key="q">追问：{{q}}</li></ul><div v-for="c in resumeClaims(s.claim_ids)" :key="c.claim_id"><p>{{c.claim_id}} · {{c.claim_text}} · {{c.source_type}}</p><EvidenceDetails :data="c" title="Supporting Evidence" /></div></details>
    <div v-if="editKey===g+':'+s.section_id"><p class="muted">机器原稿：{{s.safe_wording||s.text}}</p><label>编辑文案<textarea v-model="editText" rows="6" /></label><p class="note">FACT 保持锁定。自由编辑会保存为文案草稿；与 Evidence 不一致的数字或结论会标记风险，不自动成为实验事实。</p><button class="primary" :disabled="!editText.trim() || !!work.state.busy" @click="save(g,s)">保存文案新版本</button><button class="text-button" @click="editKey=''">取消</button></div>
    <div v-else class="button-row"><button class="secondary" :disabled="!!work.state.busy" @click="begin(g,s)">编辑文字</button><button class="text-button" :disabled="!!work.state.busy" @click="career.regenerate(g,s.section_id)">从锁定 Evidence 重新生成此段</button></div>
   </article></section></template>
   <section v-if="state.tab==='Interview'" class="panel"><h2>Contribution Summary</h2><p v-for="c in state.material.contribution_summary" :key="c.owner">{{c.owner}}：{{c.text}}</p></section>
   <section v-if="state.tab==='Defense'" class="panel"><h2>项目追问 · {{state.material.defense.length}} 题</h2><details v-for="q in state.material.defense" :key="q.question_id" class="builder-card"><summary>{{q.pressure?'压力追问 · ':''}}{{q.category}} · {{q.question}}</summary><InterviewPractice :material-id="state.material.material_id" :question="q" /><details><summary>查看参考回答提纲</summary><p class="career-text">{{q.suggested_answer_outline}}</p></details><h4>下一层追问</h4><p v-for="f in q.possible_follow_up" :key="f">{{f}}</p><h4>风险 / 限制</h4><ul><li v-for="r in q.risk" :key="r">{{r}}</li></ul><p v-for="m in q.missing_information" :key="m">{{m}}</p><EvidenceDetails :data="{claim_ids:q.claim_ids,paths:q.supporting_evidence}" title="Supporting Evidence" /></details></section>
  </template>
 </template>
</template>
<style scoped>
.career-tabs{margin:24px 0}.career-text{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.9}.builder-card{margin:18px 0}fieldset{border:0;padding:0}details{margin:14px 0}summary{cursor:pointer}li{line-height:1.8;margin:8px 0}small{overflow-wrap:anywhere}
</style>
