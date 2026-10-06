import { describe, expect, it, vi } from 'vitest'
import { withAutoResume } from '../with-auto-resume'
import { StreamApiError, StreamHttpError } from '../parse-sse'

interface TestEvent {
  id?: string
  payload: number
}

async function* fromArray(events: TestEvent[]): AsyncGenerator<TestEvent> {
  for (const ev of events) yield ev
}

async function* throwAfter(events: TestEvent[], err: unknown): AsyncGenerator<TestEvent> {
  for (const ev of events) yield ev
  throw err
}

async function collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = []
  for await (const v of gen) out.push(v)
  return out
}

describe('withAutoResume', () => {
  it('primary 正常结束时不调用 resume', async () => {
    const resume = vi.fn(() => null)
    const result = await collect(
      withAutoResume(
        () =>
          fromArray([
            { id: 'a-1', payload: 1 },
            { id: 'a-2', payload: 2 },
          ]),
        resume,
      ),
    )
    expect(result.map((e) => e.payload)).toEqual([1, 2])
    expect(resume).not.toHaveBeenCalled()
  })

  it('primary throw 时带着 lastEventId 调用 resume 并继续接收', async () => {
    const resume = vi.fn((lastEventId, attempt) => {
      expect(lastEventId).toBe('a-2')
      expect(attempt).toBe(1)
      return fromArray([
        { id: 'a-3', payload: 3 },
        { id: 'a-4', payload: 4 },
      ])
    })
    const result = await collect(
      withAutoResume<TestEvent>(
        () =>
          throwAfter(
            [
              { id: 'a-1', payload: 1 },
              { id: 'a-2', payload: 2 },
            ],
            new TypeError('network'),
          ),
        resume,
        { backoffMs: [0] },
      ),
    )
    expect(result.map((e) => e.payload)).toEqual([1, 2, 3, 4])
    expect(resume).toHaveBeenCalledOnce()
  })

  it('回调调用顺序：onReconnecting → 第一个 event → onReconnected', async () => {
    const calls: string[] = []
    await collect(
      withAutoResume<TestEvent>(
        () => throwAfter([{ id: 'a-1', payload: 1 }], new TypeError('boom')),
        () => fromArray([{ id: 'a-2', payload: 2 }]),
        {
          backoffMs: [0],
          onReconnecting: (attempt) => calls.push(`reconnecting:${attempt}`),
          onReconnected: () => calls.push('reconnected'),
          onFailed: () => calls.push('failed'),
        },
      ),
    )
    expect(calls).toEqual(['reconnecting:1', 'reconnected'])
  })

  it('超过 maxAttempts 时，先 onFailed 再 throw', async () => {
    const onFailed = vi.fn()
    const onReconnecting = vi.fn()
    await expect(
      collect(
        withAutoResume<TestEvent>(
          () => throwAfter([], new TypeError('boom')),
          () => {
            return (async function* () {
              throw new TypeError('still broken')
            })()
          },
          { backoffMs: [0], maxAttempts: 2, onReconnecting, onFailed },
        ),
      ),
    ).rejects.toThrow()
    expect(onReconnecting).toHaveBeenCalledTimes(2)
    expect(onFailed).toHaveBeenCalledOnce()
  })

  it('4xx StreamHttpError 不 retry（RESUME_NOT_FOUND/INTERRUPT_PENDING）', async () => {
    const resume = vi.fn(() => fromArray([{ id: 'a-2', payload: 2 }]))
    const onFailed = vi.fn()
    await expect(
      collect(
        withAutoResume<TestEvent>(
          () => throwAfter([], new StreamHttpError(404, 'Not Found')),
          resume,
          { backoffMs: [0], onFailed },
        ),
      ),
    ).rejects.toBeInstanceOf(StreamHttpError)
    expect(resume).not.toHaveBeenCalled()
    expect(onFailed).toHaveBeenCalledOnce()
  })

  it('RUN_ATTACH_RETRY StreamApiError 409 会 retry', async () => {
    const resume = vi.fn(() => fromArray([{ id: 'a-2', payload: 2 }]))
    const result = await collect(
      withAutoResume<TestEvent>(
        () =>
          throwAfter(
            [{ id: 'a-1', payload: 1 }],
            new StreamApiError(409, 'RUN_ATTACH_RETRY', 'retry'),
          ),
        resume,
        { backoffMs: [0] },
      ),
    )
    expect(result.map((event) => event.payload)).toEqual([1, 2])
    expect(resume).toHaveBeenCalledOnce()
  })

  it('RESUME_NOT_FOUND StreamApiError 404 不 retry', async () => {
    const resume = vi.fn(() => fromArray([{ id: 'a-2', payload: 2 }]))
    const onFailed = vi.fn()
    await expect(
      collect(
        withAutoResume<TestEvent>(
          () => throwAfter([], new StreamApiError(404, 'RESUME_NOT_FOUND', 'missing')),
          resume,
          { backoffMs: [0], onFailed },
        ),
      ),
    ).rejects.toBeInstanceOf(StreamApiError)
    expect(resume).not.toHaveBeenCalled()
    expect(onFailed).toHaveBeenCalledOnce()
  })

  it('AbortError 不 retry，原样传播', async () => {
    const resume = vi.fn(() => fromArray([{ id: 'a-2', payload: 2 }]))
    await expect(
      collect(
        withAutoResume<TestEvent>(
          () => throwAfter([], new DOMException('Aborted', 'AbortError')),
          resume,
          { backoffMs: [0] },
        ),
      ),
    ).rejects.toBeInstanceOf(DOMException)
    expect(resume).not.toHaveBeenCalled()
  })

  it('signal.aborted 时不 retry', async () => {
    const controller = new AbortController()
    controller.abort()
    const resume = vi.fn(() => fromArray([{ id: 'a-2', payload: 2 }]))
    await expect(
      collect(
        withAutoResume<TestEvent>(() => throwAfter([], new TypeError('boom')), resume, {
          backoffMs: [0],
          signal: controller.signal,
        }),
      ),
    ).rejects.toThrow()
    expect(resume).not.toHaveBeenCalled()
  })

  it('resumeFactory 返回 null 后不再 retry', async () => {
    const onFailed = vi.fn()
    await expect(
      collect(
        withAutoResume<TestEvent>(
          () => throwAfter([{ id: 'a-1', payload: 1 }], new TypeError('boom')),
          () => null,
          { backoffMs: [0], onFailed },
        ),
      ),
    ).rejects.toThrow()
    expect(onFailed).toHaveBeenCalledOnce()
  })

  it('重试 stream 正常结束后如果再次 throw，attempt 会 reset，并重新尝试直到 max', async () => {
    const sources: AsyncGenerator<TestEvent>[] = [
      throwAfter([{ id: 'a-1', payload: 1 }], new TypeError('1')),
      throwAfter([{ id: 'a-2', payload: 2 }], new TypeError('2')),
      throwAfter([{ id: 'a-3', payload: 3 }], new TypeError('3')),
      fromArray([{ id: 'a-4', payload: 4 }]),
    ]
    let primaryConsumed = false
    const primary = () => {
      if (primaryConsumed) throw new Error('primary called twice')
      primaryConsumed = true
      return sources[0]
    }
    let resumeIdx = 1
    const result = await collect(
      withAutoResume<TestEvent>(
        primary,
        () => {
          const next = sources[resumeIdx]
          resumeIdx += 1
          return next
        },
        { backoffMs: [0], maxAttempts: 5 },
      ),
    )
    expect(result.map((e) => e.payload)).toEqual([1, 2, 3, 4])
  })

  it('backoff sleep 过程中 abort 时，不 retry，立即 throw', async () => {
    const controller = new AbortController()
    const onFailed = vi.fn()
    const resume = vi.fn(() => fromArray([{ id: 'a-2', payload: 2 }]))
    const promise = collect(
      withAutoResume<TestEvent>(() => throwAfter([], new TypeError('boom')), resume, {
        backoffMs: [10000],
        signal: controller.signal,
        onFailed,
      }),
    )
    // 确保 backoff 已开始 — 让出一个 microtask 后 abort。
    await Promise.resolve()
    controller.abort()
    await expect(promise).rejects.toBeInstanceOf(DOMException)
    expect(resume).not.toHaveBeenCalled()
    expect(onFailed).toHaveBeenCalledOnce()
  })

  it('resumeFactory sync throw 时原样传播给 caller', async () => {
    const onFailed = vi.fn()
    const fatal = new Error('factory fatal')
    await expect(
      collect(
        withAutoResume<TestEvent>(
          () => throwAfter([], new TypeError('boom')),
          () => {
            throw fatal
          },
          { backoffMs: [0], onFailed },
        ),
      ),
    ).rejects.toBe(fatal)
  })

  it('primary 在 0 个 event 后 throw 时，resume 仍以 lastEventId=undefined 调用', async () => {
    const resume = vi.fn((lastEventId) => {
      expect(lastEventId).toBeUndefined()
      return fromArray([{ id: 'a-1', payload: 1 }])
    })
    const result = await collect(
      withAutoResume<TestEvent>(() => throwAfter([], new TypeError('boom')), resume, {
        backoffMs: [0],
      }),
    )
    expect(result.map((e) => e.payload)).toEqual([1])
    expect(resume).toHaveBeenCalledOnce()
  })

  it('没有 id 的 event 不更新 lastEventId', async () => {
    const resume = vi.fn((lastEventId) => {
      expect(lastEventId).toBe('a-1')
      return fromArray([{ id: 'a-2', payload: 2 }])
    })
    await collect(
      withAutoResume<TestEvent>(
        () => throwAfter([{ id: 'a-1', payload: 1 }, { payload: 99 }], new TypeError('boom')),
        resume,
        { backoffMs: [0] },
      ),
    )
    expect(resume).toHaveBeenCalledOnce()
  })
})
