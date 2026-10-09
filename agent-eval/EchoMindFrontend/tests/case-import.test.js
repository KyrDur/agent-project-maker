import test from 'node:test'
import assert from 'node:assert/strict'
import { importCases, importExample } from '../src/case-import.js'
const example = JSON.parse(importExample)[0]

test('User refund JSON maps conditions, title and category without inventing executable rules', () => {
  const { cases, warnings } = importCases(JSON.stringify(example))
  assert.equal(cases[0].case_id, 'refund_01')
  assert.equal(cases[0].test_conditions, '用户没有提供订单号')
  assert.equal(cases[0].title, '退款 · refund_01')
  assert.equal(cases[0].must_do, '追问订单号\n说明需要核验后才能处理')
  assert.equal(cases[0].judge_method, 'LLM judge')
  assert.equal(cases[0].rules, '[]')
  assert.deepEqual(cases[0].import_info, { category: '退款', expected_tools: [] })
  assert.deepEqual(warnings, [])
})
test('Array, JSONL, consecutive objects and code fence preserve one multitur n task per Case', () => {
  const second = { ...example, case_id: 'refund_02', turns: ['我想退款', '订单是 01', '没有付款凭证'], must_do: ['说明含有 { } 和 "引号" 的信息'] }
  for (const text of [JSON.stringify([example, second]), `${JSON.stringify(example)}\n${JSON.stringify(second)}`,
    `${JSON.stringify(example)},\n${JSON.stringify(second)}`, '```json\n' + JSON.stringify([example, second]) + '\n```']) {
    const { cases } = importCases(text)
    assert.equal(cases.length, 2)
    assert.equal(cases[1].turns.length, 3)
  }
})
test('Expected tools remain natural expectations, including empty array not prohibiting tools', () => {
  const result = importCases(JSON.stringify({ ...example, expected_tools: ['check_billing_fields'] }))
  assert(result.cases[0].must_do.includes('期望使用工具：check_billing_fields'))
  assert.equal(result.cases[0].rules, '[]')
  assert.equal(result.warnings.length, 1)
})
test('Duplicate IDs, including append conflicts, reject the entire import', () => {
  assert.throws(() => importCases(JSON.stringify([example, example])), /重复/)
  assert.throws(() => importCases(JSON.stringify(example), ['refund_01']), /重复/)
})
test('Broken or incomplete JSON cannot partially import earlier valid objects', () => {
  for (const text of [`${JSON.stringify(example)}\n{"case_id":`, `${JSON.stringify(example)},`, '[', 'not JSON']) assert.throws(() => importCases(text), /JSON/)
})
test('Unsupported fields, malformed expectation arrays and ambiguous inputs are not silently dropped', () => {
  for (const row of [{ ...example, typo: 'must not silently disappear' }, { ...example, must_do: [42] },
    { ...example, input: 'conflict' }, { ...example, turns: [] }, { ...example, test_conditions: 'conflict' }]) assert.throws(() => importCases(JSON.stringify(row)))
})
test('Only explicitly supplied valid structured rules can become executable rules', () => {
  const rule = { type: 'required_tool', tool: 'check_billing_fields' }
  assert.deepEqual(JSON.parse(importCases(JSON.stringify({ ...example, executable_rules: [rule] })).cases[0].rules), [rule])
  assert.throws(() => importCases(JSON.stringify({ ...example, judge_method: 'rule' })), /需要明确/)
  assert.throws(() => importCases(JSON.stringify({ ...example, executable_rules: [{ type: 'keyword', target: '退款' }] })), /不支持/)
})
test('Missing IDs are assigned once; legacy question and newline expectation input remain usable', () => {
  const { cases } = importCases(JSON.stringify({ question: '我想退款', must_do: '追问订单号\n核验' }))
  assert(cases[0].case_id)
  assert.deepEqual(cases[0].turns, ['我想退款'])
  assert.equal(cases[0].must_do, '追问订单号\n核验')
})
