<script setup>
import { inject } from 'vue'
import { dimensions, qualityVisible } from '../presentation'
import StatusBadge from './StatusBadge.vue'
import EvidenceDetails from './EvidenceDetails.vue'
import ReviewForm from './ReviewForm.vue'
defineProps({ result: Object, runId: String, diagnose: Boolean, thresholds: Object })
const work = inject('workspace')
</script>
<template>
  <article class="case-card" :data-case-id="result.case_id">
    <div class="case-heading"><div><span class="eyebrow">CUSTOMER SERVICE TASK</span><h3>{{ result.case?.title || result.case_id }}</h3></div><StatusBadge :status="result.review_status === 'PENDING' ? 'PENDING' : result.final_status" /></div>
    <p v-if="result.execution_status !== 'SUCCESS'" class="note danger">本次评测无效：Agent 未成功执行。{{ result.turn_evidence?.find(t => t.execution_error)?.execution_error }}</p>
    <p v-else-if="result.judge_status === 'FAILED'" class="note danger">本次评测无效：Judge 请求失败。没有可用的质量分数。</p>
    <p v-else-if="result.evaluation_error" class="note danger">本次评测无效：评测过程未形成有效结论。</p>
    <p v-else-if="result.review_status === 'PENDING'" class="note">待人工复核：Agent 已执行，尚未形成有效质量结论。这不属于评测错误。</p>
    <p class="reason"><strong>判定依据</strong> {{ result.detail || result.original_reason }}</p>
    <div class="machine-line"><span>机器判定 <StatusBadge :status="result.original_status" /></span><span>有效判定 <StatusBadge :status="result.final_status" /></span></div>
    <p v-if="result.human_final_status" class="note">人工最终判定：{{ result.human_final_status }} · {{ result.human_reason }}<br />{{ result.hard_rule_override ? '人工已覆盖 Hard Rule；机器违规记录仍保留。' : '机器原判与原始理由保留。' }}</p>
    <p v-if="result.human_final_status" class="muted">机器原判理由：{{ result.original_reason }}</p>
    <ul v-if="result.hard_rule_violations.length" class="violations"><li v-for="item in result.hard_rule_violations" :key="item">Hard Rule violation：{{ item }}</li></ul>
    <div v-if="qualityVisible(result)" class="quality-grid" data-testid="quality-scores">
      <div v-for="(label, key) in dimensions" :key="key"><span>{{ label }} <small>{{ key }}</small></span><strong>{{ result.scores[key] }}</strong><div class="score-track"><i :style="{ width: (result.scores[key] * 100) + '%' }" /></div><small>本次门槛 {{ thresholds?.[key] ?? '见评测条件' }}</small></div>
    </div>
    <p v-else class="muted" data-testid="no-quality">{{ result.judge_status === 'NOT_REQUIRED' ? '本题按确定性规则判定，无需质量 Judge。' : '本题没有有效的四维质量评分。' }}</p>
    <details class="conversation" open><summary>对话与回答 <span>{{ result.turn_evidence.length }} 轮 · 1 个 Case</span></summary>
      <div v-for="turn in result.turn_evidence" :key="turn.turn" class="turn"><div class="user-message"><small>用户 · 第 {{ turn.turn }} 轮</small><p>{{ turn.question }}</p></div><div class="agent-message"><small>Agent 回答</small><p>{{ turn.response || '未生成可用回答' }}</p></div>
        <details v-if="turn.tool_traces.length" class="tools"><summary>工具调用证据 · {{ turn.tool_traces.length }} 次</summary><div v-for="(trace, i) in turn.tool_traces" :key="i"><strong>{{ trace.tool_name || trace.tool || trace.name || '工具调用' }}</strong><span class="badge" :class="trace.success ? 'pass' : 'fail'">{{ trace.success ? '成功' : '失败' }}</span><pre>{{ JSON.stringify(trace, null, 2) }}</pre></div></details>
      </div>
    </details>
    <button v-if="diagnose && result.final_status === 'FAIL'" class="secondary" :disabled="!!work.state.busy" @click="work.diagnose(result.case_id)">分析这个问题</button>
    <ReviewForm v-if="runId" :result="result" :run-id="runId" />
    <EvidenceDetails :data="result" title="查看此 Case 的原始证据" />
  </article>
</template>
