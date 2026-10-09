<script setup>
import { inject, reactive, ref, watch } from 'vue'
import EvidenceDetails from '../components/EvidenceDetails.vue'
import { importCases, importExample } from '../case-import.js'
const work = inject('workspace'), { state } = work
const objective = reactive({ name: '', goal: '', correct_behavior: '', unacceptable_behavior: '' })
const makeCase = () => ({ case_id: crypto.randomUUID(), title: '', turns: [''], must_do: '', must_not_do: '', test_conditions: '', rules: '[]', judge_method: 'LLM judge' })
const cases = ref([])
const mode = ref('import'), importText = ref(''), importError = ref(''), importWarnings = ref([]), importMode = ref('replace')
function chooseMode(value) { mode.value = value; if (value === 'manual' && !cases.value.length) cases.value.push(makeCase()) }
function parseImport() {
  importError.value = ''
  try {
    const parsed = importCases(importText.value, importMode.value === 'append' ? cases.value.map(c => c.case_id) : [])
    cases.value = importMode.value === 'append' ? [...cases.value, ...parsed.cases] : parsed.cases
    importWarnings.value = parsed.warnings
    if (!objective.name.trim()) objective.name = '导入的电商客服测试'
    if (!objective.goal.trim()) objective.goal = '根据每道题的测试条件和期望行为，评测客服 Agent 的回答。'
    if (!objective.correct_behavior.trim()) objective.correct_behavior = '满足每道题的「必须做到」，缺少必要信息时先澄清。'
    if (!objective.unacceptable_behavior.trim()) objective.unacceptable_behavior = '违反每道题的「不能做」或编造事实。'
  } catch (error) { importError.value = error.message + ' 当前题目保持不变。' }
}
watch(() => state.evalSet, ev => {
  if (!ev) return
  Object.assign(objective, ev.metadata.objective || {})
  mode.value = 'manual'
  cases.value = ev.case_snapshot.map(c => ({ ...c, import_info: ev.metadata.case_import_info?.[c.case_id], turns: c.turns.length ? [...c.turns] : [c.input],
    must_do: c.must_do.join('\n'), must_not_do: c.must_not_do.join('\n'), rules: JSON.stringify(c.executable_rules, null, 2) }))
}, { immediate: true })
const lines = value => value.split('\n').map(s => s.trim()).filter(Boolean)
function copy(c) { cases.value.push({ ...c, case_id: crypto.randomUUID(), title: c.title + '（副本）', turns: [...c.turns] }) }
async function save() {
  await work.action('校验测试内容', async () => cases.value.forEach(c => { if (!Array.isArray(JSON.parse(c.rules))) throw new Error('rules') }))
  if (state.error) return
  await work.define({ metadata: { objective: { ...objective }, case_import_info: Object.fromEntries(cases.value.filter(c => c.import_info).map(c => [c.case_id, c.import_info])) }, dialog_cases: cases.value.map(c => ({ case_id: c.case_id,
    title: c.title, scenario: c.scenario ?? objective.goal, ...(c.user_id !== undefined ? { user_id: c.user_id } : {}),
    ...(c.conv_id !== undefined ? { conv_id: c.conv_id } : {}), turns: [...c.turns], test_conditions: c.test_conditions,
    must_do: [...new Set([...lines(objective.correct_behavior), ...lines(c.must_do)])],
    must_not_do: [...new Set([...lines(objective.unacceptable_behavior), ...lines(c.must_not_do)])], executable_rules: JSON.parse(c.rules),
    judge_method: c.judge_method, source: 'user_created' })) })
}
</script>
<template>
  <div class="page-heading"><div><p class="eyebrow">02 / DEFINE</p><h1>先说清楚，什么叫做好</h1><p>用同一套问题检验优化。自然语言期望不会自动变成硬规则。</p></div></div>
  <p v-if="state.baseline" class="note">这套测试已经用于 Baseline，现在只读。Retest 必须使用同一个固定版本；新目标请开始新实验。</p>
  <form @submit.prevent="save">
    <fieldset :disabled="!!state.baseline || !!state.busy">
      <section class="panel import-panel"><h2>你的测试题，直接粘贴就能用</h2><p class="muted">批量导入自己的题目，不用逐题填写。导入只准备测试，不会自动发起模型请求。</p>
        <div class="button-row input-modes" role="group" aria-label="测试题输入方式"><button type="button" :class="mode === 'import' ? 'primary' : 'secondary'" :aria-pressed="mode === 'import'" @click="chooseMode('import')">批量粘贴 JSON</button><button type="button" :class="mode === 'manual' ? 'primary' : 'secondary'" :aria-pressed="mode === 'manual'" @click="chooseMode('manual')">逐题填写（可选）</button></div>
        <template v-if="mode === 'import'"><label>测试题 JSON<textarea v-model="importText" rows="10" spellcheck="false" :placeholder="importExample" /></label><p class="muted">支持单个对象、JSON 数组，也支持连续粘贴多个对象。conditions 会作为测试条件；未写判定方式时使用默认 Judge，不必填写可执行规则。</p>
          <label v-if="cases.length">导入方式<select v-model="importMode"><option value="replace">替换当前 {{ cases.length }} 道题</option><option value="append">追加到当前题目之后</option></select></label>
          <div class="button-row"><button type="button" class="secondary" :disabled="!importText.trim()" @click="parseImport">{{ cases.length && importMode === 'replace' ? '解析并替换当前题目' : '解析并预览' }}</button><button type="button" class="text-button" @click="importText = importExample; importError = ''">填入格式示例</button></div>
          <p v-if="importError" class="note danger" role="alert">{{ importError }}</p><p v-for="warning in importWarnings" :key="warning" class="note warning">{{ warning }}</p>
          <p v-if="cases.length" class="note positive" role="status">已准备 {{ cases.length }} 道题。请确认目标与题目，保存后再开始评测。</p>
        </template>
      </section>
      <section class="panel objective-panel"><span class="eyebrow">PRODUCT OBJECTIVE</span><h2>我的客服目标</h2><label>测试场景名称<input v-model="objective.name" required placeholder="例如：退款客服 Agent" /></label><label>产品目标<textarea v-model="objective.goal" required rows="2" placeholder="例如：正确判断退款资格，不在缺少证据时声称退款完成" /></label><div class="form-row"><label>正确行为<textarea v-model="objective.correct_behavior" required rows="3" placeholder="理想回答应该做什么？" /></label><label>不可接受行为<textarea v-model="objective.unacceptable_behavior" required rows="3" placeholder="哪些行为绝对不能接受？" /></label></div></section>
      <div class="section-heading"><div><h2>我的测试题 · {{ cases.length }} 道</h2><p class="muted">每个任务是一个 Case。多轮对话仍然只算一道题。</p></div><button v-if="mode === 'manual'" type="button" class="secondary" @click="cases.push(makeCase())">＋ 添加 Case</button></div>
      <section v-for="(c, index) in cases" :key="c.case_id" class="panel builder-card">
        <details :open="mode === 'manual'" class="case-editor"><summary><strong>{{ c.title || '未命名测试' }}</strong><span>{{ c.turns.length }} 轮 · 1 道题 · 查看或修改</span></summary>
        <div class="section-heading"><span class="eyebrow">CASE {{ String(index + 1).padStart(2, '0') }}</span><div class="button-row"><button type="button" class="text-button" @click="copy(c)">复制</button><button type="button" class="text-button" :disabled="cases.length === 1" @click="cases.splice(index, 1)">删除</button></div></div>
        <label>Case 标题<input v-model="c.title" required placeholder="例如：缺少付款凭证的退款申请" /></label>
        <div v-for="(_, turn) in c.turns" :key="turn" class="turn-editor"><label>用户输入 · 第 {{ turn + 1 }} 轮<textarea v-model="c.turns[turn]" required rows="2" placeholder="输入真实用户会说的问题" /></label><button v-if="turn > 0" type="button" class="text-button" @click="c.turns.splice(turn, 1)">删除此轮</button></div>
        <button type="button" class="text-button" @click="c.turns.push('')">＋ 添加一轮对话</button>
        <div class="form-row"><label>必须做到（每行一条）<textarea v-model="c.must_do" rows="2" /></label><label>不能做（每行一条）<textarea v-model="c.must_not_do" rows="2" /></label></div><label>测试条件<input v-model="c.test_conditions" placeholder="例如：用户没有提供订单号或付款证明" /></label>
        <details class="advanced"><summary>判定方式与可执行规则</summary><label>Judge method<select v-model="c.judge_method"><option>LLM judge</option><option>rule</option><option>tool trace</option><option>human review</option></select></label><label>结构化 executable rules（JSON 数组）<textarea v-model="c.rules" rows="4" spellcheck="false" /></label><p class="muted">只有结构化规则触发 Hard Rule。自然语言“必须做到 / 不能做”供 Judge 与人工参考。</p><p class="muted">例如：[{"type":"required_tool","tool":"check_billing_fields"}]</p></details>
        <div class="preview"><span class="eyebrow">保存前预览</span><p><strong>{{ c.title || '未命名测试' }}</strong> · {{ c.turns.length }} 轮，1 个 Case</p><p>{{ c.turns.filter(Boolean).join(' → ') || '等待填写用户问题' }}</p><p v-if="c.must_do">期望：{{ c.must_do }}</p><p v-if="c.must_not_do">不能：{{ c.must_not_do }}</p></div>
        </details>
      </section>
    </fieldset>
    <div class="button-row"><button v-if="!state.baseline" class="primary" :disabled="!!state.busy || !cases.length">保存测试，准备 Baseline →</button><button v-else type="button" class="primary" @click="work.go('evaluate')">查看 Baseline →</button></div>
  </form>
  <EvidenceDetails v-if="state.evalSet" :data="state.evalSet" />
</template>
