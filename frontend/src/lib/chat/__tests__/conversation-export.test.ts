import { describe, expect, it } from 'vitest'
import type { Message, MessagesEnvelope } from '@/lib/types'
import {
  conversationToJson,
  conversationToMarkdown,
  exportFilename,
  type ExportLabels,
} from '../conversation-export'

const labels: ExportLabels = {
  roleUser: '用户',
  roleAssistant: '助理',
  roleTool: '工具',
  toolCalls: '工具调用',
  attachments: '附',
  exportedAt: '导出于',
}

function msg(partial: Partial<Message>): Message {
  return {
    id: 'm1',
    conversation_id: 'c1',
    role: 'user',
    content: '',
    tool_calls: null,
    tool_call_id: null,
    created_at: '2026-07-02T00:00:00Z',
    ...partial,
  } as Message
}

describe('conversationToMarkdown', () => {
  it('渲染标题/header/role 标签/content', () => {
    const md = conversationToMarkdown(
      [
        msg({ role: 'user', content: '你好' }),
        msg({ id: 'm2', role: 'assistant', content: '很高兴见到你' }),
      ],
      { title: '测试对话', exportedAt: '2026-07-02T00:00:00Z', labels },
    )
    expect(md).toContain('# 测试对话')
    expect(md).toContain('## 用户 · 2026-07-02T00:00:00Z')
    expect(md).toContain('你好')
    expect(md).toContain('## 助理')
    expect(md).toContain('很高兴见到你')
  })

  it('渲染 tool_calls 和 attachments', () => {
    const md = conversationToMarkdown(
      [
        msg({
          role: 'assistant',
          content: '',
          tool_calls: [{ name: 'web_search', args: { q: 'hi' } }],
          attachments: [
            {
              id: 'a1',
              filename: 'file.png',
              mime_type: 'image/png',
              size_bytes: 1,
              url: 'https://x/f.png',
            },
          ],
        }),
      ],
      { title: 't', exportedAt: 'now', labels },
    )
    expect(md).toContain('web_search')
    expect(md).toContain('[file.png](https://x/f.png)')
  })
})

describe('conversationToJson', () => {
  it('将 envelope 序列化为可解析的 JSON', () => {
    const envelope = { messages: [msg({ content: 'hi' })] } as MessagesEnvelope
    const json = conversationToJson(envelope)
    expect(JSON.parse(json).messages[0].content).toBe('hi')
  })
})

describe('exportFilename', () => {
  it('生成 conversation-{id}-{ts}.{ext} 格式', () => {
    expect(exportFilename('c1', 'md', '2026-07-02T00-00-00')).toBe(
      'conversation-c1-2026-07-02T00-00-00.md',
    )
    expect(exportFilename('c1', 'json', '2026-07-02T00-00-00')).toBe(
      'conversation-c1-2026-07-02T00-00-00.json',
    )
  })
})
