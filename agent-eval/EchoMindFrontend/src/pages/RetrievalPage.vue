<script setup>
import { embeddingLabel, semanticModel, lexicalModel } from '../embedding-models.js'
import { computed, inject, ref, watch } from 'vue'
import RunBriefing from '../components/RunBriefing.vue'
import TraceAssistant from '../components/TraceAssistant.vue'
import { resultStartingPoint } from '../journey-guidance.js'
import EvidenceDetails from '../components/EvidenceDetails.vue'
import StatusBadge from '../components/StatusBadge.vue'
import ExperimentHealth from '../components/ExperimentHealth.vue'
import MetricHelp from '../components/MetricHelp.vue'
import { retrievalMetrics } from '../retrieval-metric-help.js'
import { demoDocuments, demoCases } from '../rag-demo.js'
import { api } from '../api.js'
import { records } from '../case-import.js'
const props=defineProps({step:String})
const work=inject('workspace'), rag=inject('retrieval'), practice=inject('practice'), {state}=rag
const name=ref('我的知识检索实验'), documents=ref([{document_id:'doc_1',title:'',text:'',metadata:{}}]), cases=ref('')
const embeddingModel=ref(semanticModel)
const size=ref(200), overlap=ref(20), topK=ref(3), rewriting=ref(false), reranking=ref(false), answers=ref(true)
const error=ref(''), selected=ref(''), type=ref('QUERY_REWRITE_TOGGLE'), nextK=ref(5), reason=ref(''), confirmed=ref(false)
const connectionBlocker=computed(()=>{
  const session=work.state.session
  if(!session)return '尚未配置模型。请先到 Setup 输入自己的 API Key，保存模型会话并测试连接。'
  if(session.credential_status!=='PRESENT')return '当前模型凭据不可用。请到 Setup 重新输入 API Key 并保存，再测试连接。'
  if(session.judge_connection?.available===false)return '独立 Judge 凭据已失效，请到 Setup 重新连接或恢复默认 Judge。'
  if(session.text_connection_status==='FAILED')return '模型连接测试失败。请检查 Setup 中的地址、模型名称和 API Key，然后重新测试连接。'
  if(session.text_connection_status!=='READY')return 'API Key 已保存，但尚未通过模型连接测试。测试成功后，即可开始 Baseline。'
  return ''
})
const diagnosis=ref(''),alternatives=ref(''),risks=ref('')
const aiOrigin=ref('')
function useSuggestion(suggestion){
 if(suggestion.run_id!==state.baseline?.run.run_id)return
 if(suggestion.change_type==='HUMAN_REVIEW'){work.state.notice='请展开最终回答，使用人工复核入口核对判定。';return}
 if(suggestion.change_type==='CHECK_LABELS'){work.go('define');return}
 if(suggestion.change_type==='NEW_BASELINE'){work.go('setup');return}
 if(suggestion.change_type==='KNOWLEDGE_UPDATE'){work.go('knowledge');work.state.notice='请先补充并保存知识，再回到修改页记录这次知识更新。';return}
 selected.value=suggestion.case_id;type.value=suggestion.change_type
 diagnosis.value='AI 待核验假设：'+suggestion.reason+'\n验证建议：'+suggestion.verification
 risks.value=suggestion.side_effects;aiOrigin.value=suggestion.draft_id;reason.value='';alternatives.value='';confirmed.value=false
 work.go('improve')
}
if(state.preferredChange){type.value=state.preferredChange;state.preferredChange=null}
const reviewReason=ref(''),reviewStatus=ref('PASS'), override=ref(false)
const conclusion=ref('KEEP'),conclusionReason=ref(''),conclusionConfirmed=ref(false)
const orderedPairs=computed(()=>[...(state.comparison?.case_pairs || [])].sort((a,b)=>({RETRIEVAL_REGRESSED:0,NOT_COMPARABLE:1,RETRIEVAL_IMPROVED:2,RETRIEVAL_UNCHANGED:3}[a.transition]??4)-({RETRIEVAL_REGRESSED:0,NOT_COMPARABLE:1,RETRIEVAL_IMPROVED:2,RETRIEVAL_UNCHANGED:3}[b.transition]??4)))
watch(()=>state.comparison?.comparison_id,id=>{if(id)work.action('读取实验结论',()=>practice.loadConclusions(id))},{immediate:true})
const runSide=ref('RETEST')
watch(()=>state.knowledge,k=>{if(k){name.value=k.name;documents.value=k.documents.map(d=>({document_id:d.document_id,title:d.title,text:d.text,metadata:d.metadata}))}},{immediate:true})
watch(()=>state.evalSet,e=>{if(e)cases.value=JSON.stringify(e.cases,null,2)},{immediate:true})
watch(()=>state.baseline,v=>{if(v){selected.value=state.change?.selected_case_ids[0] || v.run.case_results.find(r=>r.metrics.relevant_rank!==1)?.case_id || v.run.execution_order[0];nextK.value=v.run.retrieval_config.top_k===20?19:Math.min(20,v.run.retrieval_config.top_k+2)}},{immediate:true})
watch(()=>state.retest,()=>{runSide.value='RETEST'})
watch([selected,type],()=>{state.preview=null})
const run=computed(()=>runSide.value==='BASELINE'?state.baseline:state.retest || state.baseline), currentCase=computed(()=>state.baseline?.run.case_results.find(c=>c.case_id===selected.value))
const targetIndex=ref(null),targetIndexError=ref(false)
watch(()=>state.change?.target_index_id,async id=>{
 targetIndex.value=null;targetIndexError.value=false
 if(!id)return
 try{const value=await api.get('/knowledge-indices/'+id);if(state.change?.target_index_id===id)targetIndex.value=value}
 catch{if(state.change?.target_index_id===id)targetIndexError.value=true}
},{immediate:true})
const retestIndex=computed(()=>state.change?.change_type==='KNOWLEDGE_UPDATE'
 ?(state.index?.index_id===state.change.target_index_id?state.index:targetIndex.value)
 :state.baseline?.run.controls.index_snapshot)
const startingPoint=computed(()=>resultStartingPoint(run.value))
const highlightedCase=ref(null)
function inspectRecommended(){
 const id=startingPoint.value?.caseId;if(!id)return
 highlightedCase.value=id
 const element=document.getElementById('retrieval-case-'+id)
 element?.focus({preventScroll:true})
 element?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'})
}
const metrics=retrievalMetrics
const format=(n)=>n==null?'unavailable':n.toFixed(3)
const rank=(n)=>n==null?'未找到':n
const labels={RETRIEVAL_IMPROVED:'检索改善',RETRIEVAL_REGRESSED:'检索退化',RETRIEVAL_UNCHANGED:'检索未变化',NOT_COMPARABLE:'无法比较'}
const findings={TOP_1_HIT:'首位命中',LOWER_RANK_HIT:'排序待改善',NOT_RETRIEVED:'候选池未命中',UNLABELED:'未标注',INVALID:'INVALID'}
const parse=async(fn)=>{error.value='';try{await fn()}catch(e){error.value=e.message || '请检查输入'}}
function addDocument(){documents.value.push({document_id:'doc_'+crypto.randomUUID().replaceAll('-',''),title:'',text:'',metadata:{}})}
function demo(){documents.value=structuredClone(demoDocuments);cases.value=JSON.stringify(demoCases,null,2);name.value='Demo · 电商知识检索';error.value=''}
function newBaseline(){const knowledge=state.knowledge;rag.reset();state.knowledge=knowledge;rag.persist();work.go('define')}
async function files(event){await parse(async()=>{const added=[];for(const f of event.target.files){if(!/\.(txt|md)$/i.test(f.name)||f.size>200000)throw new Error('仅支持不超过 200 KB 的 .txt / .md 文件。');added.push({document_id:'doc_'+crypto.randomUUID().replaceAll('-',''),title:f.name,text:await f.text(),metadata:{filename:f.name}})}if(documents.value.length===1 && !documents.value[0].text.trim() && !documents.value[0].title.trim())documents.value=added;else documents.value.push(...added)});event.target.value=''}
async function saveKnowledge(){await parse(()=>rag.saveKnowledge({name:name.value,documents:documents.value,
  ...(state.knowledge?{knowledge_dataset_id:state.knowledge.knowledge_dataset_id}:{})}))}
async function saveCases(){await parse(()=>rag.saveEvalset({name:name.value,cases:records(cases.value)}))}
async function propose(){const after={...state.baseline.run.retrieval_config};if(type.value==='TOP_K_CHANGE')after.top_k=nextK.value
  else if(type.value==='QUERY_REWRITE_TOGGLE')after.query_rewrite=!after.query_rewrite;else if(type.value==='RERANK_TOGGLE')after.rerank=!after.rerank
  await rag.propose({change_type:type.value,after_config:after,reason:`分析来源：${aiOrigin.value?'AI 草稿 '+aiOrigin.value+'，经用户核对':'用户填写'}\n证据与假设：${diagnosis.value}\n选择理由：${reason.value}\n备选方案：${alternatives.value}\n副作用：${risks.value}`,selected_case_ids:[selected.value],user_confirmed:confirmed.value,...(type.value==='KNOWLEDGE_UPDATE'?{target_index_id:state.index.index_id}:{})})}
function choose(id){selected.value=id;rag.state.preview=null;work.go('improve')}
const selectedAnswer=ref(null)
async function saveReview(){if(!selectedAnswer.value || !reviewReason.value.trim())return
  if(selectedAnswer.value.result.hard_rule_violations.length && reviewStatus.value==='PASS'&&!override.value)return
  await rag.review(selectedAnswer.value.runId,{case_id:selectedAnswer.value.result.case_id,human_final_status:reviewStatus.value,human_reason:reviewReason.value})
  selectedAnswer.value=null;reviewReason.value='';override.value=false}
</script>
<template>
  <div class="page-heading"><div><p class="eyebrow">RETRIEVAL EXPERIMENT</p><h1>{{step==='define'?'用你的知识，定义检索测试':step==='evaluate'?'找到没有命中的知识':step==='improve'?'依据问题，选择一个修改':'检索与回答，分别看变化'}}</h1><p>冻结每次运行的知识与题目，分别检验检索配置或知识更新。</p></div><span class="pill">RAG · 独立冻结索引</span></div>
  <p v-if="error" role="alert" class="note danger">{{error}}</p>
  <template v-if="step==='define'">
    <p class="note">先保存知识，再建立索引，最后标注每题应找到哪份知识。修改知识会生成新版本，需要重新建立 Baseline。</p>
    <section class="panel"><div class="section-heading"><h2>1. Knowledge · 知识</h2><button class="secondary" :disabled="!!work.state.busy || !!state.baseline" @click="demo">载入 Demo 知识与 8 道题</button></div>
      <p class="muted">Demo 政策仅用于流程演示，请用自己的业务知识替换。</p>
      <fieldset :disabled="!!work.state.busy || !!state.baseline">
        <label>检索实验名称<input v-model="name" required /></label>
        <label>上传知识文档（.txt / .md）<input type="file" accept=".txt,.md" multiple @change="files" /></label>
        <details v-for="(doc,i) in documents" :key="i" class="builder-card" :open="documents.length===1"><summary>{{doc.title || `知识文档 ${i+1}`}} · {{doc.document_id}}</summary>
          <div class="form-row"><label>文档 ID<input v-model="doc.document_id" required pattern="[A-Za-z0-9_-]+" /></label><label>知识标题<input v-model="doc.title" /></label></div>
          <label>知识正文<textarea v-model="doc.text" rows="5" required /></label><button class="text-button" @click="documents.splice(i,1)">移除文档</button>
        </details>
        <div class="button-row"><button class="secondary" @click="addDocument">＋ 添加知识</button><button class="primary" :disabled="!documents.length || documents.some(d=>!d.text.trim() || !d.document_id.trim())" @click="saveKnowledge">{{state.knowledge?'保存为新知识版本':'保存知识版本'}}</button></div>
      </fieldset>
      <div v-if="state.knowledge" class="note positive">已保存 {{state.knowledge.documents.length}} 份文档 · Version {{state.knowledge.version}}。历史版本保留。</div>
    </section>
    <section class="panel"><h2>2. 建立固定索引</h2><label>检索方式<select v-model="embeddingModel" :disabled="!!work.state.busy || !!state.baseline"><option :value="semanticModel">语义检索 · 原有 MiniLM 模型（默认）</option><option :value="lexicalModel">词汇检索 · 保留对照</option></select></label><p class="muted">默认使用原有 MiniLM 本地语义模型（384 维），无需额外 API Key。首次使用需下载；中文检索效果以实际测试为准。</p>
      <details class="advanced"><summary>切分设置</summary><div class="form-row"><label>Chunk 大小<input v-model.number="size" type="number" min="50" max="2000" :disabled="!!state.baseline" /></label><label>Chunk 重叠<input v-model.number="overlap" type="number" min="0" :disabled="!!state.baseline" /></label></div></details>
      <button class="primary" :disabled="!state.knowledge || !!work.state.busy || !!state.baseline" @click="rag.buildIndex({chunk_size:size,chunk_overlap:overlap},embeddingModel)">建立冻结索引</button>
      <p v-if="state.index" class="note positive">{{embeddingLabel(state.index)}} · 索引 READY · {{state.index.chunks.length}} 个 Chunk · 知识 Version {{state.index.knowledge_version}}</p><EvidenceDetails v-if="state.index" :data="state.index" title="Chunk / Embedding / Index 证据" />
    </section>
    <section class="panel"><h2>3. Retrieval EvalSet · 测试题</h2><p class="muted">每道题填写 query 和 relevant_document_ids 或 relevant_chunk_ids。标签由你确认，不由模型猜测。文档标签会对重复 Chunk 去重计分。</p>
      <label>检索测试题 JSON<textarea v-model="cases" rows="12" spellcheck="false" :disabled="!!state.baseline || !!work.state.busy" placeholder='[{"case_id":"01","query":"退款多久到账？","relevant_document_ids":["refund"]}]' /></label>
      <button class="primary" :disabled="!state.index || !cases.trim() || !!state.baseline || !!work.state.busy" @click="saveCases">保存检索测试，准备 Baseline →</button>
    </section>
    <p v-if="state.baseline" class="note warning">本实验知识和题目已冻结。要更新知识，请建立新 Baseline。</p><button v-if="state.baseline" class="secondary" :disabled="!!work.state.busy" @click="newBaseline">基于这份知识建立新 Baseline</button>
  </template>
  <template v-else-if="step==='evaluate'">
    <p v-if="!state.evalSet" class="empty">还没有检索测试题，请在 Define 中保存知识、索引与测试题。</p>
    <section v-else-if="!state.baseline" class="panel"><h2>第一次检索 · Baseline</h2><p class="muted">{{embeddingLabel(state.index)}}</p><p>{{state.evalSet.cases.length}} 道题 · {{state.knowledge.documents.length}} 份知识 · {{state.index.chunks.length}} 个 Chunk</p>
      <label>返回候选数量 Top K<input v-model.number="topK" type="number" min="1" max="20" /></label><div class="button-row"><label class="check"><input v-model="rewriting" type="checkbox" />Query Rewrite 开启</label><label class="check"><input v-model="reranking" type="checkbox" />Rerank 开启</label></div>
      <label class="check"><input v-model="answers" type="checkbox" />同时验证最终回答（会调用 Agent 和 Judge）</label><p class="muted">改写与重排失败会标记 INVALID，不会静默回退。检索缓存关闭；Answer 为单一知识客服 Agent，不含 Router / Memory。</p>
      <RunBriefing :session="work.state.session" :index="state.index" :cases="state.evalSet.cases" :config="{top_k:topK,query_rewrite:rewriting,rerank:reranking}" :verify-answers="answers" />
      <button class="primary" :disabled="!!work.state.busy || !!connectionBlocker" @click="rag.run('BASELINE',{top_k:topK,query_rewrite:rewriting,rerank:reranking},answers)">开始检索 Baseline</button>
      <div v-if="connectionBlocker" class="note warning" role="status"><p>{{connectionBlocker}}</p><div class="button-row"><button v-if="work.state.session?.credential_status==='PRESENT'" class="secondary" :disabled="!!work.state.busy" @click="work.testConnection">测试模型连接</button><button class="text-button" :disabled="!!work.state.busy" @click="work.go('setup')">去配置模型 →</button></div></div>
    </section>
    <template v-if="run">
      <div class="section-heading"><h2>{{run.run.run_type}} · {{run.run.status}}</h2><button v-if="state.retest" class="primary" :disabled="!!work.state.busy" @click="rag.compare">比较检索前后变化 →</button></div><label v-if="state.retest">查看哪次检索<select v-model="runSide"><option value="BASELINE">Baseline · 修改前</option><option value="RETEST">Retest · 修改后</option></select></label>
      <p class="muted">本次运行：{{embeddingLabel(run.run.controls.index_snapshot)}}</p>
      <section v-if="startingPoint" class="result-guidance" aria-label="结果分析引导"><p class="guide-kicker">下一步，先看这一处</p><h3>{{startingPoint.title}}</h3><p v-if="startingPoint.query" class="recommended-query">“{{startingPoint.query}}”</p><p>{{startingPoint.explanation}}</p><p v-if="!run.run.verify_answers" class="guide-tip">本次只评测了检索，没有运行最终回答和 Judge。</p><div class="button-row"><button v-if="startingPoint.caseId" class="primary" @click="inspectRecommended">查看这题的依据 ↓</button><button v-if="run.run.run_type==='BASELINE' && startingPoint.caseId && ['ANSWER','MISSING','OUTSIDE_K','LOWER_RANK'].includes(startingPoint.kind)" class="secondary" :disabled="!!work.state.busy" @click="choose(startingPoint.caseId)">基于这题记录修改 →</button><button v-if="startingPoint.kind==='UNLABELED'" class="secondary" @click="work.go('define')">回到测试题补标签 →</button><button v-if="startingPoint.kind==='INVALID'" class="secondary" @click="work.go('setup')">检查模型连接 →</button></div></section>
      <div class="rag-metric-grid"><section v-for="metric in metrics" :key="metric.id" class="metric-card"><div class="metric-heading"><small>{{metric.label}}</small><MetricHelp :metric="metric" /></div><strong>{{format(run.run.metrics[metric.id])}}</strong><small>{{run.run.metrics.denominators?.[metric.id] || 0}} 个有效标注 Case</small></section></div>
      <p class="note">已采集 {{run.run.metrics.acquired || 0}} / {{run.run.metrics.total || 0}} · 有效 {{run.run.metrics.valid || 0}} · INVALID {{run.run.metrics.invalid || 0}}。Hit@1 / Hit@3 / MRR 按固定候选池计分，Recall / Precision / NDCG 按返回 Top K 计分。</p>
      <section v-for="c in run.run.case_results" :key="c.case_id" class="panel rag-case" :data-testid="'retrieval-case-'+c.case_id" :id="'retrieval-case-'+c.case_id" tabindex="-1" :class="{'recommended-case':highlightedCase===c.case_id}"><div class="section-heading"><h3>{{c.query}}</h3><span class="pill">{{c.partition==='HOLDOUT'?'保留测试':'调试题'}}</span><StatusBadge :status="findings[c.retrieval_status] || '未完成'" /></div>
        <p>正确知识：{{[...c.relevant_document_ids,...c.relevant_chunk_ids].join('、') || '未标注'}} · 候选池 Rank = <strong>{{rank(c.metrics.relevant_rank)}}</strong> · {{c.metrics.returned_relevant_rank ? '返回 Top K 已命中' : '返回 Top K 未命中'}}</p>
        <p v-if="c.error" class="note danger">{{c.error}} · 无有效检索指标</p>
        <ol class="rag-results"><li v-for="r in c.results" :key="r.chunk_id"><strong>{{r.document_id}}</strong><p>{{r.text}}</p></li></ol>
        <details v-if="run.effective_answer_results.find(a=>a.case_id===c.case_id)" class="evidence"><summary>最终回答 · {{run.effective_answer_results.find(a=>a.case_id===c.case_id).final_status}}</summary><div v-for="a in run.effective_answer_results.filter(a=>a.case_id===c.case_id)" :key="a.case_id"><p>{{a.turn_evidence[0]?.response || '执行未完成'}}</p><p>{{a.original_reason}}</p><p>Machine: {{a.original_status}} · Human: {{a.human_final_status || '未复核'}}</p><button class="secondary" :disabled="a.execution_status!=='SUCCESS' || a.judge_status==='FAILED' || !!a.evaluation_error" @click="selectedAnswer={result:a,runId:run.run.run_id}">人工复核回答</button></div></details>
        <div class="button-row"><button v-if="run.run.run_type==='BASELINE'" class="secondary" :disabled="!!work.state.busy" @click="choose(c.case_id)">基于这题选择修改 →</button></div><TraceAssistant :run-id="run.run.run_id" :case-id="c.case_id" :can-suggest="run.run.run_type==='BASELINE'" @suggestion="useSuggestion" /><EvidenceDetails :data="c" title="检索原始轨迹" copyable />
      </section>
      <section v-if="selectedAnswer" class="panel"><h3>回答人工复核 · 原机器证据保留</h3><label>人工最终判定<select v-model="reviewStatus"><option>PASS</option><option>FAIL</option></select></label><label>回答复核理由<textarea v-model="reviewReason" rows="3" required /></label><label v-if="selectedAnswer.result.hard_rule_violations.length && reviewStatus==='PASS'" class="check"><input v-model="override" type="checkbox" />我确认人工覆盖 Hard Rule，违规证据保留</label><button class="primary" :disabled="!!work.state.busy || !reviewReason.trim() || (selectedAnswer.result.hard_rule_violations.length && reviewStatus==='PASS'&&!override)" @click="saveReview">保存回答复核</button></section>
      <EvidenceDetails :data="run" title="冻结 Run 证据" />
      <ExperimentHealth :view="run" />
    </template>
  </template>
  <template v-else-if="step==='improve'">
    <p v-if="!state.baseline" class="empty">先运行 Retrieval Baseline，再从结果选择问题。</p>
    <section v-else class="panel"><h2>记录你的单变量判断</h2><p v-if="aiOrigin" class="note">部分内容来自 AI 分析草稿 {{aiOrigin}}，尚未验证。请修改并填写自己的选择理由与备选方案，再确认应用。</p><p class="muted">先写事实，再写假设。例如“正确资料排第 6 位，Top K=3 没返回”是观察；“口语表达影响召回”是待验证假设。此示例不会自动填入你的判断。</p><label>观察的 Case<select v-model="selected"><option v-for="c in state.baseline.run.case_results" :key="c.case_id" :value="c.case_id">{{c.query}} · Rank {{rank(c.metrics.relevant_rank)}}</option></select></label>
      <p class="note">{{currentCase?.query}} · 正确知识 {{currentCase?.relevant_document_ids.join('、')}} · Rank {{rank(currentCase?.metrics.relevant_rank)}}</p>
      <fieldset :disabled="!!state.change || !!work.state.busy"><label>只修改一个变量<select v-model="type"><option value="TOP_K_CHANGE">返回候选数量 Top K</option><option value="QUERY_REWRITE_TOGGLE">Query Rewrite OFF / ON</option><option value="KNOWLEDGE_UPDATE">补充知识 · 保留原题与检索配置</option><option value="RERANK_TOGGLE">Rerank OFF / ON</option></select></label>
        <label v-if="type==='TOP_K_CHANGE'">新的 Top K<input v-model.number="nextK" type="number" min="1" max="20" /></label>
        <p v-else-if="type!=='KNOWLEDGE_UPDATE'">{{type==='QUERY_REWRITE_TOGGLE'?'Query Rewrite':'Rerank'}}：{{state.baseline.run.retrieval_config[type==='QUERY_REWRITE_TOGGLE'?'query_rewrite':'rerank']?'ON → OFF':'OFF → ON'}}</p>
        <p v-else class="note">初测知识 v{{state.baseline.run.controls.knowledge_snapshot.version}} → 当前知识 v{{state.index?.knowledge_version || '尚未建索引'}}。请先在“我的知识库”保存新版本并建立索引。原题、预期行为、切分方式与检索配置保持一致。</p>
        <button v-if="type==='QUERY_REWRITE_TOGGLE'" class="secondary" :disabled="work.state.session?.credential_status!=='PRESENT'" @click="rag.preview(currentCase.query)">预览模型查询改写</button>
        <div v-if="state.preview" class="note"><strong>模型预览 · 尚未应用</strong><p>Original：{{state.preview.original_query}}</p><p>Rewrite：{{state.preview.rewritten_query}}</p><small>正式 Run 会按冻结配置重新调用模型，保留实际改写结果。</small></div>
        <label>失败证据与根因假设<textarea v-model="diagnosis" rows="3" placeholder="引用具体题目和知识。根因在验证前仍是假设。" required /></label>
        <label>备选方案与取舍<textarea v-model="alternatives" rows="2" required /></label>
        <label>选择这个修改的理由<textarea v-model="reason" rows="3" required /></label>
        <label>可能副作用<textarea v-model="risks" rows="2" required /></label>
        <label class="check"><input v-model="confirmed" type="checkbox" />我确认这是我的产品判断，只修改上述一个变量</label>
        <button class="primary" :disabled="!confirmed || !reason.trim() || !diagnosis.trim() || !alternatives.trim() || !risks.trim() || !selected || (type==='KNOWLEDGE_UPDATE' && (!state.index || state.index.index_id===state.baseline.run.controls.index_snapshot.index_id))" @click="propose">确认并记录修改</button>
      </fieldset>
      <template v-if="state.change"><p v-if="state.change.implemented_status==='APPLIED' && !state.retest && !retestIndex" class="note warning">{{targetIndexError?'复测索引暂时无法读取，请同步状态后检查目标知识版本。':'正在读取已确认的复测索引…'}}</p><RunBriefing v-if="state.change.implemented_status==='APPLIED' && !state.retest && retestIndex" :session="{configuration:state.baseline.run.provider_configuration_snapshot}" :index="retestIndex" :cases="state.baseline.run.controls.eval_set_snapshot.cases" :config="state.change.after_config" :verify-answers="state.baseline.run.verify_answers" /><p class="note positive">{{state.change.change_type}} · {{state.change.implemented_status}}</p><p>{{state.change.reason}}</p><button v-if="state.change.implemented_status==='PROPOSED'" class="primary" :disabled="!!work.state.busy" @click="rag.apply">{{state.change.change_type==='KNOWLEDGE_UPDATE'?'Apply · 应用新知识索引':'Apply · 应用检索配置'}}</button><button v-else class="primary" :disabled="!!work.state.busy || !!state.retest || work.state.session?.credential_status!=='PRESENT'" @click="rag.run('RETEST',null,state.baseline.run.verify_answers)">运行检索 Retest →</button><EvidenceDetails :data="state.change" title="用户确认 / Declared / Observed Diff" /></template>
    </section>
  </template>
  <template v-else-if="step==='compare'">
    <p v-if="!state.comparison" class="empty">完成 Baseline 和 Retest 后生成比较。</p>
    <template v-else><section class="panel"><h2>{{state.comparison.comparable?'控制条件可比较':'控制条件不可比较'}} · {{state.comparison.comparison_completeness}}</h2><p class="note warning">这是一次观察。单次运行存在随机性，模型服务内部版本未知，不能自动归因或证明质量提升。</p><p v-if="state.comparison.comparison_completeness==='PARTIAL'">仅比较已完成有效的 Case pair，不能声称整套题库提升。</p><p v-if="state.comparison.comparability_reasons.length">{{state.comparison.comparability_reasons.join(' · ')}}</p></section>
      <div class="rag-metric-grid"><section v-for="metric in metrics" :key="metric.id" class="metric-card"><div class="metric-heading"><small>{{metric.label}} · 有效匹配题</small><MetricHelp :metric="metric" /></div><strong>{{format(state.comparison.paired_metrics.baseline[metric.id])}} → {{format(state.comparison.paired_metrics.retest[metric.id])}}</strong><small>分母 {{state.comparison.paired_metrics.baseline.denominators[metric.id]}}</small></section></div>
      <section v-for="p in orderedPairs" :key="p.case_id" class="panel rag-case"><div class="section-heading"><h3>{{p.query}}</h3><strong>{{labels[p.transition]}}</strong></div><p>正确知识 Rank：{{rank(p.baseline?.metrics.relevant_rank)}} → {{rank(p.retest?.metrics.relevant_rank)}}</p><p>Top K：{{p.baseline?.top_k || '缺失'}} → {{p.retest?.top_k || '缺失'}}</p><p v-if="p.reason">{{p.reason}}</p>
        <div class="two-column"><div><h4>Baseline 知识</h4><ol class="rag-results"><li v-for="r in p.baseline?.results" :key="r.chunk_id">{{r.document_id}}<p>{{r.text}}</p></li></ol></div><div><h4>Retest 知识</h4><ol class="rag-results"><li v-for="r in p.retest?.results" :key="r.chunk_id">{{r.document_id}}<p>{{r.text}}</p></li></ol></div></div>
        <details v-if="p.baseline_answer || p.retest_answer" class="evidence"><summary>回答变化 · {{p.answer_transition}}</summary><div class="two-column"><div><h4>Baseline · {{p.baseline_answer?.final_status}}</h4><p>{{p.baseline_answer?.turn_evidence[0]?.response}}</p><p>{{p.baseline_answer?.original_reason}}</p></div><div><h4>Retest · {{p.retest_answer?.final_status}}</h4><p>{{p.retest_answer?.turn_evidence[0]?.response}}</p><p>{{p.retest_answer?.original_reason}}</p></div></div><p class="note">检索改善不自动等于回答改善。回答按相关性、准确性、完整性、帮助性及禁止行为检查，判定仍需复核。</p></details>
      <TraceAssistant :comparison-id="state.comparison.comparison_id" :case-id="p.case_id" /></section><section class="panel"><h2>下一步，怎样处理这次修改？</h2><label>我的决定<select v-model="conclusion"><option value="KEEP">保留修改</option><option value="REVISE">继续调整</option><option value="REVERT">采用初测版本</option></select></label><label>结果解释与取舍<textarea v-model="conclusionReason" rows="3" placeholder="解释改善、退化和证据局限，说明为什么作出这个决定。" /></label><label class="check"><input type="checkbox" v-model="conclusionConfirmed" />我确认这是本人判断，当前结果的局限仍然保留</label><button class="primary" :disabled="!conclusionReason.trim() || !conclusionConfirmed || !!work.state.busy" @click="practice.conclude(state.comparison.comparison_id,{decision:conclusion,reason:conclusionReason,user_confirmed:true})">保存实验结论</button><p v-for="c in practice.state.conclusions" :key="c.conclusion_id">{{c.decision}}：{{c.reason}}</p><div class="button-row"><button class="secondary" @click="practice.newChat();practice.state.chatSource=conclusion==='REVERT'?'baseline':'retest';work.go('chat')">回到聊天验证体验 →</button><button class="secondary" @click="work.go('career')">整理项目与求职材料 →</button></div></section><EvidenceDetails :data="state.comparison" title="完整检索比较证据" />
    </template>
  </template>
</template>
