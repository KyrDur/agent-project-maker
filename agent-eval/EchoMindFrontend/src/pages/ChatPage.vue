<script setup>
import { embeddingLabel } from '../embedding-models.js'
import { computed, inject, ref } from 'vue'
const work=inject('workspace'),rag=inject('retrieval'),practice=inject('practice')
const message=ref(''),source=ref(practice.state.chatSource || 'current'),selected=ref(null),expected=ref(''),labels=ref(''),required=ref(''),forbidden=ref(''),confirmed=ref(false),partition=ref('DEBUG')
const context=computed(()=>{
  const run=source.value==='baseline'?rag.state.baseline?.run:source.value==='retest'?rag.state.retest?.run:null
  if(run)return {index:run.controls.index_snapshot,index_id:run.controls.index_snapshot.index_id,version:run.controls.knowledge_snapshot.version,
    name:run.controls.knowledge_snapshot.name,config:run.retrieval_config}
  const current=rag.state.index
  const matching=[rag.state.retest?.run,rag.state.baseline?.run].find(r=>r?.controls.index_snapshot.index_id===current?.index_id)
  return {index:current,index_id:current?.index_id,version:current?.knowledge_version,name:rag.state.knowledge?.name,
    config:matching?.retrieval_config || {top_k:3,query_rewrite:false,rerank:false}}
})
const configured=computed(()=>context.value.index_id && work.state.session?.credential_status==='PRESENT' && work.state.session?.text_connection_status==='READY')
const matchesConversation=computed(()=>{
 const first=practice.state.turns[0];if(!first)return true
 return first.index_id===context.value.index_id && first.provider_session_id===work.state.session?.provider_session_id && ['top_k','query_rewrite','rerank','candidate_pool_size'].every(k=>first.retrieval_config[k]===(context.value.config[k]??{candidate_pool_size:20}[k]))
})
const ready=computed(()=>configured.value && matchesConversation.value)
function selectSource(){practice.newChat();selected.value=null}
async function send(){if(!message.value.trim() || !ready.value)return
  const result=await practice.send({index_id:context.value.index_id,message:message.value.trim(),retrieval_config:context.value.config})
  if(result)message.value=''
}
function makeTest(turn){selected.value=turn;expected.value='';labels.value='';required.value='';forbidden.value='';confirmed.value=false}
const lines=text=>text.split('\n').map(s=>s.trim()).filter(Boolean)
async function saveTest(){await practice.draft(selected.value.turn_id,{expected_answer:expected.value.trim(),
  relevant_document_ids:labels.value.split(/[,，、\s]+/).filter(Boolean),must_do:lines(required.value),must_not_do:lines(forbidden.value),partition:partition.value,confirmed:confirmed.value})}
const samples=['拆了还能退吗？','钱什么时候回到卡里？','包裹咋还没动？','报销的凭证怎么弄？']
</script>
<template>
 <div class="page-heading"><div><p class="eyebrow">体验电商 Agent</p><h1>先聊一聊，再发现问题。</h1><p>根据你选用的知识回答。发现问题后，把真实对话转成测试。</p></div><button class="secondary" :disabled="!!work.state.busy" @click="selectSource">新对话</button></div>
 <section class="panel chat-config"><label>体验哪个版本<select v-model="source" :disabled="!!work.state.busy" @change="selectSource"><option value="current">当前知识库</option><option v-if="rag.state.baseline" value="baseline">初测的知识与配置</option><option v-if="rag.state.retest" value="retest">复测的知识与配置</option></select></label>
  <p v-if="context.index_id">{{context.name}} · 知识 v{{context.version}} · 返回 {{context.config.top_k}} 条 · 查询改写{{context.config.query_rewrite?'开启':'关闭'}} · 重排{{context.config.rerank?'开启':'关闭'}}</p>
  <p class="muted">每段对话固定知识与配置；保留最近 5 次成功问答作为上下文。Demo 政策用于练习，不代表真实商家承诺。</p>
  <p v-if="!matchesConversation" class="note warning">这段历史对话使用原来的模型会话、知识与配置。继续发问前，请点击“新对话”，使用上方所选版本。</p>
  <div v-if="!configured" class="note warning">开始前，请完成模型连接和知识索引。<div class="button-row"><button class="secondary" @click="work.go('setup')">配置自己的 API</button><button class="secondary" @click="work.go('knowledge')">准备知识库</button></div></div>
 </section>
 <p v-if="context.index" class="note">当前检索：{{embeddingLabel(context.index)}}。切换索引后请开启新对话。</p>
 <section class="panel chat-panel" aria-label="聊天记录">
  <div v-if="!practice.state.turns.length" class="chat-empty"><h2>你想问什么？</h2><p>可以从示例开始，也可以问知识库范围内的其他问题。</p><div class="button-row"><button v-for="s in samples" :key="s" class="secondary" @click="message=s">{{s}}</button></div></div>
  <article v-for="turn in practice.state.turns" :key="turn.turn_id" class="chat-turn">
   <div class="chat-user"><small>你</small><p>{{turn.message}}</p></div>
   <div class="chat-agent"><small>电商 Agent · 知识 v{{turn.knowledge_version}}</small><p class="preserve-lines" v-if="turn.status==='SUCCESS'">{{turn.answer}}</p><p v-else class="note danger">回答未完成：{{turn.error}}。本次未产生有效答案。</p>
    <details v-if="turn.retrieval.results.length"><summary>引用与检索依据 · {{turn.citations.length}} 个引用片段</summary><p v-if="!turn.citations.length" class="muted">回答未明确引用文档 ID。以下为实际检索候选，不代表答案已使用或已核验。</p><div v-for="r in turn.retrieval.results" :key="r.chunk_id" class="builder-card"><strong>{{r.document_id}}</strong><span class="pill">{{turn.citations.some(c=>c.chunk_id===r.chunk_id)?'回答引用':'检索候选'}}</span><p>{{r.text}}</p></div><p class="muted">{{(turn.latency_ms/1000).toFixed(1)}} 秒 · {{turn.provider_call_count}} 次模型调用 · {{turn.turn_id}}</p></details>
    <div class="button-row" v-if="turn.status==='SUCCESS'"><button class="secondary" :disabled="!!work.state.busy" @click="makeTest(turn)">有问题，加入测试</button><button class="text-button" :disabled="!!work.state.busy" @click="makeTest(turn)">值得保留，加入回归测试</button><button class="text-button" @click="work.go('knowledge')">补充相关知识</button></div>
   </div>
  </article>
  <form @submit.prevent="send" class="chat-composer"><label>你的问题<textarea v-model="message" rows="3" maxlength="5000" placeholder="例如：包装拆了，但是商品没用过，可以退吗？" :disabled="!!work.state.busy" /></label><button class="primary" :disabled="!ready || !message.trim() || !!work.state.busy">{{work.state.busy?'正在处理…':'发送问题 →'}}</button></form>
 </section>
 <section v-if="selected" class="panel"><h2>确认这道题的预期行为</h2><p>{{selected.message}}</p><p class="muted">原回答与上下文会保留为来源。正确标准由你确认，系统不会把原回答当作标准答案。</p>
  <label>预期回答或验收标准<textarea v-model="expected" rows="3" placeholder="说明应该回答什么，以及依据哪条政策。" /></label><label>相关文档 ID（逗号分隔，可填写待补充的文档 ID）<input v-model="labels" placeholder="如 opened" /></label>
  <div class="form-row"><label>必须做到（每行一项）<textarea v-model="required" rows="3" /></label><label>不能做（每行一项）<textarea v-model="forbidden" rows="3" /></label></div>
  <label>题目用途<select v-model="partition"><option value="DEBUG">调试题 · 用于分析与修改</option><option value="HOLDOUT">保留测试 · 暂不用于调参</option></select></label><p class="muted">已经查看或用于修改的题应归入调试题；保留题一旦用于调参，请调整用途。</p>
  <label class="check"><input v-model="confirmed" type="checkbox" />我确认以上是有依据的预期行为</label><button class="primary" :disabled="(!expected.trim() && !required.trim()) || !confirmed || !!work.state.busy" @click="saveTest">加入测试草稿 →</button>
 </section>
</template>
