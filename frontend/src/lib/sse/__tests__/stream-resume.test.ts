/**
 * HiTL resume wire body shape 回归守卫 — 验证 `streamResumeDecisions`
 * 是否发送 `{decisions: [...]}` body。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Decision } from '@/lib/types'
import { streamResumeDecisions } from '../stream-resume'

// ---------------------------------------------------------------------------
// 将 fetchEventSource 替换为 fake — 只捕获 body 就足够（stream 本身为空
// generator 并立即 close）。不验证真实网络/SSE parsing。
// ---------------------------------------------------------------------------

interface CapturedCall {
  url: string
  method: string
  body: unknown
  headers: Record<string, string>
}

const captured: CapturedCall[] = []

vi.mock('@microsoft/fetch-event-source', () => ({
  fetchEventSource: vi.fn(
    async (
      url: string,
      init: {
        method?: string
        body?: string
        headers?: Record<string, string>
        onopen?: (response: Response) => Promise<void> | void
        onmessage?: (msg: { event: string; data: string; id?: string }) => void
        onclose?: () => void
        onerror?: (err: unknown) => void
      },
    ) => {
      captured.push({
        url,
        method: init.method ?? 'GET',
        body: init.body ? JSON.parse(init.body as string) : undefined,
        headers: init.headers ?? {},
      })
      // 模拟 200 响应 → 通过 onopen → 立即 onclose。
      const fakeResponse = {
        ok: true,
        status: 200,
        headers: { get: () => null },
      } as unknown as Response
      await init.onopen?.(fakeResponse)
      init.onclose?.()
    },
  ),
}))

async function drain<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = []
  for await (const v of gen) out.push(v)
  return out
}

beforeEach(() => {
  captured.length = 0
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('streamResumeDecisions', () => {
  it('body 会精确序列化为 {decisions: [...]} 形式', async () => {
    const decisions: Decision[] = [
      { type: 'approve' },
      {
        type: 'edit',
        edited_action: { name: 'send_email', args: { to: 'x@y' } },
      },
      { type: 'reject', message: 'not allowed' },
      { type: 'respond', message: 'user reply' },
    ]

    await drain(streamResumeDecisions('conv-1', decisions))

    expect(captured).toHaveLength(1)
    expect(captured[0].method).toBe('POST')
    expect(captured[0].url).toContain('/api/conversations/conv-1/messages/resume')
    expect(captured[0].body).toEqual({ decisions })
    // 标准 wire 绝不能同时发送 legacy `response` 字段。
    expect(captured[0].body).not.toHaveProperty('response')
  })

  it('空 decisions 数组也原样发送（validation 交给 middleware）', async () => {
    await drain(streamResumeDecisions('conv-2', []))
    expect(captured[0].body).toEqual({ decisions: [] })
  })

  it('设置 Content-Type: application/json header', async () => {
    await drain(streamResumeDecisions('conv-3', [{ type: 'approve' }]))
    expect(captured[0].headers['Content-Type']).toBe('application/json')
    expect(captured[0].headers['Accept']).toBe('text/event-stream')
  })
})
