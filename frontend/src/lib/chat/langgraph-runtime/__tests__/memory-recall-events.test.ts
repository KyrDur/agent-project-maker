import { describe, expect, it } from 'vitest'
import { protocolMemoryRecall } from '../memory-recall-events'

describe('protocolMemoryRecall', () => {
  it('从 moldy.memory_recalled custom 事件中解析 brief 列表', () => {
    const parsed = protocolMemoryRecall({
      method: 'custom',
      event_id: 'run-1:memory_recalled',
      params: {
        data: {
          name: 'moldy.memory_recalled',
          payload: {
            memories: [
              { id: 'm1', scope: 'user', content: '偏好中文' },
              { id: 'm2', scope: 'agent', content: '整理成表格' },
            ],
          },
        },
      },
    })
    expect(parsed).toEqual([
      { id: 'm1', scope: 'user', content: '偏好中文' },
      { id: 'm2', scope: 'agent', content: '整理成表格' },
    ])
  })

  it('也识别 custom:moldy.memory_recalled method 形式', () => {
    const parsed = protocolMemoryRecall({
      method: 'custom:moldy.memory_recalled',
      params: {
        data: { payload: { memories: [{ scope: 'user', content: '注释' }] } },
      },
    })
    expect(parsed).toEqual([{ id: undefined, scope: 'user', content: '注释' }])
  })

  it('过滤 scope 或 content 无效的项', () => {
    const parsed = protocolMemoryRecall({
      method: 'custom',
      params: {
        data: {
          name: 'moldy.memory_recalled',
          payload: {
            memories: [
              { scope: 'user', content: '有效' },
              { scope: 'other', content: 'scope 无效' },
              { scope: 'agent', content: '   ' },
              'not-a-record',
            ],
          },
        },
      },
    })
    expect(parsed).toEqual([{ id: undefined, scope: 'user', content: '有效' }])
  })

  it('其他 custom 事件（subagent_names 等）返回 null', () => {
    expect(
      protocolMemoryRecall({
        method: 'custom',
        params: { data: { name: 'moldy.subagent_names', payload: { names: {} } } },
      }),
    ).toBeNull()
    expect(
      protocolMemoryRecall({
        method: 'messages',
        params: { data: { chunk: 'x' } },
      }),
    ).toBeNull()
  })

  it('memories 为空时返回 null（不显示 chip）', () => {
    expect(
      protocolMemoryRecall({
        method: 'custom',
        params: { data: { name: 'moldy.memory_recalled', payload: { memories: [] } } },
      }),
    ).toBeNull()
  })
})
