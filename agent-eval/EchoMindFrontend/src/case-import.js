const methods = ['LLM judge', 'rule', 'tool trace', 'human review']
const fields = new Set(['case_id', 'title', 'category', 'turns', 'input', 'question', 'conditions', 'test_conditions',
  'expected_tools', 'must_do', 'must_not_do', 'executable_rules', 'judge_method', 'scenario', 'user_id', 'conv_id'])
const fail = message => { throw new Error(message) }
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)

export function records(text) {
  if (typeof text !== 'string' || text.length > 1000000) fail('请粘贴不超过 1 MB 的测试题 JSON。')
  const input = text.trim().replace(/^```(?:json|jsonl)?\s*\n([\s\S]*?)\n```$/i, '$1').trim()
  if (!input) fail('请先粘贴测试题 JSON。')
  try { const parsed = JSON.parse(input); return Array.isArray(parsed) ? parsed : [parsed] } catch { /* Try consecutive objects / JSONL. */ }
  const output = []
  let start = -1, depth = 0, quoted = false, escaped = false, comma = false
  for (let i = 0; i < input.length; i++) {
    const c = input[i]
    if (start === -1) {
      if (/\s/.test(c)) continue
      if (c === ',' && output.length && !comma) { comma = true; continue }
      if (c !== '{') fail('JSON 格式有误。请使用一个对象、对象数组，或逐个粘贴完整的 JSON 对象。')
      start = i; depth = 1; quoted = false; escaped = false; comma = false; continue
    }
    if (quoted) {
      if (escaped) escaped = false
      else if (c === '\\') escaped = true
      else if (c === '"') quoted = false
    } else if (c === '"') quoted = true
    else if (c === '{') depth++
    else if (c === '}' && --depth === 0) {
      try { output.push(JSON.parse(input.slice(start, i + 1))) } catch { fail(`第 ${output.length + 1} 个 JSON 对象格式有误，请检查引号和逗号。`) }
      start = -1
    }
  }
  if (start !== -1 || !output.length || comma) fail('JSON 不完整，请检查括号、引号或末尾逗号。')
  return output
}

export function importCases(text, existingIds = []) {
  const rows = records(text)
  if (!rows.length || rows.length > 100) fail('每次请导入 1 至 100 道题。')
  const seen = new Set(existingIds), warnings = new Set()
  const cases = rows.map((raw, index) => {
    const error = message => fail(`第 ${index + 1} 题：${message}`)
    if (!object(raw)) error('每道题必须是一个 JSON 对象。')
    const unknown = Object.keys(raw).filter(k => !fields.has(k))
    if (unknown.length) error(`存在不支持的字段：${unknown.join('、')}。请先移除或改用页面支持的字段。`)
    const string = (value, name, fallback = '') => {
      if (value === undefined) return fallback
      if (typeof value !== 'string' || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)) error(`${name} 应填写文本。`)
      return value.trim()
    }
    const list = (value, name) => {
      if (value === undefined) return []
      const items = typeof value === 'string' ? value.split('\n').map(s => s.trim()).filter(Boolean) : value
      if (!Array.isArray(items) || items.some(v => typeof v !== 'string' || !v.trim())) error(`${name} 应是文本数组，或每行一条的文本。`)
      return items.map(v => string(v, name))
    }
    const case_id = raw.case_id === undefined ? crypto.randomUUID() : string(raw.case_id, 'case_id')
    if (!case_id || seen.has(case_id)) error('case_id 为空或重复，请为每道题使用不同编号。')
    seen.add(case_id)
    const inputs = ['turns', 'input', 'question'].filter(k => raw[k] !== undefined)
    if (inputs.length !== 1) error('请只使用 turns、input 或 question 其中一个提供用户问题。')
    const turns = inputs[0] === 'turns' ? raw.turns : [raw[inputs[0]]]
    if (!Array.isArray(turns) || !turns.length || turns.some(t => typeof t !== 'string' || !t.trim())) error('turns 应是至少包含一条非空用户输入的数组。')
    if (raw.conditions !== undefined && raw.test_conditions !== undefined && raw.conditions !== raw.test_conditions) error('conditions 与 test_conditions 不一致，请保留一个。')
    const category = string(raw.category, 'category')
    const expected_tools = list(raw.expected_tools, 'expected_tools')
    const must_do = list(raw.must_do, 'must_do')
    if (expected_tools.length) { must_do.push(`期望使用工具：${expected_tools.join('、')}`); warnings.add('expected_tools 已作为自然语言期望加入评测上下文，不会自动变成硬规则。') }
    const rules = raw.executable_rules ?? []
    if (!Array.isArray(rules)) error('executable_rules 应是数组；不需要硬规则时填写 [] 或省略。')
    for (const rule of rules) {
      if (!object(rule) || Object.keys(rule).some(k => !['type', 'tool', 'target'].includes(k))) error('可执行规则应只包含 type 与相应 tool / target。')
      if (rule.type === 'required_tool') { if (typeof rule.tool !== 'string' || !rule.tool.trim() || rule.target != null) error('required_tool 需要非空 tool。') }
      else if (rule.type === 'expected_intent') { if (typeof rule.target !== 'string' || !rule.target.trim() || rule.tool != null) error('expected_intent 需要非空 target。') }
      else if (rule.type !== 'forbidden_claim' || rule.target !== 'refund_completed_without_evidence' || rule.tool != null) error('不支持这条 executable rule，请保留已支持的明确规则。')
    }
    const judge_method = raw.judge_method ?? 'LLM judge'
    if (!methods.includes(judge_method)) error('judge_method 不受支持，通常省略即可使用 LLM judge。')
    if (['rule', 'tool trace'].includes(judge_method) && !rules.length) error('rule / tool trace 需要明确的 executable_rules；普通题请使用 LLM judge。')
    const draft = { case_id, title: string(raw.title, 'title') || [category, case_id].filter(Boolean).join(' · '),
      turns: turns.map(t => string(t, '用户输入')), test_conditions: string(raw.test_conditions ?? raw.conditions, '测试条件'),
      must_do: [...new Set(must_do)].join('\n'), must_not_do: list(raw.must_not_do, 'must_not_do').join('\n'),
      rules: JSON.stringify(rules, null, 2), judge_method, import_info: { category, expected_tools } }
    for (const field of ['scenario', 'user_id', 'conv_id']) if (raw[field] !== undefined) draft[field] = string(raw[field], field)
    return draft
  })
  return { cases, warnings: [...warnings] }
}

export const importExample = JSON.stringify([{ case_id: 'refund_01', category: '退款', turns: ['我想退款'],
  conditions: '用户没有提供订单号', expected_tools: [], must_do: ['追问订单号', '说明需要核验后才能处理'],
  must_not_do: ['声称退款已完成', '编造订单信息'] }], null, 2)
