import { AIMessage, HumanMessage, ToolMessage } from '@langchain/core/messages'
import { describe, expect, it } from 'vitest'
import {
  activeInterruptPayloads,
  appendInterruptToolCallMessages,
  appendResolvedInterruptToolCallMessages,
  interruptPayloadResolvedByMessages,
  resolvedInterruptToolCallsFromDecisions,
  standardPayloadFromInterrupt,
  standardPayloadsFromInterrupts,
  stripInterruptedRawToolCalls,
} from '../hitl-interrupts'
import type { StandardInterruptPayload } from '@/lib/types'

describe('standardPayloadFromInterrupt', () => {
  it('normalizes snake_case HITL interrupt values', () => {
    const payload = standardPayloadFromInterrupt({
      id: 'intr-1',
      value: {
        action_requests: [{ name: 'send_email', args: { to: 'team@example.com' } }],
        review_configs: [{ action_name: 'send_email', allowed_decisions: ['approve', 'reject'] }],
      },
    })

    expect(payload).toEqual({
      interrupt_id: 'intr-1',
      action_requests: [{ name: 'send_email', args: { to: 'team@example.com' } }],
      review_configs: [{ action_name: 'send_email', allowed_decisions: ['approve', 'reject'] }],
    })
  })

  it('在 review_config 中保留会话同意标记（session_consent_eligible）', () => {
    // Skill builder AD-4——如果 backend wire 注入的标记在 parser 中丢失，
    // 批准卡片中的"留出本次会议的剩余时间"选项就不会渲染。
    const payload = standardPayloadFromInterrupt({
      id: 'intr-consent',
      value: {
        action_requests: [{ name: 'test_skill_draft', args: { command: 'python scripts/run.py' } }],
        review_configs: [
          {
            action_name: 'test_skill_draft',
            allowed_decisions: ['approve', 'reject'],
            session_consent_eligible: true,
          },
        ],
      },
    })

    expect(payload?.review_configs).toEqual([
      {
        action_name: 'test_skill_draft',
        allowed_decisions: ['approve', 'reject'],
        session_consent_eligible: true,
      },
    ])
  })

  it('normalizes camelCase HITL interrupt values from LangGraph React', () => {
    const payload = standardPayloadFromInterrupt({
      id: 'intr-camel',
      value: {
        actionRequests: [{ name: 'ask_user', args: { question: '要继续吗？' } }],
        reviewConfigs: [{ actionName: 'ask_user', allowedDecisions: ['respond'] }],
      },
    })

    expect(payload).toEqual({
      interrupt_id: 'intr-camel',
      action_requests: [{ name: 'ask_user', args: { question: '要继续吗？' } }],
      review_configs: [{ action_name: 'ask_user', allowed_decisions: ['respond'] }],
    })
  })

  it('normalizes live input.requested interrupts from LangGraph React', () => {
    const payload = standardPayloadFromInterrupt({
      interruptId: 'intr-live',
      namespace: ['tools:call-1'],
      payload: {
        action_requests: [{ name: 'send_email', args: { to: 'team@example.com' } }],
        review_configs: [{ action_name: 'send_email', allowed_decisions: ['approve'] }],
      },
    })

    expect(payload).toEqual({
      interrupt_id: 'intr-live',
      namespace: ['tools:call-1'],
      action_requests: [{ name: 'send_email', args: { to: 'team@example.com' } }],
      review_configs: [{ action_name: 'send_email', allowed_decisions: ['approve'] }],
    })
  })

  it('adapts native ask_user interrupt values', () => {
    const payload = standardPayloadFromInterrupt({
      id: 'intr-ask',
      value: { type: 'ask_user', question: '哪一边？', options: ['A', 'B'] },
    })

    expect(payload).toEqual({
      interrupt_id: 'intr-ask',
      action_requests: [
        {
          name: 'ask_user',
          args: { question: '哪一边？', options: ['A', 'B'] },
        },
      ],
      review_configs: [{ action_name: 'ask_user', allowed_decisions: ['respond'] }],
    })
  })

  it('keeps the thread namespace when root and thread interrupts share an id', () => {
    const payloads = standardPayloadsFromInterrupts([
      {
        id: 'intr-1',
        value: {
          action_requests: [{ name: 'send_email', args: { to: 'team@example.com' } }],
          review_configs: [{ action_name: 'send_email', allowed_decisions: ['approve'] }],
        },
      },
      {
        interruptId: 'intr-1',
        namespace: ['tools:call-1'],
        payload: {
          action_requests: [{ name: 'send_email', args: { to: 'team@example.com' } }],
          review_configs: [{ action_name: 'send_email', allowed_decisions: ['approve'] }],
        },
      },
    ])

    expect(payloads).toEqual([
      {
        interrupt_id: 'intr-1',
        namespace: ['tools:call-1'],
        action_requests: [{ name: 'send_email', args: { to: 'team@example.com' } }],
        review_configs: [{ action_name: 'send_email', allowed_decisions: ['approve'] }],
      },
    ])
  })
})

describe('appendInterruptToolCallMessages', () => {
  it('appends synthetic assistant tool calls for visible approval cards', () => {
    const messages = [new HumanMessage({ id: 'user-1', content: 'send it' })]
    const projected = appendInterruptToolCallMessages(messages, [
      {
        interrupt_id: 'intr-1',
        action_requests: [{ name: 'send_email', args: { to: 'team@example.com' } }],
        review_configs: [{ action_name: 'send_email', allowed_decisions: ['approve', 'reject'] }],
      },
    ])
    const synthetic = projected[1]

    expect(projected).toHaveLength(2)
    expect(synthetic).toBeInstanceOf(AIMessage)
    expect(AIMessage.isInstance(synthetic) ? synthetic.tool_calls : []).toEqual([
      {
        id: 'intr-1:0',
        name: 'request_approval',
        args: expect.objectContaining({
          approval_id: 'intr-1:0',
          hitl_interrupt_id: 'intr-1',
          tool_name: 'send_email',
        }),
      },
    ])
  })

  it('does not append duplicate synthetic calls when they already exist', () => {
    const existing = new AIMessage({
      id: 'existing',
      content: '',
      tool_calls: [{ id: 'intr-1:0', name: 'request_approval', args: {} }],
    })
    const projected = appendInterruptToolCallMessages(
      [existing],
      [
        {
          interrupt_id: 'intr-1',
          action_requests: [{ name: 'send_email', args: {} }],
          review_configs: [{ action_name: 'send_email', allowed_decisions: ['approve'] }],
        },
      ],
    )

    expect(projected).toEqual([existing])
  })

  it('hydrates the persisted ask_user tool call instead of appending a duplicate interrupt card', () => {
    const existing = new AIMessage({
      id: 'assistant-ask',
      content: [
        {
          type: 'tool_call',
          id: 'toolu-ask',
          name: 'ask_user',
          args: {
            mode: 'option_list',
            question: '请选择水果',
            options: ['苹果', '葡萄', '梨'],
          },
        },
      ],
      tool_calls: [
        {
          id: 'toolu-ask',
          name: 'ask_user',
          args: {
            mode: 'option_list',
            question: '请选择水果',
            options: ['苹果', '葡萄', '梨'],
          },
        },
      ],
    })
    const projected = appendInterruptToolCallMessages(
      [new HumanMessage({ id: 'user-1', content: '请 ask user' }), existing],
      [
        {
          interrupt_id: 'intr-ask',
          action_requests: [
            {
              name: 'ask_user',
              args: {
                mode: 'option_list',
                question: '请选择水果',
                options: ['苹果', '葡萄', '梨'],
              },
            },
          ],
          review_configs: [{ action_name: 'ask_user', allowed_decisions: ['respond'] }],
        },
      ],
    )

    expect(projected).toHaveLength(2)
    expect(AIMessage.isInstance(projected[1]) ? projected[1].tool_calls : []).toEqual([
      expect.objectContaining({
        id: 'toolu-ask',
        name: 'ask_user',
        args: expect.objectContaining({
          approval_id: 'toolu-ask',
          hitl_interrupt_id: 'intr-ask',
          hitl_action_index: 0,
          hitl_total_actions: 1,
        }),
      }),
    ])
  })

  it('treats a missing ask_user options field and an empty options array as equivalent', () => {
    const existing = new AIMessage({
      id: 'assistant-ask-text',
      content: '',
      tool_calls: [
        {
          id: 'toolu-ask-text',
          name: 'ask_user',
          args: { question: '请输入补充说明' },
        },
      ],
    })

    const projected = appendInterruptToolCallMessages(
      [new HumanMessage({ id: 'user-1', content: 'ask for details' }), existing],
      [
        {
          interrupt_id: 'intr-ask-text',
          action_requests: [
            {
              name: 'ask_user',
              args: { question: '请输入补充说明', options: [] },
            },
          ],
          review_configs: [{ action_name: 'ask_user', allowed_decisions: ['respond'] }],
        },
      ],
    )

    expect(projected).toHaveLength(2)
    expect(AIMessage.isInstance(projected[1]) ? projected[1].tool_calls : []).toEqual([
      expect.objectContaining({
        id: 'toolu-ask-text',
        args: expect.objectContaining({
          hitl_interrupt_id: 'intr-ask-text',
          hitl_action_index: 0,
        }),
      }),
    ])
  })

  it('hydrates a persisted ask_user tool call even when the interrupt id already matches', () => {
    const existing = new AIMessage({
      id: 'assistant-ask',
      content: [
        {
          type: 'tool_call',
          id: 'intr-ask:0',
          name: 'ask_user',
          args: {
            mode: 'option_list',
            question: '请选择水果',
            options: ['苹果', '葡萄', '梨'],
          },
        },
      ],
      tool_calls: [
        {
          id: 'intr-ask:0',
          name: 'ask_user',
          args: {
            mode: 'option_list',
            question: '请选择水果',
            options: ['苹果', '葡萄', '梨'],
          },
        },
      ],
    })
    const projected = appendInterruptToolCallMessages(
      [new HumanMessage({ id: 'user-1', content: '请 ask user' }), existing],
      [
        {
          interrupt_id: 'intr-ask',
          action_requests: [
            {
              name: 'ask_user',
              args: {
                mode: 'option_list',
                question: '请选择水果',
                options: ['苹果', '葡萄', '梨'],
              },
            },
          ],
          review_configs: [{ action_name: 'ask_user', allowed_decisions: ['respond'] }],
        },
      ],
    )

    expect(projected).toHaveLength(2)
    expect(projected[1]).not.toBe(existing)
    expect(projected[1]).toMatchObject({
      status: { type: 'requires-action', reason: 'tool-calls' },
    })
    expect(AIMessage.isInstance(projected[1]) ? projected[1].tool_calls : []).toEqual([
      expect.objectContaining({
        id: 'intr-ask:0',
        name: 'ask_user',
        args: expect.objectContaining({
          approval_id: 'intr-ask:0',
          hitl_interrupt_id: 'intr-ask',
          hitl_action_index: 0,
          hitl_total_actions: 1,
        }),
      }),
    ])
  })

  it('binds two arg-equivalent ask_user interrupts to distinct persisted slots', () => {
    const askArgs = {
      mode: 'option_list',
      question: '请选择水果',
      options: ['苹果', '葡萄', '梨'],
    }
    const first = new AIMessage({
      id: 'assistant-ask-1',
      content: '',
      tool_calls: [{ id: 'toolu-ask-1', name: 'ask_user', args: { ...askArgs } }],
    })
    const second = new AIMessage({
      id: 'assistant-ask-2',
      content: '',
      tool_calls: [{ id: 'toolu-ask-2', name: 'ask_user', args: { ...askArgs } }],
    })

    const projected = appendInterruptToolCallMessages(
      [new HumanMessage({ id: 'user-1', content: 'ask twice' }), first, second],
      [
        {
          interrupt_id: 'intr-ask-a',
          action_requests: [{ name: 'ask_user', args: { ...askArgs } }],
          review_configs: [{ action_name: 'ask_user', allowed_decisions: ['respond'] }],
        },
        {
          interrupt_id: 'intr-ask-b',
          action_requests: [{ name: 'ask_user', args: { ...askArgs } }],
          review_configs: [{ action_name: 'ask_user', allowed_decisions: ['respond'] }],
        },
      ],
    )

    // No duplicate card appended; both persisted slots hydrate distinctly.
    expect(projected).toHaveLength(3)
    expect(AIMessage.isInstance(projected[1]) ? projected[1].tool_calls : []).toEqual([
      expect.objectContaining({
        id: 'toolu-ask-1',
        args: expect.objectContaining({ hitl_interrupt_id: 'intr-ask-a' }),
      }),
    ])
    expect(AIMessage.isInstance(projected[2]) ? projected[2].tool_calls : []).toEqual([
      expect.objectContaining({
        id: 'toolu-ask-2',
        args: expect.objectContaining({ hitl_interrupt_id: 'intr-ask-b' }),
      }),
    ])
  })

  it('hydration 时不修改输入数组（immutability contract）', () => {
    const existing = new AIMessage({
      id: 'assistant-ask',
      content: '',
      tool_calls: [
        {
          id: 'toolu-ask',
          name: 'ask_user',
          args: { mode: 'option_list', question: 'Q', options: ['a', 'b'] },
        },
      ],
    })
    const input = [new HumanMessage({ id: 'user-1', content: 'ask' }), existing]
    const inputSnapshot = [...input]

    const projected = appendInterruptToolCallMessages(input, [
      {
        interrupt_id: 'intr-ask',
        action_requests: [
          { name: 'ask_user', args: { mode: 'option_list', question: 'Q', options: ['a', 'b'] } },
        ],
        review_configs: [{ action_name: 'ask_user', allowed_decisions: ['respond'] }],
      },
    ])

    // 原数组及其元素引用保持不变，只在返回数组中替换为新消息。
    expect(input).toEqual(inputSnapshot)
    expect(input[1]).toBe(existing)
    expect(projected[1]).not.toBe(existing)
  })
})

describe('appendResolvedInterruptToolCallMessages', () => {
  it('does not append a synthetic completed ask_user card when the persisted ask_user call is visible', () => {
    const existing = new AIMessage({
      id: 'assistant-ask',
      content: '',
      tool_calls: [
        {
          id: 'toolu-ask',
          name: 'ask_user',
          args: {
            mode: 'option_list',
            question: '请选择水果',
            options: ['苹果', '葡萄', '梨'],
          },
        },
      ],
    })

    const projected = appendResolvedInterruptToolCallMessages(
      [existing],
      [
        {
          toolCall: {
            id: 'intr-ask:0',
            name: 'ask_user',
            args: {
              mode: 'option_list',
              question: '请选择水果',
              options: ['苹果', '葡萄', '梨'],
              hitl_interrupt_id: 'intr-ask',
            },
          },
          result: { decision: 'approved' },
        },
      ],
    )

    expect(projected).toEqual([existing])
  })
})

describe('interruptPayloadResolvedByMessages', () => {
  const payload: StandardInterruptPayload = {
    interrupt_id: 'intr-docx',
    action_requests: [
      {
        name: 'execute_in_skill',
        args: {
          skill_directory: '/skills/docx-document',
          command: 'node scripts/create_langgraph_v3_artifacts.cjs',
        },
      },
    ],
    review_configs: [{ action_name: 'execute_in_skill', allowed_decisions: ['approve'] }],
  }

  it('treats a replayed interrupt as resolved when its real tool result is present', () => {
    const messages = [
      new AIMessage({
        id: 'assistant-tool',
        content: '',
        tool_calls: [
          {
            id: 'call-docx',
            name: 'execute_in_skill',
            args: payload.action_requests[0].args,
          },
        ],
      }),
      new ToolMessage({
        id: 'tool-docx',
        content: 'done',
        tool_call_id: 'call-docx',
      }),
    ]

    expect(interruptPayloadResolvedByMessages(payload, messages)).toBe(true)
  })

  it('keeps an interrupt active before the requested tool result exists', () => {
    const messages = [
      new AIMessage({
        id: 'assistant-tool',
        content: '',
        tool_calls: [
          {
            id: 'call-docx',
            name: 'execute_in_skill',
            args: payload.action_requests[0].args,
          },
        ],
      }),
    ]

    expect(interruptPayloadResolvedByMessages(payload, messages)).toBe(false)
  })

  it('filters replayed interrupts whose real tool result is already in messages', () => {
    const messages = [
      new AIMessage({
        id: 'assistant-tool',
        content: '',
        tool_calls: [
          {
            id: 'call-docx',
            name: 'execute_in_skill',
            args: payload.action_requests[0].args,
          },
        ],
      }),
      new ToolMessage({
        id: 'tool-docx',
        content: 'done',
        tool_call_id: 'call-docx',
      }),
    ]

    expect(activeInterruptPayloads([payload], messages, [])).toEqual([])
  })
})

describe('stripInterruptedRawToolCalls', () => {
  const payload: StandardInterruptPayload = {
    interrupt_id: 'intr-1',
    action_requests: [
      {
        name: 'execute_in_skill',
        args: { skill_directory: '/skills/docx', command: 'node x.cjs' },
      },
    ],
    review_configs: [{ action_name: 'execute_in_skill', allowed_decisions: ['approve', 'reject'] }],
  }

  it('drops the raw tool call an approval card represents + its orphaned result', () => {
    const messages = [
      new AIMessage({
        id: 'm1',
        content: '',
        tool_calls: [
          {
            id: 'call_x',
            name: 'execute_in_skill',
            args: { skill_directory: '/skills/docx', command: 'node x.cjs' },
          },
        ],
      }),
      new ToolMessage({ id: 't1', content: 'OUTPUT', tool_call_id: 'call_x' }),
    ]

    // The empty AIMessage (only the interrupted call) and its result are removed.
    expect(stripInterruptedRawToolCalls(messages, [payload], [])).toHaveLength(0)
  })

  it('keeps non-interrupt tool calls and unrelated messages', () => {
    const messages = [
      new HumanMessage({ id: 'h', content: 'hi' }),
      new AIMessage({
        id: 'm1',
        content: '',
        tool_calls: [
          {
            id: 'call_x',
            name: 'execute_in_skill',
            args: { skill_directory: '/skills/docx', command: 'node x.cjs' },
          },
          { id: 'call_dt', name: 'current_datetime', args: {} },
        ],
      }),
    ]

    const out = stripInterruptedRawToolCalls(messages, [payload], [])
    const ai = out.find((message) => AIMessage.isInstance(message)) as AIMessage
    expect(out).toHaveLength(2)
    expect(ai.tool_calls?.map((toolCall) => toolCall.name)).toEqual(['current_datetime'])
  })

  it('strips a resolved interrupt via its original (unredacted) action, keeping text', () => {
    const secretPayload: StandardInterruptPayload = {
      interrupt_id: 'intr-2',
      action_requests: [{ name: 'edit_file', args: { file_path: 'a.yaml', api_key: 'sk-real' } }],
      review_configs: [
        { action_name: 'edit_file', allowed_decisions: ['approve', 'edit', 'reject'] },
      ],
    }
    const resolved = resolvedInterruptToolCallsFromDecisions(secretPayload, [{ type: 'approve' }])
    const messages = [
      new AIMessage({
        id: 'm1',
        content: '应用修改',
        tool_calls: [
          { id: 'call_e', name: 'edit_file', args: { file_path: 'a.yaml', api_key: 'sk-real' } },
        ],
      }),
    ]

    const out = stripInterruptedRawToolCalls(messages, [], resolved)
    const ai = out[0] as AIMessage
    expect(out).toHaveLength(1)
    expect(ai.tool_calls ?? []).toHaveLength(0)
    expect(String(ai.content)).toContain('应用修改')
  })

  it('is a no-op when there are no interrupts', () => {
    const messages = [
      new AIMessage({
        id: 'm1',
        content: '',
        tool_calls: [{ id: 'c', name: 'execute_in_skill', args: {} }],
      }),
    ]

    const out = stripInterruptedRawToolCalls(messages, [], [])
    expect(out).toHaveLength(1)
    expect((out[0] as AIMessage).tool_calls).toHaveLength(1)
  })

  it('matches the raw tool call regardless of arg key ORDER', () => {
    // Interrupt action args and the raw model tool_call args come from different
    // serialization paths; a plain JSON.stringify could differ by key order.
    const messages = [
      new AIMessage({
        id: 'm1',
        content: '',
        tool_calls: [
          // same args as `payload`, keys in the opposite order
          {
            id: 'call_x',
            name: 'execute_in_skill',
            args: { command: 'node x.cjs', skill_directory: '/skills/docx' },
          },
        ],
      }),
    ]

    expect(stripInterruptedRawToolCalls(messages, [payload], [])).toHaveLength(0)
  })

  it('drops a block-array message with only tool_use blocks, keeps one with a text block', () => {
    const toolBlocks = [
      { type: 'tool_use', id: 'call_x', name: 'execute_in_skill', input: {} },
    ] as unknown as AIMessage['content']
    const textAndTool = [
      { type: 'text', text: '生成文档' },
      { type: 'tool_use', id: 'call_y', name: 'execute_in_skill', input: {} },
    ] as unknown as AIMessage['content']
    const rawArgs = { skill_directory: '/skills/docx', command: 'node x.cjs' }
    const messages = [
      new AIMessage({
        id: 'm1',
        content: toolBlocks,
        tool_calls: [{ id: 'call_x', name: 'execute_in_skill', args: rawArgs }],
      }),
      new AIMessage({
        id: 'm2',
        content: textAndTool,
        tool_calls: [{ id: 'call_y', name: 'execute_in_skill', args: rawArgs }],
      }),
    ]

    const out = stripInterruptedRawToolCalls(messages, [payload], [])
    // m1 (only tool_use) dropped; m2 kept (has a text block) with its tool call stripped.
    expect(out).toHaveLength(1)
    const ai = out[0] as AIMessage
    expect(ai.id).toBe('m2')
    expect(ai.tool_calls ?? []).toHaveLength(0)
  })
})

describe('order-insensitive arg matching', () => {
  it('resolves a payload when the completed tool result args are in a different key order', () => {
    // sameArgs must be order-insensitive: the interrupt action args and the
    // completed model tool_call args come from different serialization paths.
    const payload: StandardInterruptPayload = {
      interrupt_id: 'i',
      action_requests: [{ name: 'send_email', args: { to: 'x@y', subject: 'hi' } }],
      review_configs: [{ action_name: 'send_email', allowed_decisions: ['approve'] }],
    }
    const messages = [
      new AIMessage({
        id: 'm',
        content: '',
        // same args, keys reversed
        tool_calls: [{ id: 'call', name: 'send_email', args: { subject: 'hi', to: 'x@y' } }],
      }),
      new ToolMessage({ id: 't', content: 'sent', tool_call_id: 'call' }),
    ]

    expect(interruptPayloadResolvedByMessages(payload, messages)).toBe(true)
  })
})
