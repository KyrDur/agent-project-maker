<script setup>
import {computed,inject,reactive,ref} from 'vue'
import {api,ApiError} from '../api.js'
import {modelPresets,presetConfig} from '../model-presets.js'
const work=inject('workspace'),ai=inject('ai'),preset=ref('deepseek'),key=ref(''),saved=ref(null),target=ref('')
const config=reactive({...presetConfig('deepseek'),temperature:0,max_tokens:1024,timeout_seconds:60,max_calls:100})
const binding=computed(()=>work.state.session?.configuration.judge_provider_session_id)
function change(){Object.assign(config,presetConfig(preset.value));key.value='';saved.value=null}
async function load(){await work.action('读取 Judge 会话',async()=>{ai.providerOptions=await api.get('/ai/provider-options')})}
async function connect(){await work.action('保存并测试独立 Judge',async()=>{
 try{saved.value=await api.post('/provider-sessions',{...config,api_key:key.value})}finally{key.value=''}
 const r=await api.post(`/provider-sessions/${saved.value.provider_session_id}/test`)
 saved.value=await api.get('/provider-sessions/'+saved.value.provider_session_id)
 if(r.status!=='SUCCESS')throw new ApiError(r.status,409)
 target.value=saved.value.provider_session_id;ai.providerOptions=await api.get('/ai/provider-options');work.state.notice='独立 Judge 文本连接成功，可以绑定到当前回答会话。'
})}
async function bind(id){await work.action(id?'绑定独立 Judge':'恢复沿用当前 Judge',async()=>{
 const session=await api.post(`/provider-sessions/${work.state.session.provider_session_id}/judge`,{judge_provider_session_id:id||null})
 work.state.session=session
 const result=await api.post(`/provider-sessions/${session.provider_session_id}/test`)
 work.state.session=await api.get('/provider-sessions/'+session.provider_session_id)
 if(result.status!=='SUCCESS')throw new ApiError(result.status,409)
 work.state.notice='新模型会话已验证。历史实验保持原配置；请用新配置建立新的初测。'
})}
</script>
<template><section class="panel" aria-label="独立 Judge 配置"><h2>Judge 可以使用另一套模型连接</h2><p class="muted">默认沿用当前会话的 Judge 模型。独立 Judge 有自己的地址、模型与 Key；不同模型是否判得更准，需要人工对照验证。</p><p v-if="binding" class="note positive">已绑定 {{work.state.session.configuration.judge_provider_configuration.model}} · {{work.state.session.configuration.judge_provider_configuration.base_url}}</p><details><summary @click="load">配置独立 Judge（可选）</summary><fieldset :disabled="!!work.state.busy"><label>Judge 模型服务<select v-model="preset" @change="change"><option v-for="p in modelPresets" :key="p.id" :value="p.id">{{p.label}}</option></select></label><label>Judge 接口协议<select v-model="config.provider" @change="config.thinking_mode=null"><option value="openai-compatible">OpenAI 兼容</option><option value="anthropic-compatible">Anthropic 兼容</option></select></label><label>Judge Base URL<input v-model="config.base_url" type="url" /></label><label>Judge Model<input v-model="config.model" /></label><label>Judge API Key<input type="password" v-model="key" autocomplete="off" placeholder="只保留在后端内存" /></label><div class="form-row"><label>Judge 超时（秒）<input type="number" v-model.number="config.timeout_seconds" min="1" max="120" /></label><label>Judge 输出上限<input type="number" v-model.number="config.max_tokens" min="1" max="4096" /></label></div><button class="secondary" :disabled="!key.trim() || !config.model.trim() || !config.base_url" @click="connect">保存并测试独立 Judge · 预计 1 次请求</button><p v-if="saved" class="muted">Judge 会话：{{saved.text_connection_status}} · 凭据 {{saved.credential_status}}</p><label>选择已连接的 Judge 会话<select v-model="target"><option value="">请选择</option><option v-for="s in ai.providerOptions.filter(s=>s.credential_status==='PRESENT'&&s.text_connection_status==='READY'&&!s.configuration.judge_provider_session_id)" :key="s.provider_session_id" :value="s.provider_session_id">{{s.configuration.model}} · {{s.configuration.base_url}} · {{s.provider_session_id.slice(0,8)}}</option></select></label><button class="primary" :disabled="!target || !work.state.session || work.state.session.credential_status!=='PRESENT'" @click="bind(target)">绑定并测试新会话</button><button v-if="binding" class="secondary" @click="bind(null)">恢复沿用当前模型</button><p class="muted">绑定会创建新会话并测试各不同模型连接，至少 2 次请求，不改变旧实验。回答与 Judge 的正式调用合并计入当前实验预算。</p></fieldset></details></section></template>
