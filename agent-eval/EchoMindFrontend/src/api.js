const errors = {
  AI_REQUEST_BUSY: ['AI 正在处理这次请求', '请等待当前生成完成，已有草稿保留。'],
  AI_OUTPUT_INVALID: ['生成内容未通过校验', '返回内容、知识 ID 或原文引用不符合要求。已有草稿保留，可以明确重试；重试会增加请求。'],
  AI_INPUT_TOO_LARGE: ['本次资料过多', '请缩小知识或单题轨迹范围后再生成，系统不会静默截断依据。'],
  EMBEDDING_MODEL_UNAVAILABLE: ['本地语义模型不可用', '请检查首次模型下载的网络、缓存文件和运行依赖；系统不会自动改用词汇检索。'],
  EMBEDDING_INPUT_TOO_LONG: ['内容超过语义模型长度限制', '每段最多 256 Token（含特殊标记）。请缩短问题，或减小知识切分长度后重新建索引；系统不会静默截断。'],
  CHAT_CONFIGURATION_CHANGED: ['对话配置已变化', '请开始新对话，使用当前知识版本与模型配置。'],
  CONVERSATION_BUSY: ['这段对话正在回答', '请等待当前回答完成后再发送。'],
  CONVERSATION_LIMIT_REACHED: ['本段对话已达到 30 次', '请开始新对话。历史记录仍保留。'],
  WORKSPACE_UNAVAILABLE: ['工作区身份已失效', '请刷新页面建立新的独立工作区。旧记录不会自动转入新工作区。'],
  WORKSPACE_CAPACITY_REACHED: ['服务暂时繁忙', '当前工作区容量已满，请稍后再试。'],
  WORKSPACE_BUSY: ['实验服务暂时繁忙', '服务器同时运行的实验已达到上限，请稍后重试。'],
  WORKSPACE_ORIGIN_REJECTED: ['请求来源不受支持', '请从本站页面操作。'],
  PUBLIC_PROVIDER_ENDPOINT_NOT_ALLOWED: ['此模型地址暂不支持公开访问', '公开站点仅允许已配置的模型服务域名和 HTTPS。可使用 DeepSeek、百炼、Kimi、OpenAI、Claude、硅基流动或智谱官方地址。'],
  NARRATIVE_VALIDATION_FAILED: ['材料校验未通过', '请检查配置冲突、未验证业绩或补充判断。未通过的结果不会保存为正式材料。'],
  AUTH_FAILED: ['模型认证失败', '请检查 API Key，并重新配置会话。'],
  MODEL_NOT_FOUND: ['模型不存在', '请检查模型名称及 Base URL。'],
  RATE_LIMITED: ['模型请求受限', '请稍后重试，或检查服务额度。'],
  TIMEOUT: ['模型请求超时', '请稍后重试，或在高级设置中调整超时。'],
  NETWORK_ERROR: ['模型网络连接失败', '请检查模型服务地址与网络。'],
  INVALID_RESPONSE: ['模型响应无法用于评测', '返回格式不符合本次请求协议。'],
  PROVIDER_ERROR: ['模型服务异常', '请检查兼容服务的参数支持，或稍后重试。'],
  CALL_BUDGET_EXCEEDED: ['请求预算耗尽', '请检查本次调用预算；已有失败不会变成有效分数。'],
  CREDENTIAL_UNAVAILABLE: ['模型凭据需要重新输入', '后端重启或删除会话后，Key 不会恢复。'],
  CONNECTION_NOT_VERIFIED: ['请先测试模型连接', '文本连接成功后才能开始评测。'],
  TEXT_CONNECTION_NOT_READY: ['请先测试模型连接', '连接成功后才能测试工具能力。'],
  TOOL_CALL_UNSUPPORTED: ['模型不支持工具调用', '该模型可以普通对话，但当前无法运行客服评测。'],
}

export function describeError(code, status = 0) {
  if (errors[code]) return { title: errors[code][0], message: errors[code][1] }
  if (status === 409) return { title: '操作条件尚未满足', message: '请同步后端状态，检查确认、版本、修改或复核条件。' }
  if (status === 422) return { title: '填写内容需要检查', message: '请检查必填项、规则格式与模型参数。' }
  if (status === 404) return { title: '记录无法找到', message: '请检查后端数据目录，或从历史实验重新打开。' }
  if (status === 503) return { title: '实验后端暂不可用', message: '请启动 Python experiments.app 服务。' }
  return { title: '无法连接实验 API', message: '请检查 Python 后端与前端代理。请求可能已保存，可点击“同步状态”确认。' }
}
export class ApiError extends Error {
  constructor(code, status) {
    const safe = describeError(code, status)
    super(safe.message)
    this.title = safe.title
    this.status = status
    // Never retain/echo the server body, request body, URL, or arbitrary exception text.
    this.code = Object.hasOwn(errors, code) ? code : 'API_ERROR'
  }
}
export function createApi(fetcher = globalThis.fetch) {
  async function request(path, body) {
    let response
    try {
      response = await fetcher('/api/experiments' + path, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        cache: 'no-store',
      })
    } catch { throw new ApiError(null, 0) }
    let data
    try { data = await response.json() } catch { throw new ApiError(null, response.status) }
    if (!response.ok) throw new ApiError(typeof data.detail === 'string' ? data.detail : null, response.status)
    return data
  }
  return {
    get: path => request(path),
    post: (path, body = {}) => request(path, body),
    async list(group) {
      let offset = 0, items = [], page
      do {
        page = await request(`/artifacts/${group}?offset=${offset}&limit=100`)
        items.push(...page.items)
        offset += page.items.length
      } while (offset < page.total && page.items.length)
      return items
    },
  }
}
export const api = createApi()

// Complete cookie creation before concurrent history requests. The public ref
// only clears stale UI pointers; it never authorizes backend access.
export async function prepareWorkspace(storage = globalThis.localStorage, fetcher = globalThis.fetch) {
  let response, data
  try {
    response = await fetcher('/api/experiments/workspace', {credentials: 'same-origin', cache: 'no-store'})
    data = await response.json()
  } catch { throw new ApiError(null, 0) }
  if (!response.ok) throw new ApiError(data.detail, response.status)
  if (data.isolated) {
    if (typeof data.workspace_ref !== 'string' || !/^[a-f0-9]{64}$/.test(data.workspace_ref)) throw new ApiError(null, 0)
    try {
      if (storage.getItem('echomind.browser-workspace') !== data.workspace_ref) {
        for (const key of ['echomind.workspace.v1','echomind.retrieval.v1','echomind.career.v1','agenteval.practice.v1']) storage.removeItem(key)
        storage.setItem('echomind.browser-workspace', data.workspace_ref)
      }
    } catch { /* Backend cookie still enforces privacy when storage is disabled. */ }
  }
  return data
}
