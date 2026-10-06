import { describe, expect, it } from 'vitest'
import { protocolSubagentNames } from '../subagent-names-events'

describe('protocolSubagentNames', () => {
  it('从 moldy.subagent_names custom 事件中解析映射', () => {
    const event = {
      method: 'custom',
      event_id: 'run-1:subagent_names',
      seq: 1,
      params: {
        data: {
          name: 'moldy.subagent_names',
          payload: { names: { agent_11111111: '调研员', agent_22222222: '作者' } },
        },
      },
    }

    expect(protocolSubagentNames(event)).toEqual({
      agent_11111111: '调研员',
      agent_22222222: '作者',
    })
  })

  it('也识别 custom: prefixed method 形式', () => {
    const event = {
      method: 'custom:moldy.subagent_names',
      params: { data: { payload: { names: { a: 'A' } } } },
    }

    expect(protocolSubagentNames(event)).toEqual({ a: 'A' })
  })

  it('忽略其他 custom 事件（compaction 等）', () => {
    const event = {
      method: 'custom',
      params: { data: { name: 'moldy.compaction', payload: { state: 'running' } } },
    }

    expect(protocolSubagentNames(event)).toBeNull()
  })

  it('排除空字符串/非字符串 display name', () => {
    const event = {
      method: 'custom',
      params: {
        data: { name: 'moldy.subagent_names', payload: { names: { a: '  ', b: 42, c: '作者' } } },
      },
    }

    expect(protocolSubagentNames(event)).toEqual({ c: '作者' })
  })

  it('names 为空时返回 null', () => {
    const event = {
      method: 'custom',
      params: { data: { name: 'moldy.subagent_names', payload: {} } },
    }

    expect(protocolSubagentNames(event)).toBeNull()
  })
})
