import { createEventDeduper } from './parse-sse'

/**
 * Caller-side guard for SSE stream consumers.
 *
 * 阻止两类 race：
 * 1. **Stale events** — 用户通过 builder cancel + 重启、Edit/Regenerate fork
 *    等方式开始新 stream 时，防止旧 stream 的 generator 异步
 *    延迟 yield 的 chunk 污染新 stream 的 state。
 *    AbortController 只能中断 fetch 层，无法阻止已经堆在 buffer 中并从 caller
 *    流出的 chunk。
 * 2. **Duplicate events** — 同一 ``id`` 的 chunk 到达两次时忽略第二次。
 *    后端（``streaming.py``）为每个 chunk 发布 ``{msg_id}-{seq}`` 格式的
 *    unique id，因此 dedup 可安全工作。
 *
 * 用法：
 *   const guardRef = useRef(createStreamGuard())
 *   const token = guardRef.current.begin()
 *   for await (const ev of stream) {
 *     if (guardRef.current.isStale(token)) return
 *     if (guardRef.current.isDuplicate(ev.id)) continue
 *     // handle ev
 *   }
 */
export interface StreamGuard {
  /** 开始新 stream — 发放 version 并 reset dedup counter。consumer 用返回的 token
   *  验证自己是否仍是存活的 stream。 */
  begin(): number
  /** 如果 ``begin()`` 返回的 token 已不是最新 version，则为 stale。 */
  isStale(token: number): boolean
  /** 判断相同 id 的 chunk 是否第二次到达。没有 id 时始终为 false（兼容旧版
   *  后端）。 */
  isDuplicate(eventId: string | undefined): boolean
}

export function createStreamGuard(): StreamGuard {
  let version = 0
  const dedup = createEventDeduper()
  return {
    begin() {
      version += 1
      dedup.reset()
      return version
    },
    isStale(token) {
      return token !== version
    },
    isDuplicate(eventId) {
      return dedup.isDuplicate(eventId)
    },
  }
}
