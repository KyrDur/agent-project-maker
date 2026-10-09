<script setup>
import { cloneArtifact } from '../practice-data.js'
import { computed, inject, ref } from 'vue'
import { demoCases } from '../rag-demo.js'
import TestGenerator from '../components/TestGenerator.vue'
import {appendGeneratedCases} from '../ai-assistance.js'
const work=inject('workspace'),rag=inject('retrieval'),practice=inject('practice'),error=ref(''),confirmed=ref(false)
const name=ref(rag.state.evalSet?.name || '我的电商 Agent 测试')
const cases=ref(cloneArtifact(rag.state.evalSet?.cases || []).map(c=>({...c,partition:c.partition||'DEBUG'})))
for(const draft of practice.state.drafts)if(!cases.value.some(c=>c.case_id===draft.case_id))cases.value.push(cloneArtifact(draft))
const form=computed(()=>cases.value.map(c=>({...c,partition:c.partition||'DEBUG',relevant_document_ids:c.relevant_document_ids||[],must_do:c.must_do||[],must_not_do:c.must_not_do||[]})))
const changed=()=>{confirmed.value=false}
function add(){cases.value.push({case_id:'case_'+crypto.randomUUID(),query:'',expected_answer:'',relevant_document_ids:[],must_do:[],must_not_do:[],source:'user_created',partition:'DEBUG'});changed()}
function demo(){cases.value=cloneArtifact(demoCases).map(c=>({...c,partition:'DEBUG',must_not_do:['不能声称真实退款、订单操作已完成']}));changed()}
function edge(){const extras=[
 ['custom','定制商品拆封了，还能七天无理由退货吗？','opened','说明定制商品不适用该无理由政策，不承诺退款。'],
 ['missing','我想退货，直接帮我退吧。','opened','先核验订单号和商品状态，不声称已经执行退款。'],
 ['late_address','包裹已经揽收了，能保证改地址成功吗？','address','需核验拦截可能性，不能保证修改成功。'],
 ['unknown','这个商品能配送到火星吗？',null,'知识不足，说明无法确认，不编造配送范围。']]
 for(const [id,query,doc,expected_answer] of extras)if(!cases.value.some(c=>c.case_id==='edge_'+id))cases.value.push({case_id:'edge_'+id,query,expected_answer,relevant_document_ids:doc?[doc]:[],source:'demo',partition:'HOLDOUT',must_not_do:['不得编造政策和已执行状态']});changed()
}
async function save(){error.value='';if(!confirmed.value)return
 try{const rows=cases.value.map(c=>({...c,query:c.query.trim(),expected_answer:c.expected_answer?.trim() || null}))
  if(rows.some(c=>!c.query || (!c.expected_answer && !(c.must_do||[]).length)))throw new Error('每道题需要问题和明确的预期行为。')
  if(new Set(rows.map(c=>c.case_id)).size!==rows.length)throw new Error('题目 ID 重复。')
  await rag.saveEvalset({name:name.value,cases:rows,...(rag.state.evalSet?{retrieval_eval_set_id:rag.state.evalSet.retrieval_eval_set_id}:{})})
  if(!work.state.error){practice.state.drafts=[];practice.persist()}
 }catch(e){error.value=e.message}
}
const lineArray=s=>s.split('\n').map(v=>v.trim()).filter(Boolean)
function adoptGenerated(draft){try{cases.value=appendGeneratedCases(cases.value,draft.cases,rag.state.index?.index_id,draft.index_id);changed();work.state.notice='已追加 AI 测试草稿，已有题保留。请检查并保存测试。'}catch(e){error.value=e.message}}
</script>
<template>
 <div class="page-heading"><div><p class="eyebrow">定义目标与测试</p><h1>先说明，怎样才算答得对。</h1><p>从真实对话或业务问题建立测试，分别保留调试题与保留测试。</p></div></div>
 <p v-if="error" class="note danger" role="alert">{{error}}</p><div v-if="!rag.state.index" class="note warning">请先保存知识并建立索引。<button class="secondary" @click="work.go('knowledge')">准备知识库 →</button></div>
 <TestGenerator @adopt="adoptGenerated" />
 <section class="panel"><div class="section-heading"><h2>测试题 · {{cases.length}} 道</h2><div class="button-row"><button class="secondary" :disabled="!!work.state.busy" @click="demo">载入 8 道 Demo 题</button><button class="secondary" :disabled="!!work.state.busy" @click="edge">补充 4 道边界题</button></div></div><p class="muted">Demo 题只适用于对应 Demo 政策。保留题用于检查未参与调参的问题；一旦用于选方案，请改为调试题。</p>
  <label>实验名称<input v-model="name" @input="changed" /></label>
  <details class="test-writing-help"><summary>不知道怎样写测试标准？看一个例子</summary><p>问题：包装拆开了还能退吗？</p><p>先找到你的实际退货政策，再写明应说明的条件、需要追问的信息与禁止承诺。相关知识 ID 填这份政策的文档 ID。不要直接复制 Agent 的回答作为正确答案。</p><p>同一事实只写一次；需要新知识才能回答的题勾选“知识缺失测试”。用于调整方案的题保留为调试用途。</p></details>
  <fieldset :disabled="!!work.state.busy"><article v-for="(c,i) in cases" :key="c.case_id" class="builder-card"><div class="section-heading"><h3>问题 {{i+1}} <small v-if="c.source==='ai_generated'">AI 生成</small></h3><button class="text-button" @click="cases.splice(i,1);changed()">移除</button></div>
   <div class="form-row"><label>题目 ID<input v-model="c.case_id" @input="changed" /></label><label>用途<select v-model="c.partition" @change="changed"><option value="DEBUG">调试题</option><option value="HOLDOUT">保留测试</option></select></label></div><label>用户问题<textarea v-model="c.query" rows="2" @input="changed" /></label><label>预期回答与依据<textarea v-model="c.expected_answer" placeholder="例如：说明包装、二次销售等适用条件；先核验订单与状态，不承诺退款已完成。请以实际资料为准。" rows="3" @input="changed" /></label>
   <label>相关知识 ID（逗号分隔；无相关知识可留空）<input :value="(c.relevant_document_ids||[]).join(', ')" @input="c.relevant_document_ids=$event.target.value.split(/[,，、\s]+/).filter(Boolean);changed()" /></label>
   <div class="form-row"><label>必须做到（每行一项）<textarea :value="(c.must_do||[]).join('\n')" rows="2" @input="c.must_do=lineArray($event.target.value);changed()" /></label><label>不能做（每行一项）<textarea :value="(c.must_not_do||[]).join('\n')" rows="2" @input="c.must_not_do=lineArray($event.target.value);changed()" /></label></div>
   <label class="check"><input type="checkbox" v-model="c.allow_missing_knowledge" @change="changed" />这是知识缺失测试，允许期望文档尚未加入知识库</label><details v-if="c.context?.length"><summary>原始对话上下文 · {{c.context.length}} 条</summary><p v-for="(m,j) in c.context" :key="j">{{m.role}}：{{m.content}}</p></details><details v-if="c.generation?.source_quotes?.length"><summary>AI 生成原始依据 · 知识 v{{c.generation.knowledge_version}}</summary><p v-for="(q,j) in c.generation.source_quotes" :key="j">{{q.document_id}}：{{q.quote}}</p><p class="muted">生成记录 {{c.generation.draft_id}}。此处保留生成时的引用；编辑后的标准仍需人工核对。</p></details><small v-if="c.source_chat_turn_id">来源：{{c.source_chat_turn_id}}</small>
  </article><button class="secondary" @click="add">＋ 添加测试题</button></fieldset>
  <p>调试题 {{form.filter(c=>c.partition==='DEBUG').length}} · 保留测试 {{form.filter(c=>c.partition==='HOLDOUT').length}}</p><p v-if="rag.state.baseline" class="note">保存修改后的题目会建立新的初测起点，历史实验保持原样。知识补充实验请从“判断与修改”进入，以保留原题。</p><label class="check"><input v-model="confirmed" type="checkbox" />我已检查标签与预期行为，确认评分依据</label><button class="primary" :disabled="!rag.state.index || !cases.length || !confirmed || !!work.state.busy" @click="save">保存测试，准备初测 →</button>
 </section>
</template>
