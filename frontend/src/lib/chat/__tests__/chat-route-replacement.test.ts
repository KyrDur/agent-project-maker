import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CHAT_ROUTE_CLEARED_EVENT,
  CHAT_ROUTE_REPLACED_EVENT,
  clearChatRouteReplacement,
  conversationIdFromChatPath,
  isChatRouteReplacedEvent,
  replaceChatRouteWithoutRemount,
} from '../chat-route-replacement'

describe('conversationIdFromChatPath', () => {
  it('从匹配的 agentId 路径中提取 conversationId', () => {
    expect(conversationIdFromChatPath('/agents/agent-1/conversations/conv-9', 'agent-1')).toBe(
      'conv-9',
    )
  })

  it('agentId 不同则返回 null', () => {
    expect(conversationIdFromChatPath('/agents/agent-2/conversations/conv-9', 'agent-1')).toBeNull()
  })

  it('不是聊天路径格式则返回 null', () => {
    expect(conversationIdFromChatPath('/agents/agent-1/settings', 'agent-1')).toBeNull()
    expect(conversationIdFromChatPath('/agents/agent-1/conversations', 'agent-1')).toBeNull()
    expect(
      conversationIdFromChatPath('/agents/agent-1/conversations/conv-1/traces', 'agent-1'),
    ).toBeNull()
    expect(conversationIdFromChatPath('', 'agent-1')).toBeNull()
    expect(conversationIdFromChatPath('/', 'agent-1')).toBeNull()
  })

  it('解码 percent-encoded conversationId', () => {
    expect(
      conversationIdFromChatPath('/agents/agent-1/conversations/conv%20a%2Fb', 'agent-1'),
    ).toBe('conv a/b')
  })

  it('percent-encoded agentId 也按 raw 片段比较（不是解码后比较）', () => {
    // route param 的 agentId 通常已是解码后的值，因此 raw 片段不同则返回 null。
    expect(
      conversationIdFromChatPath('/agents/agent%201/conversations/conv-1', 'agent 1'),
    ).toBeNull()
    expect(conversationIdFromChatPath('/agents/agent%201/conversations/conv-1', 'agent%201')).toBe(
      'conv-1',
    )
  })

  it('malformed percent sequence 回退到 raw 片段', () => {
    expect(conversationIdFromChatPath('/agents/agent-1/conversations/%E0%A4%A', 'agent-1')).toBe(
      '%E0%A4%A',
    )
  })
})

describe('isChatRouteReplacedEvent', () => {
  it('识别具有正确 detail.pathname 的 CustomEvent', () => {
    const event = new CustomEvent(CHAT_ROUTE_REPLACED_EVENT, {
      detail: { pathname: '/agents/a/conversations/c' },
    })
    expect(isChatRouteReplacedEvent(event)).toBe(true)
  })

  it('事件类型不同则为 false', () => {
    const event = new CustomEvent('some-other-event', {
      detail: { pathname: '/agents/a/conversations/c' },
    })
    expect(isChatRouteReplacedEvent(event)).toBe(false)
  })

  it('cleared 事件为 false', () => {
    expect(isChatRouteReplacedEvent(new Event(CHAT_ROUTE_CLEARED_EVENT))).toBe(false)
  })

  it('没有 detail 或 pathname 不是字符串则为 false', () => {
    expect(isChatRouteReplacedEvent(new CustomEvent(CHAT_ROUTE_REPLACED_EVENT))).toBe(false)
    expect(
      isChatRouteReplacedEvent(new CustomEvent(CHAT_ROUTE_REPLACED_EVENT, { detail: {} })),
    ).toBe(false)
    expect(
      isChatRouteReplacedEvent(
        new CustomEvent(CHAT_ROUTE_REPLACED_EVENT, { detail: { pathname: 123 } }),
      ),
    ).toBe(false)
    expect(
      isChatRouteReplacedEvent(
        new CustomEvent(CHAT_ROUTE_REPLACED_EVENT, { detail: { pathname: null } }),
      ),
    ).toBe(false)
  })

  it('detail 为 null 则为 false', () => {
    expect(
      isChatRouteReplacedEvent(new CustomEvent(CHAT_ROUTE_REPLACED_EVENT, { detail: null })),
    ).toBe(false)
  })
})

describe('replaceChatRouteWithoutRemount', () => {
  beforeEach(() => {
    // 将 jsdom 起始路径固定为已知值，以稳定相对路径解析。
    window.history.replaceState(null, '', '/agents/agent-1/conversations/new')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('window.history.replaceState를 (null, "", path)로 호출한다', () => {
    const replaceStateSpy = vi.spyOn(window.history, 'replaceState')
    const path = '/agents/agent-1/conversations/conv-42'

    replaceChatRouteWithoutRemount(path)

    // 회귀: state 인자는 반드시 null이어야 한다(OLD URL의 stale state 재사용 금지).
    // 또한 History.prototype이 아닌 window.history.replaceState(Next monkey-patch
    // wrapper)를 거쳐야 App Router 캐시/pathname이 동기화된다.
    expect(replaceStateSpy).toHaveBeenCalledWith(null, '', path)
  })

  it('detail.pathname을 가진 CHAT_ROUTE_REPLACED_EVENT를 dispatch한다', () => {
    const path = '/agents/agent-1/conversations/conv-42'
    const events: CustomEvent<unknown>[] = []
    const listener = (event: Event) => {
      events.push(event as CustomEvent<unknown>)
    }
    window.addEventListener(CHAT_ROUTE_REPLACED_EVENT, listener)
    try {
      replaceChatRouteWithoutRemount(path)
    } finally {
      window.removeEventListener(CHAT_ROUTE_REPLACED_EVENT, listener)
    }

    expect(events).toHaveLength(1)
    const event = events[0]
    expect(event?.type).toBe(CHAT_ROUTE_REPLACED_EVENT)
    expect(isChatRouteReplacedEvent(event as Event)).toBe(true)
    expect((event?.detail as { pathname?: unknown })?.pathname).toBe(path)
  })

  it('쿼리스트링이 붙은 경로에서도 pathname만 detail에 담는다', () => {
    const events: CustomEvent<unknown>[] = []
    const listener = (event: Event) => {
      events.push(event as CustomEvent<unknown>)
    }
    window.addEventListener(CHAT_ROUTE_REPLACED_EVENT, listener)
    try {
      replaceChatRouteWithoutRemount('/agents/agent-1/conversations/conv-42?from=draft')
    } finally {
      window.removeEventListener(CHAT_ROUTE_REPLACED_EVENT, listener)
    }

    expect((events[0]?.detail as { pathname?: unknown })?.pathname).toBe(
      '/agents/agent-1/conversations/conv-42',
    )
  })

  it('SSR(window 미정의)에서는 no-op으로 안전하게 반환한다', () => {
    const original = globalThis.window
    // @ts-expect-error - SSR 환경 시뮬레이션을 위해 window를 일시적으로 제거한다.
    delete globalThis.window
    try {
      expect(() =>
        replaceChatRouteWithoutRemount('/agents/agent-1/conversations/conv-42'),
      ).not.toThrow()
    } finally {
      globalThis.window = original
    }
  })
})

describe('clearChatRouteReplacement', () => {
  it('CHAT_ROUTE_CLEARED_EVENT를 dispatch한다', () => {
    const events: Event[] = []
    const listener = (event: Event) => {
      events.push(event)
    }
    window.addEventListener(CHAT_ROUTE_CLEARED_EVENT, listener)
    try {
      clearChatRouteReplacement()
    } finally {
      window.removeEventListener(CHAT_ROUTE_CLEARED_EVENT, listener)
    }

    expect(events).toHaveLength(1)
    expect(events[0]?.type).toBe(CHAT_ROUTE_CLEARED_EVENT)
    // cleared 이벤트는 replaced 이벤트가 아니다.
    expect(isChatRouteReplacedEvent(events[0] as Event)).toBe(false)
  })

  it('SSR(window 미정의)에서는 no-op으로 안전하게 반환한다', () => {
    const original = globalThis.window
    // @ts-expect-error - SSR 환경 시뮬레이션을 위해 window를 일시적으로 제거한다.
    delete globalThis.window
    try {
      expect(() => clearChatRouteReplacement()).not.toThrow()
    } finally {
      globalThis.window = original
    }
  })
})
