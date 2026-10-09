import { reactive } from 'vue'
import { api, ApiError } from './api.js'
import { readPointers, savePointers, terminal } from './presentation.js'

export function createWorkspace(storage = globalThis.localStorage, client = api) {
  const state = reactive({ step: 'welcome', session: null, evalSet: null, baseline: null, retest: null,
    decision: null, change: null, comparison: null, selectedCase: null, error: null, notice: '',
    busy: '', history: [], evalSets: [], reviewRecords: [], initialized: false })
  let pollTimer
  const pointers = () => ({ step: state.step, session: state.session?.provider_session_id,
    evalSet: state.evalSet?.eval_set_id, baseline: state.baseline?.run.run_id,
    retest: state.retest?.run.run_id, decision: state.decision?.decision_id,
    change: state.change?.change_id, comparison: state.comparison?.comparison_id })
  function persist() { try { savePointers(storage, pointers()) } catch { state.notice = '浏览器无法保存实验入口；仍可从后端历史实验恢复。' } }
  function go(step) { state.step = step; persist() }
  async function action(label, fn) {
    if (state.busy) return
    state.busy = label; state.error = null; state.notice = ''
    try { const value = await fn(); persist(); return value }
    catch (error) { state.error = error instanceof ApiError ? { title: error.title, message: error.message, operation: label } :
      { title: '填写内容需要检查', message: '请检查 JSON 格式及必填内容，操作未被确认为成功。', operation: label } }
    finally { state.busy = '' }
  }
  async function history() {
    const [runs, sets, reviews] = await Promise.all([client.list('runs'), client.list('evalsets'), client.list('reviews')])
    state.history = runs; state.evalSets = sets; state.reviewRecords = reviews
  }
  async function loadRun(id) { return client.get('/runs/' + id) }
  async function openHistory(id) {
    clearTimeout(pollTimer)
    const view = await loadRun(id)
    const base = view.run.run_type === 'RETEST' ? await loadRun(view.run.parent_run_id) : view
    const retests = state.history.filter(r => r.parent_run_id === base.run.run_id)
    state.baseline = base
    state.retest = view.run.run_type === 'RETEST' ? view : retests[0] ? await loadRun(retests[0].run_id) : null
    state.evalSet = await client.get(`/evalsets/${base.run.eval_set_id}?version=${base.run.eval_set_snapshot.eval_set_version}`)
    const sessionId = state.retest?.run.provider_session_id || base.run.provider_session_id
    state.session = sessionId ? await client.get('/provider-sessions/' + sessionId) : null
    const [decisions, changes, comparisons] = await Promise.all([client.list('decisions'), client.list('changes'), client.list('comparisons')])
    const decision = decisions.find(d => d.related_run_id === base.run.run_id)
    state.decision = decision ? await client.get('/decisions/' + decision.decision_id) : null
    const change = changes.find(c => c.baseline_run_id === base.run.run_id && c.decision_id === state.decision?.decision_id)
    state.change = change ? await client.get('/changes/' + change.change_id) : null
    const comparison = comparisons.find(c => c.baseline_run_id === base.run.run_id && c.retest_run_id === state.retest?.run.run_id)
    state.comparison = comparison ? await client.get('/comparisons/' + comparison.comparison_id) : null
    state.selectedCase = state.decision?.selected_case_ids?.[0] || null
    if (state.comparison) go('compare')
    else go('evaluate')
    pollKnownRun()
  }
  function pollKnownRun() {
    clearTimeout(pollTimer)
    const pending = [state.baseline, state.retest].find(v => v && !terminal(v.run.status))
    if (!pending) return
    pollTimer = setTimeout(async () => {
      try {
        const view = await loadRun(pending.run.run_id)
        if (view.run.run_type === 'BASELINE') state.baseline = view
        else state.retest = view
        persist(); pollKnownRun()
      } catch { state.error = { title: '评测状态暂时无法读取', message: '请检查后端并点击“同步状态”，不会伪造执行进度。' } }
    }, 2000)
  }
  async function restore() {
    await history()
    const p = readPointers(storage)
    if (p.session) state.session = await client.get('/provider-sessions/' + p.session)
    if (p.evalSet) state.evalSet = await client.get('/evalsets/' + p.evalSet)
    const baseline = p.baseline || state.history.find(r => r.eval_set_id === p.evalSet && r.run_type === 'BASELINE')?.run_id
    if (baseline) {
      await openHistory(p.retest || baseline)
      // Prefer explicit current selections over inference from historical artifacts.
      if (p.decision) state.decision = await client.get('/decisions/' + p.decision)
      if (p.change) state.change = await client.get('/changes/' + p.change)
      if (p.comparison) state.comparison = await client.get('/comparisons/' + p.comparison)
      if (p.session) state.session = await client.get('/provider-sessions/' + p.session)
      state.selectedCase = state.decision?.selected_case_ids?.[0] || null
    }
    state.step = p.step || state.step
    state.initialized = true; persist()
  }
  return { state, go, action, restore, history, openHistory,
    initialize: async () => { await action('读取实验记录', restore); state.initialized = true },
    reset() { clearTimeout(pollTimer); Object.assign(state, { step: 'welcome', session: null, evalSet: null, baseline: null,
      retest: null, decision: null, change: null, comparison: null, selectedCase: null, error: null }); persist() },
    async setup(config, key) { return action('保存模型会话', async () => { state.session = await client.post('/provider-sessions', { ...config, api_key: key }); return state.session }) },
    async testConnection() { return action('测试模型连接', async () => {
      const result = await client.post(`/provider-sessions/${state.session.provider_session_id}/test`)
      state.session = await client.get('/provider-sessions/' + state.session.provider_session_id)
      if (result.status !== 'SUCCESS') throw new ApiError(result.status, 409)
      state.notice = '模型连接成功。这只验证文本请求。'
    }) },
    async testTools() { return action('测试工具能力', async () => {
      await client.post(`/provider-sessions/${state.session.provider_session_id}/test-tools`)
      state.session = await client.get('/provider-sessions/' + state.session.provider_session_id)
    }) },
    async define(body) { return action('保存测试集', async () => { state.evalSet = await client.post('/evalsets', body); go('evaluate') }) },
    async run(type) { return action(type === 'BASELINE' ? '第一次评测运行中' : '重新评测运行中', async () => {
      go('evaluate'); persist()
      const body = { provider_session_id: state.session.provider_session_id, eval_set_id: state.evalSet.eval_set_id,
        eval_set_version: state.evalSet.eval_set_version, run_type: type }
      if (type === 'RETEST') Object.assign(body, { eval_set_id: state.baseline.run.eval_set_id,
        eval_set_version: state.baseline.run.eval_set_snapshot.eval_set_version,
        parent_run_id: state.baseline.run.run_id, decision_id: state.decision.decision_id, change_ids: [state.change.change_id] })
      const run = await client.post('/runs', body)
      const view = await loadRun(run.run_id)
      if (type === 'BASELINE') state.baseline = view
      else state.retest = view
      await history()
    }) },
    async diagnose(caseId) { return action('创建产品分析草稿', async () => {
      state.decision = await client.post('/decisions', { related_run_id: state.baseline.run.run_id, selected_case_ids: [caseId] })
      state.change = null; state.selectedCase = caseId; go('improve')
    }) },
    async confirm(body) { return action('确认产品判断', async () => { state.decision = await client.post(`/decisions/${state.decision.decision_id}/confirm`, body) }) },
    async apply(skillId, body) { return action('应用规则修改', async () => {
      const change = await client.post('/changes', { decision_id: state.decision.decision_id, skill_id: skillId,
        rule_body: body, before_hash: state.baseline.run.skill_version.hash, change_type: 'SKILL_RULE', change_scope: 'ONE_SKILL_RULE_BODY' })
      state.change = change; persist()
      if (change.implemented_status === 'PROPOSED') state.change = await client.post(`/changes/${change.change_id}/apply`)
    }) },
    async compare() { return action('读取前后比较', async () => {
      state.comparison = await client.post('/comparisons', { baseline_run_id: state.baseline.run.run_id, retest_run_id: state.retest.run.run_id })
      go('compare')
    }) },
    async review(runId, body) { return action('保存人工复核', async () => {
      await client.post(`/runs/${runId}/reviews`, body)
      if (state.baseline?.run.run_id === runId) state.baseline = await loadRun(runId)
      if (state.retest?.run.run_id === runId) state.retest = await loadRun(runId)
      await history(); state.notice = '人工复核已保存，机器原判和已有比较记录保持不变。可重新生成比较以使用最新复核。'
    }) },
    async rollback() { return action('恢复修改前规则', async () => { state.change = await client.post(`/changes/${state.change.change_id}/rollback`) }) },
    dispose: () => clearTimeout(pollTimer),
  }
}
