import { describe, expect, it } from 'vitest'
import type { BaseMessage } from '@langchain/core/messages'
import { usageFromMessage } from '../usage-normalization'

// v3 消息有两个 usage 来源（native usage_metadata=只有 token，enriched
// additional_kwargs.metadata.usage=token+cost+timing）时，token 以 native 为准，
// 但 cost/timing 需要从 enriched 补全。如果 usageFromMessage 只看 native
// 就提前返回，会丢失 streaming timing；这里做回归保护。
function asMessage(value: Record<string, unknown>): BaseMessage {
  return value as unknown as BaseMessage
}

describe('usageFromMessage——合并 streaming timing', () => {
  it('合并 native token + enriched(additional_kwargs) 的 timing/cost', () => {
    const message = asMessage({
      usage_metadata: { input_tokens: 100, output_tokens: 20 },
      additional_kwargs: {
        metadata: {
          usage: {
            prompt_tokens: 100,
            completion_tokens: 20,
            estimated_cost: 0.5,
            ttft_ms: 300,
            generation_ms: 1200,
            tokens_per_second: 25,
          },
        },
      },
    })

    const usage = usageFromMessage(message)
    expect(usage).not.toBeNull()
    expect(usage?.prompt_tokens).toBe(100)
    expect(usage?.completion_tokens).toBe(20)
    expect(usage?.ttft_ms).toBe(300)
    expect(usage?.generation_ms).toBe(1200)
    expect(usage?.tokens_per_second).toBe(25)
    expect(usage?.estimated_cost).toBe(0.5)
  })

  it('没有 enriched 时只返回 native usage_metadata（无 timing）', () => {
    const usage = usageFromMessage(
      asMessage({ usage_metadata: { input_tokens: 5, output_tokens: 1 } }),
    )
    expect(usage?.prompt_tokens).toBe(5)
    expect(usage?.ttft_ms).toBeUndefined()
    expect(usage?.tokens_per_second).toBeUndefined()
  })

  it('有 native cost 时保留，只有缺失时才用 enriched cost 补全', () => {
    const usage = usageFromMessage(
      asMessage({
        usage_metadata: { input_tokens: 10, output_tokens: 2, estimated_cost: 0.9 },
        additional_kwargs: {
          metadata: { usage: { prompt_tokens: 10, completion_tokens: 2, estimated_cost: 0.1 } },
        },
      }),
    )
    expect(usage?.estimated_cost).toBe(0.9)
  })
})
