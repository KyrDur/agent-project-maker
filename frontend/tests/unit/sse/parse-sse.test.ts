import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  createEventDeduper,
  createHeadIndexQueue,
  parseSSEStream,
  streamSSEPost,
} from '@/lib/sse/parse-sse'

const API_BASE = 'http://localhost:8001'

/**
 * Helper: 生成 SSE 格式文本的 ReadableStream。
 */
function createSSEStream(lines: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  const text = lines.join('\n') + '\n'
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text))
      controller.close()
    },
  })
}

/**
 * Helper: 生成按 chunk 分割的 ReadableStream。
 */
function createChunkedStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
}

/**
 * Helper: 收集 parseSSEStream generator 的全部事件。
 */
async function collectEvents<T extends string>(
  body: ReadableStream<Uint8Array>,
  defaultEvent: T,
): Promise<Array<{ event: T; data: unknown; id?: string }>> {
  const events: Array<{ event: T; data: unknown; id?: string }> = []
  for await (const event of parseSSEStream<T>(body, defaultEvent)) {
    events.push(event)
  }
  return events
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('parseSSEStream', () => {
  it('解析单个事件', async () => {
    const body = createSSEStream(['event: content_delta', 'data: {"content":"hello"}', ''])
    const events = await collectEvents(body, 'content_delta')

    expect(events).toHaveLength(1)
    expect(events[0].event).toBe('content_delta')
    expect(events[0].data).toEqual({ content: 'hello' })
  })

  it('解析多个事件序列', async () => {
    const body = createSSEStream([
      'event: message_start',
      'data: {"id":"msg-1"}',
      '',
      'event: content_delta',
      'data: {"content":"Hello "}',
      '',
      'event: content_delta',
      'data: {"content":"world!"}',
      '',
      'event: message_end',
      'data: {"done":true}',
      '',
    ])

    const events = await collectEvents(body, 'content_delta')

    expect(events).toHaveLength(4)
    expect(events.map((e) => e.event)).toEqual([
      'message_start',
      'content_delta',
      'content_delta',
      'message_end',
    ])
    expect(events[0].data).toEqual({ id: 'msg-1' })
    expect(events[1].data).toEqual({ content: 'Hello ' })
    expect(events[2].data).toEqual({ content: 'world!' })
    expect(events[3].data).toEqual({ done: true })
  })

  it('将按 chunk 分割的数据重新拼接 buffer 后解析', async () => {
    const body = createChunkedStream([
      'event: content_delta\ndata: {"conte',
      'nt":"hello"}\n\nevent: message_end\ndata: {"done":true}\n\n',
    ])

    const events = await collectEvents(body, 'content_delta')

    expect(events).toHaveLength(2)
    expect(events[0].event).toBe('content_delta')
    expect(events[0].data).toEqual({ content: 'hello' })
    expect(events[1].event).toBe('message_end')
    expect(events[1].data).toEqual({ done: true })
  })

  it('跳过无效 JSON 行', async () => {
    const body = createSSEStream([
      'event: content_delta',
      'data: {invalid json}',
      '',
      'event: content_delta',
      'data: {"content":"valid"}',
      '',
    ])

    const events = await collectEvents(body, 'content_delta')

    expect(events).toHaveLength(1)
    expect(events[0].data).toEqual({ content: 'valid' })
  })

  it('没有 event 行时使用默认事件类型', async () => {
    const body = createSSEStream(['data: {"content":"no event field"}', ''])

    const events = await collectEvents(body, 'content_delta')

    expect(events).toHaveLength(1)
    expect(events[0].event).toBe('content_delta')
    expect(events[0].data).toEqual({ content: 'no event field' })
  })

  it('空 stream 在没有事件的情况下结束', async () => {
    const body = createSSEStream([])
    const events = await collectEvents(body, 'content_delta')

    expect(events).toEqual([])
  })

  it('解析 id 行并包含到事件中', async () => {
    const body = createSSEStream([
      'event: content_delta',
      'id: msg-abc-1',
      'data: {"delta":"hi"}',
      '',
      'event: content_delta',
      'id: msg-abc-2',
      'data: {"delta":" there"}',
      '',
    ])

    const events = await collectEvents(body, 'content_delta')

    expect(events).toHaveLength(2)
    expect(events[0].id).toBe('msg-abc-1')
    expect(events[1].id).toBe('msg-abc-2')
  })

  it('没有 id 行的事件其 id 为 undefined', async () => {
    const body = createSSEStream([
      'event: content_delta',
      'data: {"delta":"hi"}',
      '',
    ])

    const events = await collectEvents(body, 'content_delta')

    expect(events[0].id).toBeUndefined()
  })

  it('前一个事件的 id 不会继承到下一个事件', async () => {
    const body = createSSEStream([
      'event: content_delta',
      'id: msg-1',
      'data: {"delta":"a"}',
      '',
      'event: content_delta',
      'data: {"delta":"b"}',
      '',
    ])

    const events = await collectEvents(body, 'content_delta')

    expect(events[0].id).toBe('msg-1')
    expect(events[1].id).toBeUndefined()
  })
})

describe('createEventDeduper', () => {
  it('相同 id 第二次进入时判定为重复', () => {
    const dedup = createEventDeduper()

    expect(dedup.isDuplicate('msg-1')).toBe(false)
    expect(dedup.isDuplicate('msg-1')).toBe(true)
  })

  it('不同 id 全部通过', () => {
    const dedup = createEventDeduper()

    expect(dedup.isDuplicate('msg-1')).toBe(false)
    expect(dedup.isDuplicate('msg-2')).toBe(false)
    expect(dedup.isDuplicate('msg-3')).toBe(false)
    expect(dedup.size()).toBe(3)
  })

  it('id 为 undefined 时始终通过（兼容旧版 backend）', () => {
    const dedup = createEventDeduper()

    expect(dedup.isDuplicate(undefined)).toBe(false)
    expect(dedup.isDuplicate(undefined)).toBe(false)
    expect(dedup.size()).toBe(0)
  })

  it('reset() 清空累计的 id', () => {
    const dedup = createEventDeduper()

    dedup.isDuplicate('msg-1')
    dedup.isDuplicate('msg-2')
    dedup.reset()

    expect(dedup.size()).toBe(0)
    // reset 后相同 id 再次通过
    expect(dedup.isDuplicate('msg-1')).toBe(false)
  })
})

describe('streamSSEPost', () => {
  it('通过 POST 请求接收 SSE stream', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        createSSEStream([
          'event: content_delta',
          'data: {"content":"hello"}',
          '',
          'event: message_end',
          'data: {"done":true}',
          '',
        ]),
        { status: 200 },
      ),
    )

    const events: Array<{ event: string; data: unknown }> = []
    for await (const event of streamSSEPost(
      '/api/test/stream',
      { message: 'hi' },
      undefined,
      'content_delta',
    )) {
      events.push(event)
    }

    expect(events).toHaveLength(2)
    expect(events[0].event).toBe('content_delta')
    expect(events[1].event).toBe('message_end')

    // fetchEventSource 会按 SSE 标准添加 ``Accept: text/event-stream``，
    // 因此 header 使用 partial 匹配验证。
    expect(globalThis.fetch).toHaveBeenCalledWith(
      `${API_BASE}/api/test/stream`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ message: 'hi' }),
      }),
    )
  })

  it('head index queue drains FIFO and compacts consumed events', () => {
    const queue = createHeadIndexQueue<{ id: number }>({ compactAfter: 2 })

    queue.push({ id: 1 })
    queue.push({ id: 2 })
    queue.push({ id: 3 })

    expect(queue.length()).toBe(3)
    expect(queue.take()).toEqual({ id: 1 })
    expect(queue.take()).toEqual({ id: 2 })
    expect(queue.length()).toBe(1)
    expect(queue.take()).toEqual({ id: 3 })
    expect(queue.take()).toBeUndefined()
  })

  it('HTTP 错误响应时抛出异常', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('Internal Server Error', { status: 500 }),
    )

    const gen = streamSSEPost('/api/test/stream', {}, undefined, 'content_delta')
    // No structured ``{error: {code, message}}`` body is present, so the
    // low-level stream utility surfaces the transport fallback.
    await expect(gen.next()).rejects.toThrow('HTTP 500')
  })

  // body 为 null 的响应处理已由 fetchEventSource library 内部逻辑负责，
  // 因此 caller side unit test 已无意义 → 删除。
})
