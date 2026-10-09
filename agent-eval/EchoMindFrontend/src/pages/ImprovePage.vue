<script setup>
import { computed, inject, reactive, ref, watch } from 'vue'
import { canDialogRun } from '../presentation'
import CaseEvidence from '../components/CaseEvidence.vue'
import EvidenceDetails from '../components/EvidenceDetails.vue'
const work = inject('workspace'), { state } = work
const result = computed(() => state.baseline?.effective_results.find(r => r.case_id === state.selectedCase))
const form = reactive({ user_confirmed_root_cause: '', root_cause_reason: '', alternatives: '', selected_strategy: '',
  selection_reason: '', expected_benefit: '', possible_side_effects: '', confirmed_by: '' })
watch(() => state.decision, dec => { if (dec) for (const key of Object.keys(form)) form[key] = key === 'alternatives' ? dec.alternatives.map(a => a.description).join('\n') : dec[key] || '' }, { immediate: true })
const skillId = ref(''), rule = ref('')
const skills = computed(() => state.baseline?.run.skill_version.skills || [])
const before = computed(() => skills.value.find(s => s.skill_id === skillId.value))
watch(skills, value => { skillId.value = state.change?.affected_component || value.find(s => s.agents.includes('billing'))?.skill_id || value[0]?.skill_id || '' }, { immediate: true })
watch(before, value => { rule.value = state.change?.after_snapshot.skills.find(s => s.skill_id === skillId.value)?.rule_body || value?.rule_body || '' }, { immediate: true })
const locked = computed(() => !!state.change && ['APPLIED','APPLYING'].includes(state.change.implemented_status))
const messages = { APPLIED: '✓ 修改已经生效', NOOP: '新旧规则没有实际变化', FAILED: '修改未成功应用', UNSUPPORTED: '当前版本不支持这种修改', PROPOSED: '修改已提出，尚未验证生效', APPLYING: '后端正在应用，尚未验证生效' }
async function confirm() { await work.confirm({ ...form, alternatives: form.alternatives.split('\n').filter(v => v.trim()).map(v => ({ description: v.trim() })) }) }
</script>
<template>
  <div class="page-heading"><div><p class="eyebrow">04 / IMPROVE</p><h1>把发现变成一个产品判断</h1><p>先确认为什么要改，再只修改一条 Skill 的规则正文。</p></div><span class="pill">一次只改一个目标规则</span></div>
  <div v-if="!state.decision || !result" class="empty panel"><h2>从一个失败问题开始</h2><p>在 Baseline 里选择 FAIL Case，点击“分析这个问题”。</p><button class="primary" @click="work.go('evaluate')">查看 Baseline →</button></div>
  <template v-else>
    <div class="diagnose-grid"><div><CaseEvidence :result="result" :run-id="state.baseline.run.run_id" :thresholds="state.baseline.run.evaluation_config_snapshot.quality_thresholds" /></div>
      <section class="panel"><span class="eyebrow">PRODUCT DECISION</span><h2>我的判断</h2><p class="muted">目标：{{ state.evalSet.metadata.objective?.goal }}</p>
        <div class="suggestion"><strong>AI 建议</strong><p>{{ state.decision.root_cause_suggestion || '当前后端未提供 AI 诊断建议。请根据左侧真实证据填写你的判断。' }}</p><p v-if="state.decision.strategy_suggestion">{{ state.decision.strategy_suggestion }}</p></div>
        <form @submit.prevent="confirm"><fieldset :disabled="state.decision.status === 'CONFIRMED' || !!state.busy">
          <label>我确认的根因<textarea v-model="form.user_confirmed_root_cause" required rows="2" placeholder="我认为问题出在……" /></label><label>根因判断依据<textarea v-model="form.root_cause_reason" required rows="2" placeholder="引用回答、工具轨迹或 Judge 证据" /></label><label>备选方案（每行一个）<textarea v-model="form.alternatives" rows="2" /></label><label>最终选择<input v-model="form.selected_strategy" required placeholder="我决定先修改……" /></label><label>选择理由<textarea v-model="form.selection_reason" required rows="2" /></label><div class="form-row"><label>预期收益<textarea v-model="form.expected_benefit" rows="2" /></label><label>可能副作用<textarea v-model="form.possible_side_effects" rows="2" /></label></div><label>确认人<input v-model="form.confirmed_by" required /></label>
          <button class="primary">确认我的产品判断</button>
        </fieldset></form><p v-if="state.decision.status === 'CONFIRMED'" class="note positive">✓ 我的判断已经明确确认，可以修改规则。AI 没有替你作决定。</p>
      </section>
    </div>
    <section class="panel skill-panel"><div class="section-heading"><div><span class="eyebrow">ONE SKILL RULE BODY</span><h2>把规则改得更明确</h2></div></div>
      <p v-if="state.decision.status !== 'CONFIRMED'" class="note">请先确认产品判断；未确认的 Decision 不能提交真实 Change。</p>
      <form @submit.prevent="work.apply(skillId, rule)"><fieldset :disabled="state.decision.status !== 'CONFIRMED' || !!state.busy || locked">
        <label>选择一个 Skill<select v-model="skillId"><option v-for="skill in skills" :key="skill.skill_id" :value="skill.skill_id">{{ skill.name }}</option></select></label><p class="muted">只开放规则正文修改。匹配条件、Agent 范围、注入预算和其他组件保持固定。</p>
        <div class="form-row diff"><div><h3>Before · 修改前</h3><pre>{{ before?.rule_body }}</pre></div><label>After · 修改后<textarea v-model="rule" required rows="14" spellcheck="false" /></label></div>
        <button class="primary" :disabled="!skillId || !rule.trim()">应用修改</button>
      </fieldset></form>
      <div v-if="state.change" class="change-outcome" data-testid="change-outcome"><p class="note" :class="state.change.implemented_status === 'APPLIED' ? 'positive' : 'warning'">{{ messages[state.change.implemented_status] }}</p>
        <p v-if="state.change.rollback_status === 'ROLLED_BACK'" class="note positive">已恢复 Baseline 版本。历史 Retest 与 Comparison 仍然保留。</p>
        <p v-if="state.change.rollback_status === 'FAILED'" class="note danger">恢复未成功，请同步状态并查看证据，不能假定已经恢复。</p>
        <div class="button-row"><button v-if="state.change.implemented_status === 'APPLIED' && state.change.rollback_status === 'NOT_REQUESTED' && !state.retest" class="primary" :disabled="!!state.busy || !canDialogRun(state.session)" @click="work.run('RETEST')">使用同一套测试重新评测 →</button><button v-if="state.change.implemented_status === 'APPLIED' && state.change.rollback_status === 'NOT_REQUESTED'" class="secondary" :disabled="!!state.busy" @click="work.rollback">恢复修改前规则</button><button v-if="state.retest" class="secondary" @click="work.go('compare')">查看比较 →</button></div>
        <p v-if="!canDialogRun(state.session)" class="note">重新评测前需要可用的模型凭据与连接。<button class="text-button" @click="work.go('setup')">重新配置</button></p>
      </div>
      <EvidenceDetails v-if="state.change" :data="state.change" title="修改与生效证据" />
    </section>
    <EvidenceDetails :data="state.decision" title="产品判断与确认记录" />
  </template>
</template>
