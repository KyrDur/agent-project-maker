<script setup>
import { inject, ref } from 'vue'
import { canReview } from '../presentation'
const props = defineProps({ result: Object, runId: String })
const { state, review } = inject('workspace')
const status = ref('PASS'), reason = ref(''), reviewer = ref(''), override = ref(false)
async function save() {
  if (!canReview(props.result) || !reason.value.trim() || !reviewer.value.trim()) return
  if (props.result.hard_rule_violations.length && status.value === 'PASS' && !override.value) return
  await review(props.runId, { case_id: props.result.case_id, human_final_status: status.value,
    human_reason: reason.value.trim(), reviewer: reviewer.value.trim() })
}
</script>
<template>
  <details class="review" data-testid="review-form">
    <summary>人工复核</summary>
    <p v-if="!canReview(result)" class="note">执行失败或 Judge 失败不能人工改成有效 PASS / FAIL。请修复连接或执行问题后重新评测。</p>
    <form v-else @submit.prevent="save">
      <p class="muted">你可以纠正质量判断；原机器状态、规则违规和历史证据将永久保留。</p>
      <div class="form-row"><label>人工最终判定<select v-model="status"><option>PASS</option><option>FAIL</option></select></label><label>复核人<input v-model="reviewer" required placeholder="你的名字" /></label></div>
      <p v-if="result.hard_rule_violations.length && status === 'PASS'" class="note warning">你正在覆盖机器 Hard Rule 判定，请填写原因。</p>
      <label v-if="result.hard_rule_violations.length && status === 'PASS'" class="check"><input v-model="override" type="checkbox" required />我确认此次 PASS 是人工覆盖，机器违规事实仍保留</label>
      <label>复核理由<textarea v-model="reason" required rows="3" placeholder="说明你依据什么证据改判" /></label>
      <button class="secondary" :disabled="!!state.busy || !reason.trim() || !reviewer.trim() || (result.hard_rule_violations.length && status === 'PASS' && !override)">保存人工复核</button>
    </form>
  </details>
</template>
