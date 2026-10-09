export const dimensions = { relevance: '相关性', accuracy: '准确性', completeness: '完整性', helpfulness: '帮助度' }
export const transitions = { IMPROVED: '改善', REGRESSED: '退化', STILL_PASS: '保持通过', STILL_FAIL: '仍然失败', NOT_COMPARABLE: '无法比较' }
export const toolStates = { UNKNOWN: '未测试', VERIFIED: '已验证', FAILED: '暂时失败', UNSUPPORTED: '不支持' }
export const statuses = { PASS: 'PASS · 通过', FAIL: 'FAIL · 未通过', INVALID: 'INVALID · 无效', PENDING: '待人工复核', COMPLETE: '执行完成', PARTIAL: '部分完成', FAILED: '执行失败', RUNNING: '评测运行中', CREATED: '等待执行' }
export const warnings = {
  REDUCED_RUNTIME_KNOWLEDGE_DISABLED: '本次实验未启用 Knowledge/RAG，因此结果不能代表完整在线客服效果。',
  INSUFFICIENT_EVIDENCE: '这次结果不能视为严格因果证明。模型服务内部版本无法由客户端验证，且当前为单次运行，无法证明变化完全由本次修改造成。',
  MODEL_BACKEND_REVISION_UNVERIFIED: '模型服务内部版本无法由客户端验证。',
  SINGLE_RUN_RANDOMNESS_NOT_CAUSAL_PROOF: '当前仅运行一次，模型随机性可能影响结果。',
  TOOL_CALL_CAPABILITY_UNKNOWN: '工具能力尚未验证，本次评测仍可能遇到工具协议错误。',
  TOOL_CALL_CAPABILITY_FAILED: '工具探针暂时失败；本次运行仍存在工具能力未验证的风险。',
  RESPONSE_MODEL_IDENTIFIER_CHANGED: '模型服务返回的模型标识前后发生变化。',
  RESPONSE_MODEL_IDENTIFIER_DIFFERS_FROM_REQUEST: '模型服务返回的模型标识与请求名称不同。',
  PARTIAL_MATCHED_VALID_CASES_ONLY: '结果不完整，仅展示已有有效匹配，不能声称整套测试的通过率提高。',
  PROCESS_INTERRUPTED: '后端运行中断，本次实验未完整采集。',
  CREDENTIAL_UNAVAILABLE: '模型凭据需要重新输入。',
  RUNTIME_FAILED: 'Agent 执行未成功完成，请检查执行证据并重新评测。',
  CALL_BUDGET_EXCEEDED: '本次模型请求超出设定预算，未能完成采集。',
  UNEXPLAINED_APPLY_OR_ROLLBACK: '两次运行之间存在未纳入实验的应用或恢复操作。',
}
export const reasons = {
  MISSING_RETEST_RESULT: 'Retest 缺失结果', MISSING_BASELINE_RESULT: 'Baseline 缺失结果',
  INVALID_EVALUATION: '至少一侧评测无效', EVALSET_CHANGED: '前后使用了不同测试',
  INFERENCE_CONFIG_CHANGED: '前后模型或推理条件不同', EVALUATION_PROTOCOL_CHANGED: '判定规则发生变化',
  UNRECORDED_CHANGE: '检测到未记录的修改', RUNTIME_DRIFT: '实际运行条件发生变化',
  SAME_RUN: '选择了同一次运行，不能形成前后对照', RUN_NOT_SEALED: '至少一次运行还未结束',
  MODEL_PROVIDER_INFERENCE_CHANGED: '前后模型服务或推理参数不同', AGENT_CONFIG_CHANGED: 'Agent 配置发生变化',
  PROMPT_CHANGED: 'Agent 提示词发生变化', KNOWLEDGE_CHANGED: '知识配置发生变化', ROUTING_CHANGED: '路由规则发生变化',
  RUNTIME_POLICY_CHANGED: '实验运行条件发生变化', EXECUTION_ORDER_CHANGED: '测试执行顺序不同',
  RUNTIME_CONFIG_DRIFT: '真实生效配置与冻结条件不同', MULTI_COMPONENT_CHANGE: '实际修改超出了一个 Skill 规则正文',
  UNVERIFIED_CHANGE_CHAIN: '修改与生效证据无法完整核验', EXPERIMENT_STATE_NOT_ISOLATED: '实验运行状态未可靠隔离',
  EVALSET_SNAPSHOT_MISMATCH: '测试条件记录不一致', MISSING_OR_INVALID_EVALSET_SNAPSHOT: '缺少有效测试条件记录',
  MISSING_OR_INVALID_PROTOCOL_SNAPSHOT: '缺少有效判定规则记录', MISSING_REQUIRED_SNAPSHOT: '缺少必要实验条件记录',
  MISSING_OR_DRIFTED_RUNTIME_READBACK: '缺少一致的生效配置核验',
}
export const reasonText = code => reasons[code] || '存在额外实验条件限制，请展开原始证据核验。'
export function qualityVisible(result) { return result.execution_status === 'SUCCESS' && !result.evaluation_error && result.judge_status === 'SUCCESS' && Object.keys(result.scores || {}).length > 0 }
export function canReview(result) { return result.execution_status === 'SUCCESS' && result.judge_status !== 'FAILED' && !result.evaluation_error }
export function canRun(session, requiresTools = true) { return !!session && session.credential_status === 'PRESENT' && session.text_connection_status === 'READY' && (!requiresTools || session.tool_call_capability !== 'UNSUPPORTED') }
export const canDialogRun = session => canRun(session, true)
export function sortPairs(pairs) {
  const rank = { REGRESSED: 0, IMPROVED: 1, NOT_COMPARABLE: 2, STILL_FAIL: 3, STILL_PASS: 4 }
  return [...pairs].sort((a, b) => rank[a.effective_transition] - rank[b.effective_transition])
}
export const terminal = status => ['COMPLETE', 'PARTIAL', 'FAILED'].includes(status)
export function savePointers(storage, source) {
  const allowed = ['session', 'evalSet', 'baseline', 'retest', 'decision', 'change', 'comparison']
  const data = { step: ['welcome','chat','knowledge','setup','define','evaluate','improve','compare','career'].includes(source.step) ? source.step : 'welcome' }
  for (const key of allowed) if (typeof source[key] === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(source[key])) data[key] = source[key]
  storage.setItem('echomind.workspace.v1', JSON.stringify(data))
}
export function readPointers(storage) {
  try {
    const data = JSON.parse(storage.getItem('echomind.workspace.v1') || '{}')
    if (!data || typeof data !== 'object') return {}
    // Apply the same whitelist without writing anything or accepting arbitrary fields.
    const sink = { setItem: (_, value) => { sink.value = JSON.parse(value) } }
    savePointers(sink, data)
    return sink.value
  } catch { return {} }
}
