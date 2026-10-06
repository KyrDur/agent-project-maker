import type { APIRequestContext } from '@playwright/test'
import { API_BASE, apiPostJson, isRecord, loginApi, test, type CsrfHeaders } from '../fixtures'
import { sendMessage } from '../langgraph-v3-helpers'
import {
  capture,
  DESKTOP_VIEWPORT,
  scriptedModelId,
  settle,
  warmUpChatRoute,
} from './_capture-helpers'

/**
 * Wave 1 — hero flows (the two demo videos): natural-language agent creation
 * (builder) and a multi-turn daily conversation exercising chat components.
 * Step-by-step captures. Gated by E2E_CAPTURE_TOUR=1.
 */

const WAVE = 'wave1-flows'

async function createAgent(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
  modelId: string,
): Promise<string> {
  const agent = await apiPostJson(request, `${API_BASE}/api/agents`, csrfHeaders, {
    name: 'GPT — 日常助手',
    description: '帮助处理日程、信息和推荐的个人助手',
    system_prompt: '你是友好的个人助手。对用户的日常问题给出简洁且有帮助的回答。',
    model_id: modelId,
  })
  if (!isRecord(agent) || typeof agent.id !== 'string') throw new Error('agent create failed')
  return agent.id
}

test.describe('Wave 1 — hero flow captures', () => {
  test.skip(process.env.E2E_CAPTURE_TOUR !== '1', 'Set E2E_CAPTURE_TOUR=1 to run the capture tour')

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(DESKTOP_VIEWPORT)
  })

  // Compile the heavy chat conversation route once, out of the per-test budget,
  // so the daily-conversation test's 240s is free for the turns rather than being
  // eaten by the cold compile. Raise the hook timeout first — the config default
  // (60s) is shorter than a cold compile.
  test.beforeAll(async ({ browser }) => {
    test.setTimeout(300_000)
    await warmUpChatRoute(browser)
  })

  test('daily conversation — multi-turn chat components', async ({ page, request }) => {
    test.setTimeout(240_000)
    const csrfHeaders = await loginApi(request)
    const modelId = await scriptedModelId(request)
    const agentId = await createAgent(request, csrfHeaders, modelId)

    try {
      const convo = await apiPostJson(
        request,
        `${API_BASE}/api/agents/${agentId}/conversations`,
        csrfHeaders,
        { title: '今日助手对话' },
      )
      if (!isRecord(convo) || typeof convo.id !== 'string') throw new Error('conversation failed')

      // Cold-compile tolerant first navigation.
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        try {
          await page.goto(`/agents/${agentId}/conversations/${convo.id}`, {
            waitUntil: 'domcontentloaded',
            timeout: 180_000,
          })
          break
        } catch (error) {
          if (attempt === 2) throw error
          await page.waitForTimeout(2_000)
        }
      }
      await settle(page)
      await capture(page, WAVE, '01-empty-greeting.png')

      const settleStream = async (): Promise<void> => {
        const stop = page.locator('[data-moldy-stop-button="true"]:visible').last()
        await stop.waitFor({ state: 'visible', timeout: 8_000 }).catch(() => {})
        await stop.waitFor({ state: 'hidden', timeout: 90_000 }).catch(() => {})
        await page.waitForTimeout(800)
      }

      // Turn 0 — a warm natural greeting reply (marker-driven, so the opener reads
      // like a real daily assistant instead of the bare scripted sentinel).
      await sendMessage(page, 'E2E_DAILY_GREETING 你好！ 今天先从什么开始帮你？')
      await settleStream()
      await capture(page, WAVE, '01b-greeting-reply.png')

      // Turn 1 — a rich, formatted answer (natural-language trigger).
      await sendMessage(
        page,
        '请用清单、表格、代码、公式、图片、链接、引用和 Mermaid 图表整理本周居家训练计划',
      )
      await settleStream()
      await page.locator('svg').first().waitFor({ state: 'visible', timeout: 12_000 }).catch(() => {})
      await capture(page, WAVE, '02-rich-answer.png')

      // Turn 2 — an interactive ask_user card (natural-language trigger).
      await sendMessage(page, '请用 ask_user 让我从苹果、葡萄、梨中选择运动后的点心')
      await page
        .getByText(/喜欢什么水果|🍎 苹果|需要输入/)
        .last()
        .waitFor({ state: 'visible', timeout: 30_000 })
        .catch(() => {})
      await page.waitForTimeout(600)
      await capture(page, WAVE, '03-ask-user.png')

      // The ask_user card is the natural finale. Like the wave4 HITL approval
      // captures (10/11), we capture the interactive card WITHOUT resuming:
      // resuming the option mid-hero-flow left the run looping in the interrupt
      // (20+ re-invokes) and blew the 240s budget, and every component is already
      // captured reliably in the wave4 matrix anyway.
    } finally {
      await request.delete(`${API_BASE}/api/agents/${agentId}`, { headers: csrfHeaders }).catch(() => {})
    }
  })

  test('agent creation — conversational builder flow', async ({ page }) => {
    test.setTimeout(180_000)
    const prompt = '帮我创建一个回答健身房会员咨询并协助预约、取消的客户支持机器人'

    for (let attempt = 1; attempt <= 2; attempt += 1) {
      try {
        await page.goto(`/agents/new/conversational?initialMessage=${encodeURIComponent(prompt)}`, {
          waitUntil: 'domcontentloaded',
          timeout: 180_000,
        })
        break
      } catch (error) {
        if (attempt === 2) throw error
        await page.waitForTimeout(2_000)
      }
    }
    await page.getByText(/会话 #/).waitFor({ state: 'visible', timeout: 40_000 }).catch(() => {})
    await capture(page, WAVE, '05-builder-welcome.png')

    // Let the builder stream its response (or surface a System LLM error state).
    const stop = page.locator('[data-moldy-stop-button="true"]:visible').last()
    await stop.waitFor({ state: 'visible', timeout: 15_000 }).catch(() => {})
    await stop.waitFor({ state: 'hidden', timeout: 90_000 }).catch(() => {})
    await page.waitForTimeout(1_500)
    await capture(page, WAVE, '06-builder-result.png')
  })
})
