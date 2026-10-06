/**
 * streamSSEPost abort 回归测试。
 *
 * 当 input signal abort 时，`@microsoft/fetch-event-source` 的 promise
 * 不是 reject，而是 **resolve**，且不会调用 onclose/onerror。
 * 如果 bridge 只在 catch 中设置 closed，消费循环会永远等待，
 * 形成 deadlock — Stop（server cancel 后 local abort）时 isRunning
 * 无法解除的 durable run cancel 回归根因。
 */
import { describe, expect, it, vi } from 'vitest'

type FesInit = { signal?: AbortSignal }

const fesMock = vi.hoisted(() => ({
  impl: null as null | ((url: string, init: FesInit) => Promise<void>),
}))

vi.mock('@microsoft/fetch-event-source', () => ({
  fetchEventSource: (url: string, init: FesInit) => {
    if (!fesMock.impl) throw new Error('fetchEventSource mock not configured')
    return fesMock.impl(url, init)
  },
}))

import { streamSSEPost } from '../parse-sse'

describe('streamSSEPost abort handling', () => {
  it('abort 时即使 fetch-event-source 只 resolve，也会以 AbortError 结束（防止 deadlock）', async () => {
    // 复现库的真实 abort 行为：不 reject，只 resolve，且不调用 onclose/onerror
    fesMock.impl = (_url, init) =>
      new Promise<void>((resolve) => {
        const signal = init.signal
        if (!signal) return
        if (signal.aborted) {
          resolve()
          return
        }
        signal.addEventListener('abort', () => resolve(), { once: true })
      })

    const controller = new AbortController()
    const stream = streamSSEPost(
      '/api/conversations/x/messages',
      {},
      controller.signal,
      'content_delta',
    )

    const pending = stream.next()
    // 先让消费循环进入等待 resolver，再执行 abort
    await new Promise((resolve) => setTimeout(resolve, 10))
    controller.abort()

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })
})
