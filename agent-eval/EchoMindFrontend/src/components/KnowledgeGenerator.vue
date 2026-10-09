<script setup>
import {inject,computed} from 'vue'
import {api} from '../api.js'
import {copy} from '../ai-assistance.js'
import AssistModel from './AssistModel.vue'
const emit=defineEmits(['adopt']),work=inject('workspace'),ai=inject('ai'),s=ai.knowledge
const selected=computed(()=>s.documents.filter(d=>s.selected.includes(d.document_id)))
const sid=computed(()=>ai.modelSession||work.state.session?.provider_session_id)
async function generate(category=null){await work.action(category?'重新生成一类知识':'AI 生成完整知识库',async()=>{
 const draft=await api.post('/ai/knowledge',{request_id:crypto.randomUUID(),provider_session_id:sid.value,scenario:s.scenario,facts:s.facts})
 if(category){const d=draft.content.documents.find(d=>d.metadata.category===category),at=s.documents.findIndex(d=>d.metadata.category===category);s.documents[at]=copy(d);s.selected=s.documents.map(d=>d.document_id)}
 else {s.draft=draft;s.documents=copy(draft.content.documents);s.name=draft.content.name;s.selected=s.documents.map(d=>d.document_id)}
 s.confirmed=false
})}
function adopt(){emit('adopt',{name:s.name,documents:copy(selected.value),generation_id:s.draft.draft_id});s.confirmed=false}
</script>
<template><section class="panel ai-panel" aria-label="AI 生成知识库"><p class="eyebrow">站内 AI 助手</p><h2>描述场景，生成完整知识库。</h2><p>不用先准备资料。AI 会生成商品、配送、退换货、退款、保修、发票、账户及积分八类模拟知识。</p><fieldset :disabled="!!work.state.busy"><label>电商场景<textarea v-model="s.scenario" rows="2" maxlength="1500" placeholder="例如：一家销售耳机和音箱的电商，面向国内消费者。" /></label><label>已有事实或规则（可选，优先保留）<textarea v-model="s.facts" rows="2" maxlength="12000" placeholder="例如：品牌名、商品特点、已有售后政策；没有提供的规则将作为模拟设定。" /></label><AssistModel/><p class="call-estimate">预计 1 次远程请求 · 发送上述场景与规则 · 输出上限 4096 Token，费用以服务商账单为准。</p><button class="primary" :disabled="!sid || s.scenario.trim().length<5" @click="generate()">{{s.draft?'重新生成整套草稿':'AI 生成知识库'}}</button><button class="text-button" v-if="!sid" @click="work.go('setup')">先连接模型 →</button></fieldset>
 <div v-if="s.draft" class="ai-draft"><p class="note">AI 生成的模拟业务知识 · 尚未保存。核对规则一致性后，用选中条目替换当前未保存的编辑内容；已有知识版本保持原样。</p><fieldset :disabled="!!work.state.busy" @input="s.confirmed=false"><label>生成的知识库名称<input v-model="s.name" maxlength="150" /></label><div class="button-row"><button class="secondary" @click="s.selected=s.documents.map(d=>d.document_id);s.confirmed=false">全选</button><button class="secondary" @click="s.selected=[];s.confirmed=false">取消全选</button></div><article v-for="d in s.documents" :key="d.document_id" class="builder-card"><div class="section-heading"><label class="check"><input type="checkbox" v-model="s.selected" :value="d.document_id" />{{d.metadata.category}} · {{d.title}}</label><button class="text-button" @click="generate(d.metadata.category)">重生成此类</button></div><details><summary>查看与编辑 · {{d.document_id}}</summary><label>标题<input v-model="d.title" maxlength="200" /></label><label>正文、适用条件与例外<textarea v-model="d.text" rows="5" /></label><p class="muted">来源：AI 模拟设定 · 生成记录 {{d.metadata.generation_id}}</p></details></article></fieldset><label class="check"><input type="checkbox" v-model="s.confirmed" />我已核对选中的模拟规则，确认带入编辑区</label><button class="primary" :disabled="!s.confirmed || !selected.length || selected.some(d=>!d.text.trim()) || !!work.state.busy" @click="adopt">确认，用选中 {{selected.length}} 条替换编辑区</button><p class="muted">随后点击保存为新版本，再建立索引。此类重生成仍请求整套八类草稿，仅替换这一类，预计 1 次请求。原生成记录保留。</p></div></section></template>
