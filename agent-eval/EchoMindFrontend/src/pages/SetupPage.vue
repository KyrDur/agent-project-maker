<script setup>
import { computed, inject, reactive, ref, watch } from 'vue'
import { modelPresets, presetConfig, identifyPreset } from '../model-presets.js'
import { toolStates } from '../presentation'
import EvidenceDetails from '../components/EvidenceDetails.vue'
import IndependentJudge from '../components/IndependentJudge.vue'
const work = inject('workspace'), { state } = work
const anonymousWorkspace = inject('anonymousWorkspace', ref(false))
const experimentMode=inject('experimentMode'), rag=inject('retrieval')
const isRetrieval=computed(()=>experimentMode?.value==='RETRIEVAL')
const activeBaseline=computed(()=>isRetrieval.value?rag?.state.baseline:state.baseline)
const config = reactive({ ...presetConfig('deepseek'), temperature: 0,
  max_tokens: 1024, timeout_seconds: 60, max_calls: 100 })
const selectedPreset = ref('deepseek')
const preset = computed(() => modelPresets.find(p => p.id === selectedPreset.value))
const key = ref(''), roles = ref('{}')
watch(() => state.session, session => { if (session) { Object.assign(config, { thinking_mode: null }, session.configuration); selectedPreset.value = identifyPreset(session.configuration); roles.value = JSON.stringify(session.configuration.role_overrides || {}, null, 2) } }, { immediate: true })
function presetChanged() { Object.assign(config, presetConfig(selectedPreset.value)); key.value = ''; roles.value = '{}' }
function providerChanged() { selectedPreset.value = 'custom'; config.thinking_mode = null; config.base_url = config.provider === 'openai-compatible' ? '' : 'https://api.anthropic.com'; key.value = '' }
async function save() {
  try { await work.action('校验模型配置', async () => JSON.parse(roles.value))
    if (state.error) return
    // A new main connection must not inherit an old Judge's lost credential.
    // The independent Judge panel explicitly binds a verified connection later.
    const {judge_provider_session_id, judge_provider_configuration, ...mainConfig} = config
    await work.setup({ ...mainConfig, role_overrides: JSON.parse(roles.value) }, key.value)
  } finally { key.value = '' }
}
</script>
<template>
  <div class="page-heading"><div><p class="eyebrow">连接自己的模型</p><h1>让模型准备好</h1><p>{{isRetrieval?'使用自己的模型服务，保存配置并测试文本连接，再准备知识库。':'使用你自己的模型服务。先连接，再检查工具能力。'}}</p></div><span class="pill">Key 仅保留在当前后端内存</span></div>
  <div class="two-column setup-columns">
    <section class="panel"><h2>模型配置</h2><p class="muted">保存后会创建一个新会话；修改配置不会重写已有实验。</p>
      <form @submit.prevent="save">
        <label>模型服务<select v-model="selectedPreset" @change="presetChanged"><option v-for="item in modelPresets" :key="item.id" :value="item.id">{{ item.label }}</option></select></label>
        <p class="muted preset-note">{{ anonymousWorkspace ? '公开站点支持 DeepSeek、百炼、Kimi、OpenAI、Claude、硅基流动、智谱、MiniMax 和火山方舟的已配置官方 HTTPS 地址。自定义地址也须在上述服务范围内。模型名称以你的账号实际开通为准。' : preset?.note }} <a v-if="preset?.docs" :href="preset.docs" target="_blank" rel="noopener noreferrer">官方说明 ↗</a></p>
        <label>Base URL<input v-model="config.base_url" type="url" required placeholder="https://api.openai.com/v1" /></label>
        <label>Model<input v-model="config.model" list="model-suggestions" required placeholder="选择建议或输入已开通的模型名" /></label>
        <datalist id="model-suggestions"><option v-for="model in preset?.models" :key="model" :value="model" /></datalist>
        <label>API Key<input v-model="key" type="password" required autocomplete="off" spellcheck="false" placeholder="仅用于本次后端会话" /></label>
        <div class="form-row"><label>Temperature<input v-model.number="config.temperature" type="number" min="0" max="1" step="0.1" required /></label><label>Max Tokens<input v-model.number="config.max_tokens" type="number" min="1" max="4096" required /></label></div>
        <details class="advanced"><summary>高级设置</summary><div class="form-row"><label>请求超时（秒）<input v-model.number="config.timeout_seconds" type="number" min="0.1" max="120" step="0.1" required /></label><label>单次调用预算<input v-model.number="config.max_calls" type="number" min="1" max="500" required /></label></div>
          <label>Provider<select v-model="config.provider" @change="providerChanged"><option value="openai-compatible">OpenAI-compatible</option><option value="anthropic-compatible">Anthropic-compatible</option></select></label>
          <label v-if="config.provider === 'openai-compatible'">输出预算参数<select v-model="config.completion_token_parameter"><option>max_completion_tokens</option><option>max_tokens</option></select></label>
          <label v-if="config.provider === 'openai-compatible'">模型思考模式<select v-model="config.thinking_mode"><option :value="null">使用服务默认设置</option><option value="disabled">普通对话（服务支持时关闭思考）</option></select></label>
          <label>角色配置覆盖（JSON）<textarea v-model="roles" rows="5" spellcheck="false" placeholder='{"judge":{"model":"your-judge-model"}}' /></label><p class="muted">general / technical / billing / escalation / composer / intent / judge。未覆盖字段继承用户默认配置。</p>
        </details>
        <button class="primary" :disabled="!!state.busy || !key || !config.model">保存模型会话</button>
      </form>
    </section>
    <div class="stack"><section class="panel connection-panel"><span class="eyebrow">CONNECTION CHECK</span><h2>两步确认，开始实验</h2>
      <p class="credential" :class="state.session?.credential_status === 'PRESENT' ? 'positive' : ''">{{ state.session?.credential_status === 'PRESENT' ? '凭据已加载到当前会话' : '凭据不可用，请重新输入' }}</p>
      <div class="connection-check"><span class="check-number">1</span><div><h3>模型连接</h3><p>{{ state.session?.text_connection_status === 'READY' ? '✓ 模型连接成功' : state.session?.text_connection_status === 'FAILED' ? '模型连接失败，请检查配置' : '等待测试文本请求' }}</p><button class="secondary" :disabled="!!state.busy || state.session?.credential_status !== 'PRESENT'" @click="work.testConnection">测试连接</button></div></div>
      <div class="connection-check"><span class="check-number">2</span><div><h3>工具调用能力 <span class="badge" :class="state.session?.tool_call_capability?.toLowerCase()">{{ toolStates[state.session?.tool_call_capability] || '未测试' }}</span></h3><p>{{isRetrieval?'当前知识问答与 RAG 评测不需要业务工具。这一步可跳过；探针只检查返回格式。':'客服行为评测会调用工具。这一步只检查工具调用格式，不会执行真实退款等操作。'}}</p><button class="secondary" :disabled="!!state.busy || state.session?.credential_status !== 'PRESENT' || state.session?.text_connection_status !== 'READY'" @click="work.testTools">测试工具能力</button></div></div>
      <p v-if="state.session?.tool_call_capability === 'UNSUPPORTED'" class="note danger">该模型可以普通对话，但当前无法运行智能电商 Agent 的完整客服评测。{{isRetrieval?'Retrieval 路径可使用文本连接；它不执行原业务工具链。':''}}</p>
      <p v-if="state.session?.tool_call_capability === 'FAILED'" class="note warning">探针暂时失败。这不等同于明确不支持，请检查连接与参数后重试。</p>
      <p v-if="state.session?.tool_call_capability === 'VERIFIED'" class="note positive">工具格式已验证；这不代表完整客服链路或回答质量已经通过。</p>
      <p v-if="isRetrieval" class="muted">Retrieval / RAG 只要求文本连接；工具探针可选。最终回答使用单一知识客服 Agent。</p>
      <button class="primary" :disabled="!!state.busy || state.session?.text_connection_status !== 'READY' || state.session?.credential_status !== 'PRESENT'" @click="work.go(activeBaseline ? 'evaluate' : isRetrieval ? 'knowledge' : 'define')">{{ activeBaseline ? '返回当前实验' : isRetrieval ? '下一步：准备知识与聊天' : '下一步：定义目标与测试' }} <span>→</span></button>
    </section><EvidenceDetails v-if="state.session" :data="state.session" title="本次模型条件" /></div>
  </div>
  <IndependentJudge v-if="isRetrieval" />
</template>
