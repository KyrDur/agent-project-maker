<script setup>
import {computed,inject} from 'vue'
import {api} from '../api.js'
const work=inject('workspace'),ai=inject('ai')
const session=computed(()=>ai.modelSession?ai.providerOptions.find(s=>s.provider_session_id===ai.modelSession):work.state.session)
async function load(){await work.action('读取已连接模型',async()=>{ai.providerOptions=await api.get('/ai/provider-options')})}
</script>
<template><div class="assist-model"><p class="muted">生成／解读模型：{{session?.configuration.role_overrides?.general?.model || session?.configuration.model || '尚未配置'}} · {{session?.configuration.base_url || '先到 Setup 连接模型'}}</p><details><summary @click="load">选择其他已连接模型（可选）</summary><label>生成与解读使用的会话<select v-model="ai.modelSession"><option value="">沿用当前回答模型</option><option v-for="s in ai.providerOptions.filter(s=>s.credential_status==='PRESENT'&&s.text_connection_status==='READY')" :key="s.provider_session_id" :value="s.provider_session_id">{{s.configuration.model}} · {{s.configuration.base_url}} · {{s.provider_session_id.slice(0,8)}}</option></select></label><p class="muted">独立服务可在 Setup 保存并测试连接后选用。这里只影响生成与解读，不改变已冻结的实验模型。</p></details></div></template>
