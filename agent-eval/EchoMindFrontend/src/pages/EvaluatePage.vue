<script setup>
import { computed, inject, ref, watch } from 'vue'
import { canRun, terminal, warnings } from '../presentation'
import CaseEvidence from '../components/CaseEvidence.vue'
import EvidenceDetails from '../components/EvidenceDetails.vue'
import StatusBadge from '../components/StatusBadge.vue'
const work = inject('workspace'), { state } = work
const tab = ref('baseline'), filter = ref('ALL')
watch(() => state.retest, value => { if (value) tab.value = 'retest' }, { immediate: true })
const view = computed(() => state[tab.value])
const filtered = computed(() => (view.value?.effective_results || []).filter(r => filter.value === 'ALL' ||
  (filter.value === 'PENDING' ? r.review_status === 'PENDING' : r.final_status === filter.value && r.review_status !== 'PENDING')))
const requiresTools = computed(() => !!state.evalSet?.case_snapshot.length)
const runnable = computed(() => canRun(state.session, requiresTools.value))
const retestable = computed(() => state.change?.implemented_status === 'APPLIED' && state.change.rollback_status === 'NOT_REQUESTED' && state.decision?.status === 'CONFIRMED')
</script>
<template>
  <div class="page-heading"><div><p class="eyebrow">03 / EVALUATE</p><h1>先观察，再下判断</h1><p>Baseline 是修改前的表现。失败与无效要分开看。</p></div><div class="button-row"><button v-if="state.baseline && retestable" class="primary" :disabled="!!state.busy || !runnable || !!state.retest" @click="work.run('RETEST')">使用同一套测试重新评测</button><button v-if="state.retest && terminal(state.retest.run.status)" class="secondary" :disabled="!!state.busy" @click="work.compare">查看前后比较 →</button></div></div>
  <div v-if="!state.evalSet" class="empty panel"><h2>先准备一套测试题</h2><p>用具体问题定义你希望客服做到什么。</p><button class="primary" @click="work.go('define')">创建测试</button></div>
  <template v-else>
    <div class="note"><strong>{{ state.evalSet.metadata.objective?.name || '当前测试集' }}</strong> · {{ state.evalSet.case_snapshot.length }} 个 Dialog Case<span v-if="state.evalSet.intent_case_snapshot.length">，{{ state.evalSet.intent_case_snapshot.length }} 个 Intent 样本（分开统计）</span><p>{{ state.evalSet.metadata.objective?.goal }}</p></div>
    <p v-if="state.session?.credential_status !== 'PRESENT'" class="note danger">模型凭据需要重新输入。<button class="text-button" @click="work.go('setup')">重新配置模型 →</button></p>
    <p v-else-if="requiresTools && state.session?.tool_call_capability === 'UNSUPPORTED'" class="note danger">该模型不支持工具调用，不能开始客服评测。请更换模型并重新测试。</p>
    <p v-else-if="state.session?.text_connection_status !== 'READY'" class="note">请先测试模型连接。</p>
    <p v-else-if="requiresTools && ['UNKNOWN','FAILED'].includes(state.session?.tool_call_capability)" class="note warning">{{ warnings['TOOL_CALL_CAPABILITY_' + state.session.tool_call_capability] }} <button class="text-button" @click="work.go('setup')">去测试工具能力</button></p>
    <button v-if="!state.baseline" class="primary" :disabled="!!state.busy || !runnable" @click="work.run('BASELINE')">开始第一次评测</button>
    <div v-if="state.busy.includes('评测') || (view && !terminal(view.run.status))" class="running panel" role="status"><span class="spinner" /><div><h2>评测运行中</h2><p>模型正在执行与判定。当前 API 不提供逐题进度，完成后显示真实结果。</p></div></div>
    <div v-if="state.baseline" class="tabs"><button :class="{ active: tab === 'baseline' }" @click="tab = 'baseline'">Baseline · 修改前</button><button v-if="state.retest" :class="{ active: tab === 'retest' }" @click="tab = 'retest'">Retest · 修改后</button></div>
    <template v-if="view">
      <div class="section-heading"><h2>{{ tab === 'baseline' ? 'Baseline' : 'Retest' }} <StatusBadge :status="view.run.status" /></h2><span class="muted">{{ new Date(view.run.created_at).toLocaleString('zh-CN') }}</span></div>
      <p v-if="view.run.status === 'FAILED'" class="note danger">Run 执行失败，未形成完整实验结论。请查看运行提示，修复连接或执行条件后开始新实验。</p>
      <p v-if="view.run.status === 'PARTIAL'" class="note warning">部分任务未采集；已有结果仍可查看，缺失任务不能当作 FAIL。</p>
      <div class="metrics"><div><small>有效 Case</small><strong>{{ view.dialog_case_metrics.valid }}<span> / {{ view.run.eval_set_snapshot.case_snapshot.length }}</span></strong></div><div><small>PASS · 通过</small><strong class="positive">{{ view.dialog_case_metrics.passed }}</strong></div><div><small>FAIL · 未通过</small><strong>{{ view.dialog_case_metrics.failed }}</strong></div><div><small>INVALID · 无效</small><strong>{{ view.dialog_case_metrics.invalid }}</strong></div><div><small>待人工复核</small><strong>{{ view.dialog_case_metrics.pending_human_reviews }}</strong></div></div>
      <p class="muted">已采集 {{ view.dialog_case_metrics.total }} 个 Dialog Case。待人工复核包含在 INVALID 中，不计入 Agent / Judge / Evaluation 错误。</p>
      <p v-if="view.intent_metrics.total" class="note">Intent Classification：{{ view.intent_metrics.correct }} / {{ view.intent_metrics.total }} 个样本正确，独立于 Dialog Case 通过率。</p>
      <div v-if="view.run.warnings.length" class="run-warnings"><p v-for="warning in view.run.warnings" :key="warning" class="note warning">{{ warnings[warning] || `运行提示：${warning}` }}</p></div>
      <div class="filter-row"><button v-for="item in ['ALL','FAIL','INVALID','PENDING','PASS']" :key="item" :class="{ active: filter === item }" @click="filter = item">{{ { ALL: '全部 Case', FAIL: '找失败', INVALID: '看无效', PENDING: '待复核', PASS: '已通过' }[item] }}</button></div>
      <div class="stack"><CaseEvidence v-for="result in filtered" :key="result.case_id" :result="result" :run-id="view.run.run_id" :diagnose="tab === 'baseline' && terminal(view.run.status) && !state.change" :thresholds="view.run.evaluation_config_snapshot.quality_thresholds" /></div>
      <p v-if="!filtered.length" class="empty muted">当前筛选下没有 Case。</p>
      <EvidenceDetails :data="view" title="本次评测条件与运行证据" />
    </template>
  </template>
</template>
