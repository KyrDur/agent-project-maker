import { describe, it, expect } from 'vitest'
import { builderApi } from '@/lib/api/builder'
import { mockBuilderSession, mockAgent } from '../../mocks/fixtures'

describe('builderApi', () => {
  it('start() 调用 POST /api/builder 并返回 session', async () => {
    const session = await builderApi.start('新闻摘要智能体')

    expect(session.id).toBe(mockBuilderSession.id)
    expect(session.user_request).toBe('新闻摘要智能体')
    expect(session.status).toBe('building')
  })

  it('getSession() 通过 GET /api/builder/{id} 查询 session', async () => {
    const session = await builderApi.getSession('builder-session-1')

    expect(session.id).toBe('builder-session-1')
    expect(session.status).toBe(mockBuilderSession.status)
    expect(session.intent).not.toBeNull()
    expect(session.draft_config).not.toBeNull()
  })

  it('confirm() 通过 POST /api/builder/{id}/confirm 创建智能体', async () => {
    const agent = await builderApi.confirm('builder-session-1')

    expect(agent.id).toBe('agent-from-builder')
    expect(agent.name).toBe(mockAgent.name)
  })
})
