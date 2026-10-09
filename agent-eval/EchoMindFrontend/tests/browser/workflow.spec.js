import { test, expect } from '@playwright/test'
import { randomBytes } from 'node:crypto'
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import path from 'node:path'
const evidence = process.env.ECHOMIND_TEST_EVIDENCE_DIR || path.resolve('../../phase4')
const localProviderURL = `http://127.0.0.1:${process.env.ECHOMIND_TEST_PROVIDER_PORT || '8124'}/v1`

test('Bulk user JSON import: real EvalSet, editable preview, no auto-run, preserved conditions and IDs', async ({ page, request }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '02 Define 定义目标与测试', exact: true }).click()
  await expect(page.getByLabel('测试题 JSON', { exact: true })).toBeVisible()
  const first = { case_id: 'refund_01', category: '退款', turns: ['我想退款'], conditions: '用户没有提供订单号',
    expected_tools: [], must_do: ['追问订单号', '说明需要核验后才能处理'], must_not_do: ['声称退款已完成', '编造订单信息'] }
  const second = { ...first, case_id: 'refund_02', turns: ['我要退款', '订单号是 TEST-001', '没有付款凭证'], expected_tools: ['check_billing_fields'] }
  const before = await (await request.get('/api/experiments/artifacts/runs')).json()
  await page.getByLabel('测试题 JSON', { exact: true }).fill(JSON.stringify(first) + '\n' + JSON.stringify(second))
  await page.getByRole('button', { name: '解析并预览', exact: true }).click()
  await expect(page.getByText('已准备 2 道题。请确认目标与题目，保存后再开始评测。', { exact: true })).toBeVisible()
  await expect(page.getByText('expected_tools 已作为自然语言期望加入评测上下文，不会自动变成硬规则。', { exact: true })).toBeVisible()
  await expect(page.locator('.builder-card')).toHaveCount(2)
  await page.locator('.builder-card').first().locator('.case-editor > summary').click()
  await expect(page.locator('.builder-card').first().getByLabel('测试条件', { exact: true })).toHaveValue(first.conditions)
  await page.locator('.builder-card').first().getByLabel('Case 标题', { exact: true }).fill('未提供订单号的退款申请')
  // Parsing failure is atomic; it must not erase the successfully imported cases.
  await page.getByLabel('测试题 JSON', { exact: true }).fill(JSON.stringify(first) + '\n{"case_id":')
  await page.getByRole('button', { name: '解析并替换当前题目', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('JSON 不完整')
  await expect(page.locator('.builder-card')).toHaveCount(2)
  await page.getByRole('button', { name: '保存测试，准备 Baseline →', exact: true }).click()
  await expect(page.getByRole('button', { name: '开始第一次评测', exact: true })).toBeVisible()
  const pointers = await page.evaluate(() => JSON.parse(localStorage.getItem('echomind.workspace.v1')))
  const ev = await (await request.get('/api/experiments/evalsets/' + pointers.evalSet)).json()
  expect(ev.case_snapshot.map(c => c.case_id)).toEqual(['refund_01', 'refund_02'])
  expect(ev.case_snapshot[0].title).toBe('未提供订单号的退款申请')
  expect(ev.case_snapshot[0].test_conditions).toBe(first.conditions)
  expect(ev.case_snapshot[0].must_do).toContain('追问订单号')
  expect(ev.case_snapshot[1].turns).toHaveLength(3)
  expect(ev.case_snapshot.every(c => c.judge_method === 'LLM judge' && c.executable_rules.length === 0)).toBe(true)
  expect(ev.metadata.case_import_info.refund_02.expected_tools).toEqual(['check_billing_fields'])
  const after = await (await request.get('/api/experiments/artifacts/runs')).json()
  expect(after.total).toBe(before.total)
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('用户没有提供订单号')
  await page.reload()
  await page.getByRole('button', { name: '02 Define 定义目标与测试', exact: true }).click()
  await expect(page.locator('.builder-card')).toHaveCount(2)
  await expect(page.locator('.builder-card').first().getByLabel('Case 标题', { exact: true })).toHaveValue('未提供订单号的退款申请')
  await page.screenshot({ path: evidence + '/json-import-restored-1440.png', fullPage: true })
})
async function setup(page, model = 'phase4-scripted') {
  await page.goto('/')
  await page.getByRole('button', { name: '开始配置', exact: false }).click()
  await page.getByLabel('Base URL', { exact: true }).fill(localProviderURL)
  await page.getByLabel('Model', { exact: true }).fill(model)
  const key = randomBytes(24).toString('hex')
  await page.getByLabel('API Key', { exact: true }).fill(key)
  await page.getByRole('button', { name: '保存模型会话', exact: true }).click()
  await expect(page.getByText('凭据已加载到当前会话', { exact: true })).toBeVisible()
  await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('')
  return key
}
async function define(page, records) {
  await page.getByRole('button', { name: /下一步：定义目标/ }).click()
  await page.getByRole('button', { name: '逐题填写（可选）', exact: true }).click()
  await page.getByLabel('测试场景名称', { exact: true }).fill('退款客服产品实验')
  await page.getByLabel('产品目标', { exact: true }).fill('核验退款信息并避免无证据宣称完成退款')
  await page.getByLabel('正确行为', { exact: true }).fill('先核验付款信息，再说明退款流程')
  await page.getByLabel('不可接受行为', { exact: true }).fill('无成功退款证据宣称退款已经完成')
  for (let index = 0; index < records.length; index++) {
    if (index) await page.getByRole('button', { name: '＋ 添加 Case', exact: true }).click()
    const card = page.locator('.builder-card').nth(index), record = records[index]
    await card.getByLabel('Case 标题', { exact: true }).fill(record.title)
    await card.getByLabel('用户输入 · 第 1 轮', { exact: true }).fill(record.input)
    if (record.turns) for (let t = 0; t < record.turns.length; t++) {
      await card.getByRole('button', { name: '＋ 添加一轮对话', exact: true }).click()
      await card.getByLabel(`用户输入 · 第 ${t + 2} 轮`, { exact: true }).fill(record.turns[t])
    }
    if (record.rules || record.method) {
      await card.getByText('判定方式与可执行规则', { exact: true }).click()
      if (record.rules) await card.getByLabel('结构化 executable rules（JSON 数组）', { exact: true }).fill(JSON.stringify(record.rules))
      if (record.method) await card.getByRole('combobox', { name: 'Judge method', exact: true }).selectOption(record.method)
    }
  }
  await page.getByRole('button', { name: '保存测试，准备 Baseline →', exact: true }).click()
  await expect(page.getByRole('button', { name: '开始第一次评测', exact: true })).toBeVisible()
}
async function runBaseline(page) {
  await page.getByRole('button', { name: '开始第一次评测', exact: true }).click()
  await expect(page.locator('.case-card').first()).toBeVisible({ timeout: 40000 })
}

test('Model presets and ecommerce title: editable endpoints, DeepSeek default, clean service switching', async ({ page, request }) => {
  await page.goto('/')
  await expect(page).toHaveTitle('智能电商 Agent 评测')
  await expect(page.locator('body')).not.toContainText('EchoMind')
  await page.getByRole('button', { name: '开始配置', exact: false }).click()
  await expect(page.getByRole('combobox', { name: '模型服务', exact: true })).toHaveValue('deepseek')
  await expect(page.getByLabel('Base URL', { exact: true })).toHaveValue('https://api.deepseek.com/v1')
  await expect(page.getByLabel('Model', { exact: true })).toHaveValue('deepseek-flash')
  await page.getByLabel('API Key', { exact: true }).fill('local-preset-test-key')
  await page.getByRole('combobox', { name: '模型服务', exact: true }).selectOption('qwen')
  await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('')
  await expect(page.getByLabel('Model', { exact: true })).toHaveValue('qwen-plus')
  await page.getByRole('combobox', { name: '模型服务', exact: true }).selectOption('kimi')
  await expect(page.getByLabel('Base URL', { exact: true })).toHaveValue('https://api.moonshot.cn/v1')
  await page.getByRole('combobox', { name: '模型服务', exact: true }).selectOption('openai')
  await expect(page.getByLabel('Model', { exact: true })).toHaveValue('gpt-4.1-mini')
  await page.getByRole('combobox', { name: '模型服务', exact: true }).selectOption('claude')
  await expect(page.getByLabel('Base URL', { exact: true })).toHaveValue('https://api.anthropic.com')
  await page.getByRole('combobox', { name: '模型服务', exact: true }).selectOption('custom')
  await expect(page.getByLabel('Model', { exact: true })).toHaveValue('')
  await page.getByRole('combobox', { name: '模型服务', exact: true }).selectOption('deepseek')
  await page.getByLabel('Base URL', { exact: true }).fill(localProviderURL)
  await page.getByLabel('API Key', { exact: true }).fill('local-preset-test-key')
  await page.getByRole('button', { name: '保存模型会话', exact: true }).click()
  await expect(page.getByText('凭据已加载到当前会话', { exact: true })).toBeVisible()
  const pointers = await page.evaluate(() => JSON.parse(localStorage.getItem('echomind.workspace.v1')))
  const session = await (await request.get('/api/experiments/provider-sessions/' + pointers.session)).json()
  expect(session.configuration.thinking_mode).toBe('disabled')
  expect(session.configuration.completion_token_parameter).toBe('max_tokens')
  expect(session.configuration.model).toBe('deepseek-flash')
  await page.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(page.getByText('✓ 模型连接成功', { exact: true })).toBeVisible()
  await page.screenshot({ path: evidence + '/model-setup-1440.png' })
})

test('Golden Path: real HTTP / Python closed loop, all transitions, review, refresh and rollback', async ({ page, request }) => {
  const consoleErrors = []
  page.on('pageerror', e => consoleErrors.push(e.message))
  const key = await setup(page)
  await expect(page.getByRole('button', { name: '测试工具能力', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(page.getByText('✓ 模型连接成功', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '测试工具能力', exact: true }).click()
  await expect(page.getByText('工具格式已验证；这不代表完整客服链路或回答质量已经通过。', { exact: true })).toBeVisible()
  await define(page, [
    { title: '退款凭证缺失', input: '退款申请，请先检查账单信息', turns: ['退款订单号是 TEST-001', '退款付款凭证暂缺'] },
    { title: '意外退化', input: '退款 PHASE4_REGRESSION_CASE' },
    { title: '稳定通过', input: '退款 PHASE4_STILL_PASS' },
    { title: '仍需改进', input: '退款 PHASE4_STILL_FAIL' },
    { title: 'Judge 不可用', input: '退款 PHASE4_JUDGE_FAILURE' },
    { title: '机器规则违规', input: '退款 PHASE4_STILL_FAIL', rules: [{ type: 'required_tool', tool: 'unavailable_refund_operation' }] },
  ])
  await runBaseline(page)
  await expect(page.locator('.case-card')).toHaveCount(6)
  const refund = page.locator('.case-card').filter({ has: page.getByRole('heading', { name: '退款凭证缺失', exact: true }) })
  await expect(refund.getByText('3 轮 · 1 个 Case', { exact: true })).toBeVisible()
  const judge = page.locator('.case-card').filter({ has: page.getByRole('heading', { name: 'Judge 不可用', exact: true }) })
  await expect(judge.getByTestId('quality-scores')).toHaveCount(0)
  await expect(judge.getByText('本次评测无效：Judge 请求失败。没有可用的质量分数。', { exact: true })).toBeVisible()
  await judge.getByText('人工复核', { exact: true }).click()
  await expect(judge.getByText(/执行失败或 Judge 失败不能人工改成有效/)).toBeVisible()
  await expect(judge.getByRole('button', { name: '保存人工复核' })).toHaveCount(0)
  await refund.getByRole('button', { name: '分析这个问题', exact: true }).click()
  await expect(page.getByText('当前后端未提供 AI 诊断建议。请根据左侧真实证据填写你的判断。', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '应用修改', exact: true })).toBeDisabled()
  await page.getByLabel('我确认的根因', { exact: true }).fill('规则没有明确核验付款信息的顺序')
  await page.getByLabel('根因判断依据', { exact: true }).fill('Baseline 工具检查存在，但质量四维低于门槛')
  await page.getByLabel('备选方案（每行一个）', { exact: true }).fill('增加核验步骤\n保持现有规则')
  await page.getByLabel('最终选择', { exact: true }).fill('只修改账单 Skill 的规则正文')
  await page.getByLabel('选择理由', { exact: true }).fill('改动范围最小，并且可以用同一套测试复测')
  await page.getByLabel('预期收益', { exact: true }).fill('更完整地说明核验流程')
  await page.getByLabel('可能副作用', { exact: true }).fill('回答变长，可能导致其他测试退化')
  await page.getByLabel('确认人', { exact: true }).fill('Phase 4 browser tester')
  await page.getByRole('button', { name: '确认我的产品判断', exact: true }).click()
  await expect(page.getByRole('button', { name: '应用修改', exact: true })).toBeEnabled()
  // NOOP must be a real backend result, not a frontend before/after guess.
  await page.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(page.getByText('新旧规则没有实际变化', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /使用同一套测试重新评测/ })).toHaveCount(0)
  const rule = page.getByLabel('After · 修改后', { exact: true })
  await rule.fill((await rule.inputValue()) + '\n先核验付款凭证再解释退款流程。PHASE4_CHECK_PAYMENT_BEFORE_CLAIMS\n')
  await page.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(page.getByText('✓ 修改已经生效', { exact: true })).toBeVisible()
  await page.screenshot({ path: evidence + '/improve-1440.png', fullPage: false })
  await page.getByRole('button', { name: /使用同一套测试重新评测/ }).click()
  await expect(page.getByRole('button', { name: 'Retest · 修改后', exact: true })).toBeVisible({ timeout: 40000 })
  await page.getByRole('button', { name: /查看前后比较/ }).click()
  await expect(page.getByText('✓ 本次前后结果可以直接比较', { exact: true })).toBeVisible()
  await expect(page.getByText('✓ 系统只记录到一个目标规则修改', { exact: true })).toBeVisible()
  await expect(page.getByText(/这次结果不能视为严格因果证明/)).toBeVisible()
  await expect(page.getByText('本次实验未启用 Knowledge/RAG，因此结果不能代表完整在线客服效果。', { exact: true })).toBeVisible()
  for (const transition of ['IMPROVED','REGRESSED','STILL_PASS','STILL_FAIL','NOT_COMPARABLE']) await expect(page.locator(`[data-transition="${transition}"]`).first()).toBeVisible()
  const hard = page.locator('.comparison-case').filter({ has: page.getByRole('heading', { name: '机器规则违规', exact: true }) }).locator('.comparison-sides section').first()
  await hard.getByText('人工复核', { exact: true }).click()
  await expect(hard.getByText('你正在覆盖机器 Hard Rule 判定，请填写原因。', { exact: true })).toBeVisible()
  await hard.getByLabel('复核人', { exact: true }).fill('tester')
  await expect(hard.getByRole('button', { name: '保存人工复核', exact: true })).toBeDisabled()
  await hard.getByLabel('复核理由', { exact: true }).fill('测试使用了不可用的退款工具作为规则，应纠正误设规则；不删除机器事实')
  await hard.getByLabel('我确认此次 PASS 是人工覆盖，机器违规事实仍保留', { exact: true }).check()
  await hard.getByRole('button', { name: '保存人工复核', exact: true }).click()
  await expect(page.getByText(/人工复核已保存，机器原判和已有比较记录保持不变/)).toBeVisible()
  await expect(hard.getByTestId('current-human-review')).toContainText('当前人工最终判定：PASS')
  await expect(hard.getByTestId('current-human-review')).toContainText('机器原判：FAIL')
  const pointers = await page.evaluate(() => JSON.parse(localStorage.getItem('echomind.workspace.v1')))
  const originalComparison = pointers.comparison
  const stored = await page.evaluate(async () => ({ local: JSON.stringify(localStorage), session: JSON.stringify(sessionStorage), db: await indexedDB.databases() }))
  expect(stored.local + stored.session).not.toContain(key); expect(stored.db).toHaveLength(0)
  expect(Object.keys(pointers).every(k => ['step','session','evalSet','baseline','retest','decision','change','comparison'].includes(k))).toBe(true)
  const baseline = (await (await request.get('/api/experiments/runs/' + pointers.baseline)).json())
  const retest = (await (await request.get('/api/experiments/runs/' + pointers.retest)).json())
  expect(retest.run.eval_set_id).toBe(baseline.run.eval_set_id)
  expect(retest.run.eval_set_hash).toBe(baseline.run.eval_set_hash)
  expect(baseline.effective_results.some(r => r.hard_rule_override && r.original_status === 'FAIL' && r.final_status === 'PASS')).toBe(true)
  await page.reload()
  await expect(page.getByText('✓ 本次前后结果可以直接比较', { exact: true })).toBeVisible()
  await expect(page.getByTestId('current-human-review')).toContainText('当前人工最终判定：PASS')
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('echomind.workspace.v1')).comparison)).toBe(originalComparison)
  await page.getByRole('button', { name: '恢复修改前规则', exact: true }).click()
  await expect(page.getByText('已恢复 Baseline 版本。历史 Comparison 仍然存在。', { exact: true })).toBeVisible()
  expect((await request.get('/api/experiments/comparisons/' + originalComparison)).status()).toBe(200)
  await page.reload()
  await expect(page.getByText('已恢复 Baseline 版本。历史 Comparison 仍然存在。', { exact: true })).toBeVisible()
  expect(consoleErrors).toEqual([])
  mkdirSync(evidence, { recursive: true })
  writeFileSync(evidence + '/golden-path.json', JSON.stringify({ status: 'PASS', ...pointers,
    actual_python_api: true, browser_request_mocks: false, provider: 'local scripted Chat Completions',
    commercial_model_claim: false, key_persisted: false, all_five_transitions_observed: true,
    hard_rule_review_preserved: true, refresh_restored: true, rollback_preserved_comparison: true }, null, 2) + '\n')
  await page.screenshot({ path: evidence + '/comparison-1440.png', fullPage: true })
  await page.screenshot({ path: evidence + '/comparison-top-1440.png', fullPage: false })
  for (const width of [1366,1280,390]) {
    await page.setViewportSize({ width, height: 950 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await page.screenshot({ path: evidence + '/comparison-mobile.png', fullPage: false })
})

test('Real unsupported provider blocks Dialog; credential loss shows re-entry message', async ({ page, request }) => {
  await setup(page, 'tools-unsupported')
  await page.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(page.getByText('✓ 模型连接成功', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '测试工具能力', exact: true }).click()
  await expect(page.getByText('该模型可以普通对话，但当前无法运行智能电商 Agent 的完整客服评测。', { exact: true })).toBeVisible()
  await define(page, [{ title: '工具不支持', input: '退款' }])
  await expect(page.getByRole('button', { name: '开始第一次评测', exact: true })).toBeDisabled()
  const sid = await page.evaluate(() => JSON.parse(localStorage.getItem('echomind.workspace.v1')).session)
  await request.delete('/api/experiments/provider-sessions/' + sid)
  await page.reload()
  await expect(page.getByText(/模型凭据需要重新输入/).first()).toBeVisible()
})

test('Real connection auth failure is translated and leaves tool testing disabled', async ({ page }) => {
  await setup(page, 'auth-failed')
  await page.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(page.getByText('模型认证失败', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '测试工具能力', exact: true })).toBeDisabled()
})

test('Real temporary tool probe failure stays FAILED with a retry message', async ({ page }) => {
  await setup(page, 'tools-probe-failed')
  await page.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(page.getByText('✓ 模型连接成功', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '测试工具能力', exact: true }).click()
  await expect(page.getByText('暂时失败', { exact: true })).toBeVisible()
  await expect(page.getByText('探针暂时失败。这不等同于明确不支持，请检查连接与参数后重试。', { exact: true })).toBeVisible()
})

test('Welcome layout works at desktop and mobile widths without fake experiment results', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /智能电商 Agent/  })).toBeVisible()
  for (const width of [1366,1440,1280,390]) {
    await page.setViewportSize({ width, height: 950 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    mkdirSync(evidence, { recursive: true })
    await page.screenshot({ path: `${evidence}/welcome-${width}.png`, fullPage: true })
  }
})

test('Real pending Human Review stays separate, legal review preserves machine INVALID', async ({ page, request }) => {
  await setup(page)
  await page.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(page.getByText('✓ 模型连接成功', { exact: true })).toBeVisible()
  // UNKNOWN is an allowed state with a visible warning, not a fabricated VERIFIED.
  await define(page, [{ title: '等待人工确认', input: '退款需要核验订单', method: 'human review' }])
  await expect(page.getByText(/工具能力尚未验证，本次评测仍可能遇到工具协议错误/).first()).toBeVisible()
  await runBaseline(page)
  await expect(page.getByText('待人工复核：Agent 已执行，尚未形成有效质量结论。这不属于评测错误。', { exact: true })).toBeVisible()
  const id = await page.evaluate(() => JSON.parse(localStorage.getItem('echomind.workspace.v1')).baseline)
  const before = await (await request.get('/api/experiments/runs/' + id)).json()
  expect(before.dialog_case_metrics.pending_human_reviews).toBe(1)
  expect(before.dialog_case_metrics.agent_errors + before.dialog_case_metrics.judge_errors + before.dialog_case_metrics.evaluation_errors).toBe(0)
  await page.locator('.case-card').getByText('人工复核', { exact: true }).click()
  await page.getByLabel('复核人', { exact: true }).fill('reviewer')
  await page.getByLabel('复核理由', { exact: true }).fill('基于对话和工具调用，确认行为满足本次任务期望')
  await page.getByRole('button', { name: '保存人工复核', exact: true }).click()
  await expect(page.getByText(/人工最终判定：PASS/)).toBeVisible()
  const after = await (await request.get('/api/experiments/runs/' + id)).json()
  expect(after.effective_results[0].original_status).toBe('INVALID')
  expect(after.effective_results[0].final_status).toBe('PASS')
  expect(after.dialog_case_metrics.pending_human_reviews).toBe(0)
})

async function fixturePointers(page, step) {
  const pointers = JSON.parse(readFileSync(evidence + '/golden-path.json', 'utf8'))
  await page.addInitScript(({ pointers, step }) => {
    const keys = ['session','evalSet','baseline','retest','decision','change','comparison']
    localStorage.setItem('echomind.workspace.v1', JSON.stringify(Object.fromEntries([
      ['step', step], ...keys.map(key => [key, pointers[key]])
    ])))
  }, { pointers, step })
  return pointers
}

test('UI state fixture: PARTIAL keeps completed pairs and explains missing Retest', async ({ page, request }) => {
  const pointers = await fixturePointers(page, 'compare')
  const actual = await (await request.get('/api/experiments/comparisons/' + pointers.comparison)).json()
  const partial = structuredClone(actual)
  partial.comparison_completeness = 'PARTIAL'; partial.matched_case_count = 5
  const missing = partial.case_comparisons.find(p => p.effective_transition === 'STILL_PASS')
  missing.effective_transition = 'NOT_COMPARABLE'; missing.machine_transition = 'NOT_COMPARABLE'
  missing.effective_status_b = null; missing.machine_status_b = null
  missing.quality_scores_b = {}
  missing.not_comparable_reasons = ['MISSING_RETEST_RESULT']
  partial.group_metrics.dialog_case_metrics.valid_pair_count = 4
  partial.group_metrics.dialog_case_metrics.transitions.STILL_PASS = 0
  partial.group_metrics.dialog_case_metrics.transitions.NOT_COMPARABLE = 2
  const actualRetest = await (await request.get('/api/experiments/runs/' + pointers.retest)).json()
  const partialRetest = structuredClone(actualRetest)
  partialRetest.run.status = 'PARTIAL'
  partialRetest.run.case_results = partialRetest.run.case_results.filter(r => r.case_id !== missing.case_id)
  partialRetest.effective_results = partialRetest.effective_results.filter(r => r.case_id !== missing.case_id)
  Object.assign(partialRetest.dialog_case_metrics, { total: 5, valid: 4, passed: 1, failed: 3, quality_scored_cases: 3,
    avg_scores: { relevance: .45, accuracy: .45, completeness: .45, helpfulness: .45, overall: .45 } })
  await page.route(`**/api/experiments/runs/${pointers.retest}`, route => route.fulfill({ json: partialRetest }))
  await page.route(`**/api/experiments/comparisons/${pointers.comparison}`, route => route.fulfill({ json: partial }))
  await page.goto('/')
  await expect(page.getByTestId('comparison-completeness')).toHaveText('5 / 6 个测试已匹配结果')
  await expect(page.getByText('无法比较：Retest 缺失结果', { exact: true })).toBeVisible()
  await expect(page.getByText('本侧缺失结果', { exact: true })).toBeVisible()
  await expect(page.locator('[data-transition="IMPROVED"]')).toBeVisible()
  await expect(page.locator('[data-transition="REGRESSED"]')).toBeVisible()
  await expect(page.getByText('部分结果不会抹掉已有有效配对，也不能据此声称整套 EvalSet 的通过率提高。', { exact: true })).toBeVisible()
  await page.screenshot({ path: evidence + '/partial-state-fixture.png', fullPage: false })
})

test('UI state fixture: Apply FAILED never enables Retest or claims success', async ({ page, request }) => {
  const pointers = await fixturePointers(page, 'improve')
  const change = await (await request.get('/api/experiments/changes/' + pointers.change)).json()
  await page.route(`**/api/experiments/changes/${pointers.change}`, route => route.fulfill({ json: {
    ...change, implemented_status: 'FAILED', rollback_status: 'NOT_REQUESTED', error: 'READBACK_FAILED'
  } }))
  await page.goto('/')
  await expect(page.getByText('修改未成功应用', { exact: true })).toBeVisible()
  await expect(page.getByText('✓ 修改已经生效', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /使用同一套测试重新评测/ })).toHaveCount(0)
})

test('UI state fixture: Agent execution error cannot be human-reviewed into PASS', async ({ page, request }) => {
  const pointers = await fixturePointers(page, 'evaluate')
  const actual = await (await request.get('/api/experiments/runs/' + pointers.retest)).json()
  const failed = structuredClone(actual)
  const result = failed.effective_results[0]
  Object.assign(result, { execution_status: 'FAILED', judge_status: 'NOT_RUN', original_status: 'INVALID',
    final_status: 'INVALID', scores: {}, original_reason: 'Agent 请求失败', detail: 'Agent 请求失败', review_status: 'NOT_REQUIRED' })
  await page.route(`**/api/experiments/runs/${pointers.retest}`, route => route.fulfill({ json: failed }))
  await page.goto('/')
  const card = page.locator('.case-card').first()
  await expect(card.getByText(/本次评测无效：Agent 未成功执行/)).toBeVisible()
  await card.getByText('人工复核', { exact: true }).click()
  await expect(card.getByText(/执行失败或 Judge 失败不能人工改成有效/)).toBeVisible()
  await expect(card.getByRole('button', { name: '保存人工复核' })).toHaveCount(0)
  await expect(card.getByTestId('quality-scores')).toHaveCount(0)
})

test('UI state fixture: API unavailable explains Python backend recovery', async ({ page }) => {
  await page.route('**/api/experiments/artifacts/**', route => route.fulfill({ status: 503, json: { detail: 'unsafe provider secret' } }))
  await page.goto('/')
  await expect(page.getByText('实验后端暂不可用', { exact: true })).toBeVisible()
  await expect(page.getByText('请启动 Python experiments.app 服务。', { exact: true })).toBeVisible()
  await expect(page.getByText('unsafe provider secret')).toHaveCount(0)
})
