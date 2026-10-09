<script setup>
import {computed,inject} from 'vue'
import {api} from '../api.js'
import {copy,questionTypes,estimateTestCalls} from '../ai-assistance.js'
import AssistModel from './AssistModel.vue'
const emit=defineEmits(['adopt']),work=inject('workspace'),rag=inject('retrieval'),ai=inject('ai'),s=ai.tests
const sid=computed(()=>ai.modelSession||work.state.session?.provider_session_id)
const stale=computed(()=>s.draft && s.draft.content.index_id!==rag.state.index?.index_id)
const selected=computed(()=>s.cases.filter(c=>s.selected.includes(c.case_id)))
async function generate(){await work.action('AI 根据冻结知识出题',async()=>{
 const draft=await api.post('/ai/tests',{request_id:crypto.randomUUID(),provider_session_id:sid.value,index_id:rag.state.index.index_id,count:s.count,question_types:s.types})
 s.draft=draft;s.cases=copy(draft.content.cases);s.selected=s.cases.map(c=>c.case_id);s.confirmed=false
})}
function adopt(){emit('adopt',{cases:copy(selected.value),index_id:s.draft.content.index_id});s.confirmed=false}
</script>
<template><section class="panel ai-panel" aria-label="AI 生成测试题"><h2>根据知识，AI 帮你出题。</h2><p>生成问题、预期行为与原文依据。确认后追加到下方测试编辑区，不覆盖现有题。</p><fieldset :disabled="!!work.state.busy"><div class="form-row"><label>生成题数<select v-model.number="s.count"><option :value="4">4 道</option><option :value="8">8 道</option><option :value="12">12 道</option></select></label><p class="muted">当前知识 v{{rag.state.index?.knowledge_version || '尚未建立'}} · 按所选冻结索引出题</p></div><div class="button-row"><label class="check" v-for="type in questionTypes" :key="type"><input type="checkbox" v-model="s.types" :value="type" />{{type}}</label></div><AssistModel/><p class="call-estimate">预计 {{estimateTestCalls(s.count)}} 次远程请求 · 每批最多 4 题 · 发送当前版本的完整知识正文，不发送 Agent 回答。每次输出上限 4096 Token。</p><button class="primary" :disabled="!sid || !rag.state.index || !s.types.length" @click="generate">{{s.draft?'生成新一批草稿':'AI 生成测试草稿'}}</button></fieldset>
 <div v-if="s.draft" class="ai-draft"><p class="note">{{s.cases.length}} 道 AI 生成草稿 · 知识 v{{s.draft.content.knowledge_version}} · {{s.draft.provider_call_count}} 次实际请求。默认用于调试，不代表独立盲测。</p><p v-if="stale" class="note warning">当前索引与出题来源不同，请按当前知识重新生成。</p><fieldset :disabled="!!work.state.busy" @input="s.confirmed=false"><div class="button-row"><button class="secondary" @click="s.selected=s.cases.map(c=>c.case_id);s.confirmed=false">全选</button><button class="secondary" @click="s.selected=[];s.confirmed=false">取消全选</button></div><article class="builder-card" v-for="c in s.cases" :key="c.case_id"><label class="check"><input type="checkbox" v-model="s.selected" :value="c.case_id" />{{c.generation.question_type}} · {{c.query}}</label><details><summary>检查预期行为与原文依据</summary><label>问题<textarea v-model="c.query" rows="2" /></label><label>预期回答<textarea v-model="c.expected_answer" rows="3" /></label><p>必须做到：{{c.must_do.join('；')}}</p><p>不能做：{{c.must_not_do.join('；')}}</p><blockquote v-for="(q,i) in c.generation.source_quotes" :key="i">{{q.document_id}}：{{q.quote}}</blockquote><p v-if="!c.generation.source_quotes.length" class="muted">知识范围外题：预期明确资料不足，不编造。</p></details></article></fieldset><label class="check"><input type="checkbox" v-model="s.confirmed" />我已核对选中题的标准与依据</label><button class="primary" :disabled="!s.confirmed || stale || !selected.length || !!work.state.busy" @click="adopt">确认并追加 {{selected.length}} 道题</button></div></section></template>
