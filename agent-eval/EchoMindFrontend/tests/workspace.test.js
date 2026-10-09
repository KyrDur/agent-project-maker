import test from 'node:test'
import assert from 'node:assert/strict'
import { createWorkspace } from '../src/workspace.js'

const storage = () => ({ value: '{}', setItem(_, value) { this.value = value }, getItem() { return this.value } })
test('Retest binds Baseline EvalSet version, not a subsequently selected draft', async () => {
  const writes = []
  const run = { run_id: 'retest', run_type: 'RETEST', status: 'COMPLETE' }
  const client = { post: async (url, body) => { writes.push([url, body]); return run },
    get: async () => ({ run, effective_results: [] }), list: async () => [] }
  const work = createWorkspace(storage(), client)
  Object.assign(work.state, { session: { provider_session_id: 'session-a' }, evalSet: { eval_set_id: 'changed-draft', eval_set_version: 2 },
    baseline: { run: { run_id: 'baseline', eval_set_id: 'fixed-original', eval_set_snapshot: { eval_set_version: 1 } } },
    decision: { decision_id: 'confirmed' }, change: { change_id: 'applied' } })
  await work.run('RETEST')
  assert.deepEqual(writes[0], ['/runs', { provider_session_id: 'session-a', eval_set_id: 'fixed-original', eval_set_version: 1,
    run_type: 'RETEST', parent_run_id: 'baseline', decision_id: 'confirmed', change_ids: ['applied'] }])
})
test('Change UI state follows actual API NOOP/FAILED, never optimistic APPLIED', async () => {
  for (const outcome of ['NOOP','FAILED','APPLIED']) {
    const change = { change_id: 'change-a', implemented_status: 'PROPOSED' }
    const posts = []
    const work = createWorkspace(storage(), { post: async (url, body) => { posts.push([url, body]);
      return url === '/changes' ? change : { ...change, implemented_status: outcome } } })
    Object.assign(work.state, { decision: { decision_id: 'decision-a' }, baseline: { run: { skill_version: { hash: 'actual-before-hash' } } } })
    await work.apply('billing.md', 'new body')
    assert.equal(work.state.change.implemented_status, outcome)
    assert.equal(posts[0][1].change_scope, 'ONE_SKILL_RULE_BODY')
    assert.equal(posts[0][1].change_type, 'SKILL_RULE')
    assert.equal(posts[0][1].before_hash, 'actual-before-hash')
  }
})
test('Review rereads effective API results while immutable Comparison is retained', async () => {
  const before = { comparison_id: 'historic-comp', comparable: true }
  const effective = { original_status: 'FAIL', final_status: 'PASS', human_reason: 'evidence' }
  const work = createWorkspace(storage(), { post: async () => ({ review_id: 'review-a' }),
    get: async () => ({ run: { run_id: 'base' }, effective_results: [effective] }), list: async () => [] })
  Object.assign(work.state, { baseline: { run: { run_id: 'base' }, effective_results: [] }, comparison: before })
  await work.review('base', { case_id: 'a', human_final_status: 'PASS', human_reason: 'evidence', reviewer: 'user' })
  assert.equal(work.state.baseline.effective_results[0].original_status, 'FAIL')
  assert.equal(work.state.baseline.effective_results[0].final_status, 'PASS')
  assert.equal(work.state.comparison.comparison_id, 'historic-comp')
})
test('Rollback retains Retest and Comparison instead of resetting history', async () => {
  const work = createWorkspace(storage(), { post: async () => ({ change_id: 'c', rollback_status: 'ROLLED_BACK' }) })
  Object.assign(work.state, { change: { change_id: 'c' }, comparison: { comparison_id: 'historic' }, retest: { run: { run_id: 'retest' } } })
  await work.rollback()
  assert.equal(work.state.change.rollback_status, 'ROLLED_BACK')
  assert.equal(work.state.retest.run.run_id, 'retest')
  assert.equal(work.state.comparison.comparison_id, 'historic')
})
test('After lost POST response, restore discovers saved Run from real list/get APIs', async () => {
  const memory = storage()
  memory.value = JSON.stringify({ step: 'evaluate', evalSet: 'ev', session: 'session' })
  const gets = [], lists = []
  const run = { run_id: 'persisted', run_type: 'BASELINE', eval_set_id: 'ev', provider_session_id: 'session',
    eval_set_snapshot: { eval_set_version: 1 }, status: 'COMPLETE' }
  const client = { list: async group => { lists.push(group); return group === 'runs' ? [run] : [] },
    get: async url => { gets.push(url); return url.startsWith('/runs') ? { run, effective_results: [] }
      : url.startsWith('/evalsets') ? { eval_set_id: 'ev' } : { provider_session_id: 'session', credential_status: 'UNAVAILABLE' } } }
  const work = createWorkspace(memory, client)
  await work.restore()
  assert.equal(work.state.baseline.run.run_id, 'persisted')
  assert.equal(work.state.session.credential_status, 'UNAVAILABLE')
  assert.equal(work.state.step, 'evaluate')
  assert(gets.includes('/runs/persisted'))
  assert(lists.includes('reviews') && lists.includes('comparisons') && lists.includes('changes') && lists.includes('decisions'))
  work.dispose()
})
