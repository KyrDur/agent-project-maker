import test from 'node:test'
import assert from 'node:assert/strict'
import { canRun, canDialogRun, canReview, qualityVisible, transitions, sortPairs, savePointers, readPointers } from '../src/presentation.js'
import { ApiError, createApi, describeError } from '../src/api.js'

test('Only identifiers and navigation survive browser storage; no credentials or configuration', () => {
  const storage = { value: '', setItem(_, value) { this.value = value }, getItem() { return this.value } }
  savePointers(storage, { session: 'session-a', evalSet: 'ev-a', baseline: 'run-a', step: 'compare',
    api_key: 'never-persist-secret', configuration: { api_key: 'never-persist-secret' }, role_overrides: {},
    review: { human_reason: 'never persist form' } })
  assert.deepEqual(JSON.parse(storage.value), { step: 'compare', session: 'session-a', evalSet: 'ev-a', baseline: 'run-a' })
  assert(!storage.value.includes('secret'))
  storage.value = JSON.stringify({ step: 'improve', session: { api_key: 'never-persist-secret' } })
  assert.deepEqual(readPointers(storage), { step: 'improve' })
  storage.value = 'bad JSON'
  assert.deepEqual(readPointers(storage), {})
})
test('Dialog admission mirrors backend connection boundary, not PASS/FAIL judgment', () => {
  const ready = { text_connection_status: 'READY', credential_status: 'PRESENT' }
  for (const cap of ['VERIFIED','UNKNOWN','FAILED']) assert(canDialogRun({ ...ready, tool_call_capability: cap }))
  assert(!canDialogRun({ ...ready, tool_call_capability: 'UNSUPPORTED' }))
  assert(canRun({ ...ready, tool_call_capability: 'UNSUPPORTED' }, false))
  assert(!canDialogRun({ ...ready, credential_status: 'UNAVAILABLE' }))
  assert(!canDialogRun({ ...ready, text_connection_status: 'UNTESTED' }))
})
test('No failed Judge placeholder scores are displayed; invalid execution cannot be reviewed', () => {
  assert(!qualityVisible({ judge_status: 'FAILED', scores: { accuracy: .5 } }))
  assert(qualityVisible({ execution_status: 'SUCCESS', judge_status: 'SUCCESS', scores: { accuracy: .75 } }))
  assert(!qualityVisible({ execution_status: 'FAILED', judge_status: 'SUCCESS', scores: { accuracy: .95 } }))
  assert(!canReview({ execution_status: 'FAILED', judge_status: 'SUCCESS' }))
  assert(!canReview({ execution_status: 'SUCCESS', judge_status: 'FAILED' }))
  assert(!canReview({ execution_status: 'SUCCESS', judge_status: 'SUCCESS', evaluation_error: 'invalid' }))
  assert(canReview({ execution_status: 'SUCCESS', judge_status: 'NOT_RUN' }))
})
test('All backend transition names display distinctly with regressions first', () => {
  const pairs = Object.keys(transitions).map(effective_transition => ({ effective_transition }))
  assert.deepEqual(sortPairs(pairs).map(p => p.effective_transition), ['REGRESSED','IMPROVED','NOT_COMPARABLE','STILL_FAIL','STILL_PASS'])
  assert.equal(transitions.NOT_COMPARABLE, '无法比较')
})
for (const [status, title] of [[409,'操作条件尚未满足'],[422,'填写内容需要检查'],[503,'实验后端暂不可用'],[0,'无法连接实验 API']]) {
  test(`API ${status} classifies failure without exposing raw response`, async () => {
    const api = createApi(async () => ({ ok: false, status, json: async () => ({ detail: 'unsafe-secret-error-body' }) }))
    await assert.rejects(api.post('/runs', {}), e => e instanceof ApiError && e.title === title && !JSON.stringify(e).includes('unsafe-secret'))
  })
}
test('Text connection failures distinguish auth/model/rate/timeout/network', () => {
  assert.equal(new Set(['AUTH_FAILED','MODEL_NOT_FOUND','RATE_LIMITED','TIMEOUT','NETWORK_ERROR'].map(c => describeError(c).title)).size, 5)
})
test('API client returns backend decisions without creating frontend verdicts', async () => {
  const artifact = { original_status: 'INVALID', final_status: 'INVALID', scores: {}, comparable: true, attributable: false }
  const api = createApi(async () => ({ ok: true, json: async () => artifact }))
  assert.equal(await api.get('/runs/actual'), artifact)
})
