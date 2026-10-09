<script setup>
import { computed, inject, ref } from 'vue'
import { transitions, sortPairs, warnings, reasonText, dimensions, qualityVisible } from '../presentation'
import StatusBadge from '../components/StatusBadge.vue'
import ReviewForm from '../components/ReviewForm.vue'
import EvidenceDetails from '../components/EvidenceDetails.vue'
const work = inject('workspace'), { state } = work
const filter = ref('ALL')
const pairs = computed(() => sortPairs(state.comparison?.case_comparisons || []).filter(p => filter.value === 'ALL' || p.effective_transition === filter.value))
const result = (side, id) => state[side]?.effective_results.find(r => r.case_id === id)
const title = id => result('baseline', id)?.case?.title || result('retest', id)?.case?.title || id
const answer = (side, id) => result(side, id)?.turn_evidence.map(t => `用户：${t.question}\nAgent：${t.response || '未生成可用回答'}`).join('\n\n') || '本侧缺失结果'
</script>
<template>
  <div class="page-heading"><div><p class="eyebrow">05 / COMPARE</p><h1>改了什么，结果变了什么</h1><p>逐题看改善与退化，保留无法比较的边界。</p></div><button v-if="state.baseline && state.retest" class="secondary" :disabled="!!state.busy" @click="work.compare">{{ state.comparison ? '生成最新比较' : '生成前后比较' }}</button></div>
  <div v-if="!state.comparison" class="empty panel"><h2>{{ state.retest ? '两次结果已经就绪' : '先完成一次受控修改与 Retest' }}</h2><p>Comparison 来自 Python 后端，不会在浏览器制造提升结果。</p><button class="primary" @click="state.retest ? work.compare() : work.go('improve')">{{ state.retest ? '生成前后比较' : '前往产品判断与修改 →' }}</button></div>
  <template v-else>
    <section class="comparison-banner panel"><span class="eyebrow">BASELINE → RETEST</span><h2>修改前 vs 修改后</h2><p data-testid="comparison-completeness">{{ state.comparison.matched_case_count }} / {{ state.comparison.expected_case_count }} 个测试已匹配结果</p><p>{{ state.comparison.group_metrics.dialog_case_metrics.valid_pair_count }} 个有效 Dialog Case 可以比较<span v-if="state.comparison.comparison_completeness === 'PARTIAL'"> · 部分结果未完成</span></p>
      <p class="note" :class="state.comparison.comparable ? 'positive' : 'warning'">{{ state.comparison.comparable ? '✓ 本次前后结果可以直接比较' : '前后实验条件不同，不能直接比较' }}</p>
      <p v-if="state.comparison.single_recorded_change" class="note positive">✓ 系统只记录到一个目标规则修改</p><p v-else class="note warning">系统未确认只有一个目标规则修改，请查看实验详情。</p>
      <p v-if="!state.comparison.attributable" class="note warning">{{ warnings.INSUFFICIENT_EVIDENCE }}</p>
      <p v-for="warning in state.comparison.attribution_warnings" :key="warning" class="warning-text">{{ warnings[warning] || `实验提示：${warning}` }}</p>
      <p v-for="reason in state.comparison.comparability_reasons" :key="reason" class="note warning">{{ reasonText(reason) }}</p>
      <p v-if="state.comparison.comparison_completeness === 'PARTIAL'" class="note">部分结果不会抹掉已有有效配对，也不能据此声称整套 EvalSet 的通过率提高。</p>
    </section>
    <div class="transition-metrics"><button v-for="(label, code) in transitions" :key="code" :class="{ active: filter === code, regression: code === 'REGRESSED' }" @click="filter = code"><span>{{ label }}</span><strong>{{ state.comparison.group_metrics.dialog_case_metrics.transitions[code] || 0 }}</strong></button></div>
    <div class="section-heading"><h2>逐题前后对照</h2><button class="text-button" @click="filter = 'ALL'">查看全部</button></div>
    <details v-for="pair in pairs" :key="pair.case_id" class="panel comparison-case" :data-transition="pair.effective_transition" open>
      <summary><h3>{{ title(pair.case_id) }}</h3><span class="badge" :class="pair.effective_transition.toLowerCase()">{{ transitions[pair.effective_transition] }}</span></summary>
      <p v-for="reason in pair.not_comparable_reasons" :key="reason" class="note">无法比较：{{ reasonText(reason) }}</p>
      <div class="form-row comparison-sides"><section v-for="side in ['baseline','retest']" :key="side"><span class="eyebrow">{{ side === 'baseline' ? 'BASELINE · 修改前' : 'RETEST · 修改后' }}</span>
        <div class="machine-line"><span>机器判定 <StatusBadge :status="pair[side === 'baseline' ? 'machine_status_a' : 'machine_status_b'] || '缺失'" /></span><span>比较采用的有效判定 <StatusBadge :status="pair[side === 'baseline' ? 'effective_status_a' : 'effective_status_b'] || '缺失'" /></span></div>
        <p class="answer-block">{{ answer(side, pair.case_id) }}</p>
        <div v-if="Object.keys(pair[side === 'baseline' ? 'quality_scores_a' : 'quality_scores_b']).length && result(side, pair.case_id) && qualityVisible(result(side, pair.case_id))" class="comparison-scores"><p v-for="(label, dim) in dimensions" :key="dim">{{ label }} <strong>{{ pair[side === 'baseline' ? 'quality_scores_a' : 'quality_scores_b'][dim] }}</strong></p></div><p v-else class="muted">没有可用质量分数</p>
        <p v-if="pair[side === 'baseline' ? 'human_reason_a' : 'human_reason_b']" class="note">人工复核：{{ pair[side === 'baseline' ? 'human_reason_a' : 'human_reason_b'] }}</p>
        <p v-if="result(side, pair.case_id)?.human_final_status" class="note" data-testid="current-human-review">当前人工最终判定：{{ result(side, pair.case_id).human_final_status }} · {{ result(side, pair.case_id).human_reason }}<br />机器原判：{{ result(side, pair.case_id).original_status }} · {{ result(side, pair.case_id).original_reason }}<br />{{ result(side, pair.case_id).hard_rule_override ? '人工已覆盖 Hard Rule，机器违规事实永久保留。' : '比较采用保存时的复核版本；当前复核可能尚未纳入。' }}</p>
        <p v-for="violation in pair[side === 'baseline' ? 'hard_rule_violations_a' : 'hard_rule_violations_b']" :key="violation" class="note danger">Machine Hard Rule Result = FAIL · {{ violation }}</p>
        <p v-if="pair[side === 'baseline' ? 'hard_rule_override_a' : 'hard_rule_override_b']" class="note warning">人工已覆盖此机器规则判定。Override reason：{{ pair[side === 'baseline' ? 'human_reason_a' : 'human_reason_b'] }}</p>
        <ReviewForm v-if="result(side, pair.case_id)" :result="result(side, pair.case_id)" :run-id="state[side].run.run_id" />
        <EvidenceDetails v-if="result(side, pair.case_id)" :data="result(side, pair.case_id)" title="此侧当前 Case 证据" />
      </section></div><EvidenceDetails :data="pair" title="保存的比较证据" />
    </details>
    <p v-if="!pairs.length" class="empty muted">当前分类没有 Case。</p>
    <p class="note">比较采用保存时的复核结果。人工复核之后，点击“生成最新比较”创建新记录；旧比较仍保留。</p>
    <details v-if="state.comparison.group_metrics.intent_metrics.sample_pairs.length" class="evidence"><summary>Intent Classification · 独立比较</summary><pre>{{ JSON.stringify(state.comparison.group_metrics.intent_metrics, null, 2) }}</pre></details>
    <section v-if="state.change" class="panel rollback-panel"><h2>保留实验，恢复规则</h2><p>恢复只影响生效规则，不会删除历史 Retest / Comparison。</p><button v-if="state.change.rollback_status !== 'ROLLED_BACK'" class="secondary" :disabled="!!state.busy || state.change.implemented_status !== 'APPLIED'" @click="work.rollback">恢复修改前规则</button><p v-if="state.change.rollback_status === 'ROLLED_BACK'" class="note positive">已恢复 Baseline 版本。历史 Comparison 仍然存在。</p><p v-if="state.change.rollback_status === 'FAILED'" class="note danger">恢复未成功，不能假定规则已经恢复。</p></section>
    <EvidenceDetails :data="state.comparison" title="比较条件、归因边界与证据" />
  </template>
</template>
