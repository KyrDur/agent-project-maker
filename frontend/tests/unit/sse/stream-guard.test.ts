import { describe, it, expect } from 'vitest'
import { createStreamGuard } from '@/lib/sse/stream-guard'

describe('createStreamGuard', () => {
  it('begin() 发放单调递增的 token', () => {
    const guard = createStreamGuard()
    const t1 = guard.begin()
    const t2 = guard.begin()
    const t3 = guard.begin()
    expect(t1).toBe(1)
    expect(t2).toBe(2)
    expect(t3).toBe(3)
  })

  it('只有最近发放的 token 才是 isStale=false', () => {
    const guard = createStreamGuard()
    const t1 = guard.begin()
    expect(guard.isStale(t1)).toBe(false)

    const t2 = guard.begin()
    // t1 已不再是 active stream
    expect(guard.isStale(t1)).toBe(true)
    expect(guard.isStale(t2)).toBe(false)
  })

  it('调用 begin() 时 reset dedup 计数器', () => {
    const guard = createStreamGuard()
    guard.begin()
    expect(guard.isDuplicate('msg-1')).toBe(false)
    expect(guard.isDuplicate('msg-1')).toBe(true)

    // 启动新 stream → 相同 id 再次通过
    guard.begin()
    expect(guard.isDuplicate('msg-1')).toBe(false)
  })

  it('id 为 undefined 时始终通过（兼容旧版 backend）', () => {
    const guard = createStreamGuard()
    guard.begin()
    expect(guard.isDuplicate(undefined)).toBe(false)
    expect(guard.isDuplicate(undefined)).toBe(false)
  })

  it('不同 id 全部通过', () => {
    const guard = createStreamGuard()
    guard.begin()
    expect(guard.isDuplicate('msg-1')).toBe(false)
    expect(guard.isDuplicate('msg-2')).toBe(false)
    expect(guard.isDuplicate('msg-3')).toBe(false)
  })

  it('typical race 场景 — 通过比较 token 丢弃之前 stream 的 stale event', () => {
    const guard = createStreamGuard()

    // 启动 Stream A
    const tokenA = guard.begin()
    expect(guard.isStale(tokenA)).toBe(false)

    // 用户切换到 Stream B（Edit/Regenerate/cancel）
    const tokenB = guard.begin()

    // Stream A 的 generator 异步延迟 yield 的 chunk
    // → consumer 可通过 isStale(tokenA) 验证并丢弃
    expect(guard.isStale(tokenA)).toBe(true)
    expect(guard.isStale(tokenB)).toBe(false)
  })
})
