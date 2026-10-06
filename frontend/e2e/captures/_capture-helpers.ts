import fs from 'node:fs/promises'
import path from 'node:path'
import type { APIRequestContext, Browser, Locator, Page } from '@playwright/test'
import { getE2EAuthStatePath } from '../../scripts/e2e-lane-contract.mjs'
import { API_BASE, apiGetJson, apiPostJson, isRecord, type CsrfHeaders } from '../fixtures'

/**
 * Shared helpers for the full-app capture tour (tasks/captures-todo.md).
 *
 * Captures land under ``output/captures/<wave>/`` (gitignored). Specs are gated
 * by ``E2E_CAPTURE_TOUR=1`` so they never run in normal CI. Content is the
 * deterministic keyless scripted model + realistic seed data created here so the
 * surfaces look plausible (agent names, tool framing) rather than ``test123``.
 */

export const CAPTURE_ROOT = path.join('..', 'output', 'captures')
export const DESKTOP_VIEWPORT = { width: 1440, height: 960 } as const

// Mirror playwright.config.ts: raw browser.newContext() does NOT inherit
// use.baseURL, so the warm-up must reconstruct the dev-server origin itself.
const WARMUP_FRONTEND_PORT = process.env.E2E_FRONTEND_PORT ?? '3100'
const WARMUP_BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${WARMUP_FRONTEND_PORT}`
const WARMUP_AUTH_STATE_PATH = getE2EAuthStatePath(process.env.E2E_LANE ?? 'scripted', process.env)

/**
 * Compile the heavy 'use client' chat conversation route ONCE, in its own context,
 * so the first capture test that hits it isn't charged for the one-time Next dev
 * cold compile (several minutes on a fresh server). Call from a test.beforeAll —
 * but FIRST raise the hook budget with `test.setTimeout(...)`, because the config's
 * default `timeout` (60s) is far shorter than a cold compile and would kill the
 * hook. The params are placeholders: Next dev compiles the route module on first
 * request regardless of whether the agent/conversation data resolves.
 */
export async function warmUpChatRoute(browser: Browser): Promise<void> {
  if (process.env.E2E_CAPTURE_TOUR !== '1') return
  const ctx = await browser.newContext({
    storageState: WARMUP_AUTH_STATE_PATH,
    baseURL: WARMUP_BASE_URL,
  })
  const page = await ctx.newPage()
  try {
    await page
      .goto('/agents/warmup/conversations/warmup', {
        waitUntil: 'domcontentloaded',
        timeout: 280_000,
      })
      .catch(() => {})
    await page.waitForTimeout(2_000)
  } finally {
    await ctx.close()
  }
}

export async function capture(page: Page, wave: string, filename: string): Promise<void> {
  const dir = path.join(CAPTURE_ROOT, wave)
  await fs.mkdir(dir, { recursive: true })
  await page.screenshot({ path: path.join(dir, filename), fullPage: true })
}

/** Capture the current viewport, including fixed overlays such as keyboard skip links. */
export async function captureViewport(page: Page, wave: string, filename: string): Promise<void> {
  const dir = path.join(CAPTURE_ROOT, wave)
  await fs.mkdir(dir, { recursive: true })
  await page.screenshot({ path: path.join(dir, filename) })
}

/**
 * Element-scoped capture. The chat thread lives inside a nested ``overflow-y-auto``
 * viewport that auto-scrolls to the bottom, so ``fullPage`` page screenshots clip the
 * top of a taller-than-viewport message. ``locator.screenshot()`` scrolls the element
 * into view and grabs its full bounding box (captureBeyondViewport), so use this when
 * the target is a single message bubble rather than the whole page.
 */
export async function captureLocator(
  locator: Locator,
  wave: string,
  filename: string,
): Promise<void> {
  const dir = path.join(CAPTURE_ROOT, wave)
  await fs.mkdir(dir, { recursive: true })
  await locator.screenshot({ path: path.join(dir, filename) })
}

export async function scriptedModelId(request: APIRequestContext): Promise<string> {
  const models = await apiGetJson(request, `${API_BASE}/api/models`)
  if (!Array.isArray(models)) throw new Error('models did not return an array')
  const model = models.find(
    (row) =>
      isRecord(row) &&
      row.provider === 'e2e_scripted' &&
      row.model_name === 'document-artifact-scripted',
  )
  if (!isRecord(model) || typeof model.id !== 'string') {
    throw new Error('E2E scripted model is not seeded')
  }
  return model.id
}

/** Plausible production-shaped agents so dashboards/lists look real, not test-y. */
export const REALISTIC_AGENTS: ReadonlyArray<{
  readonly name: string
  readonly description: string
  readonly system_prompt: string
}> = [
  {
    name: 'FitLife 会员支持机器人',
    description: '处理健身房会员咨询、预约和取消的客户支持 Agent',
    system_prompt:
      '你是 FitLife Fitness 的客户支持客服。帮助查询会员积分、预约课程和取消会员。一次只处理一件事，友好且简洁地回应。',
  },
  {
    name: '旅行行程规划器',
    description: '根据目的地、时长和预算设计定制旅行行程的 Agent',
    system_prompt:
      '你是旅行规划师。了解用户的目的地、时长、预算和偏好，按天提供行程和推荐地点。',
  },
  {
    name: '公司内部 IT 服务台',
    description: '处理密码重置、VPN、设备申请等公司内部 IT 咨询',
    system_prompt:
      '你是公司内部 IT 服务台客服。指导密码重置、VPN 连接和设备申请流程。',
  },
  {
    name: '产品反馈摘要机器人',
    description: '分析客户评论和问卷并总结核心洞察',
    system_prompt:
      '你是产品反馈分析师。按主题分类客户评论，并总结正面/负面信号和改进优先级。',
  },
  {
    name: '营销文案助手',
    description: '生成活动文案、SNS 帖子和邮件文案草稿',
    system_prompt:
      '你是营销文案撰稿人。根据品牌语调，为广告文案、SNS 帖子和邮件标题提供多个方案。',
  },
]

export async function seedRealisticAgents(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
): Promise<string[]> {
  const modelId = await scriptedModelId(request)
  const ids: string[] = []
  for (const agent of REALISTIC_AGENTS) {
    const created = await apiPostJson(request, `${API_BASE}/api/agents`, csrfHeaders, {
      name: agent.name,
      description: agent.description,
      system_prompt: agent.system_prompt,
      model_id: modelId,
    })
    if (isRecord(created) && typeof created.id === 'string') ids.push(created.id)
  }
  return ids
}

export async function deleteAgents(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
  ids: readonly string[],
): Promise<void> {
  for (const id of ids) {
    await request.delete(`${API_BASE}/api/agents/${id}`, { headers: csrfHeaders }).catch(() => {})
  }
}

/**
 * Settle a navigation: network idle + a short paint delay so async lists render.
 * The networkidle wait is CAPPED — the chat conversation route holds a long-lived
 * SSE/polling connection that never reaches networkidle, so an uncapped wait hangs
 * until the test timeout. On quiet pages (dashboard/settings) idle is reached well
 * under the cap; on streaming pages we give up after it and rely on the explicit
 * element waits the callers already do (composer visible, stop-button hidden).
 */
export async function settle(page: Page, ms = 800): Promise<void> {
  await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => {})
  await page.waitForTimeout(ms)
}

// ── Rich seed (wave 7) ──────────────────────────────────────────────────────

export async function installDocxSkill(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
): Promise<string | null> {
  const items = await apiGetJson(
    request,
    `${API_BASE}/api/marketplace/items?resource_type=skill&source_kind=system_seed&limit=200`,
  )
  const list = Array.isArray(items) ? items : []
  const docx = list.find((row) => isRecord(row) && row.slug === 'docx-document')
  if (!isRecord(docx) || typeof docx.id !== 'string') return null
  const installed = await apiPostJson(
    request,
    `${API_BASE}/api/marketplace/items/${docx.id}/install`,
    csrfHeaders,
    { install_mode: 'overwrite_existing' },
  )
  return isRecord(installed) && typeof installed.installed_skill_id === 'string'
    ? installed.installed_skill_id
    : null
}

export async function systemToolIds(request: APIRequestContext, limit: number): Promise<string[]> {
  const tools = await apiGetJson(request, `${API_BASE}/api/tools`)
  const list = Array.isArray(tools) ? tools : []
  return list
    .filter((row): row is Record<string, unknown> => isRecord(row) && typeof row.id === 'string')
    .slice(0, limit)
    .map((row) => row.id as string)
}

/** A fully-configured agent (tools + skill + subagent + trigger) so settings tabs aren't empty. */
export async function createRichAgent(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
): Promise<{ agentId: string; childId: string | null }> {
  const modelId = await scriptedModelId(request)
  const skillId = await installDocxSkill(request, csrfHeaders)
  const toolIds = await systemToolIds(request, 3)
  const child = await apiPostJson(request, `${API_BASE}/api/agents`, csrfHeaders, {
    name: '预约处理助手',
    description: '课程预约/取消专用子 Agent',
    system_prompt: '只负责预约和取消。',
    model_id: modelId,
  })
  const childId = isRecord(child) && typeof child.id === 'string' ? child.id : null
  const agent = await apiPostJson(request, `${API_BASE}/api/agents`, csrfHeaders, {
    name: 'FitLife 会员支持机器人',
    description: '处理健身房会员咨询、预约和取消的客户支持 Agent',
    system_prompt:
      '你是 FitLife Fitness 的客户支持客服。帮助查询会员积分、预约课程和取消会员。一次只处理一件事，友好且简洁地回应。',
    model_id: modelId,
    tool_ids: toolIds,
    skill_ids: skillId ? [skillId] : [],
    sub_agent_ids: childId ? [childId] : [],
  })
  if (!isRecord(agent) || typeof agent.id !== 'string') throw new Error('rich agent create failed')
  return { agentId: agent.id, childId }
}

/** The seeded openai_compatible (LiteLLM) model — required for fixed-identity agents (triggers). */
export async function openaiCompatibleModelId(request: APIRequestContext): Promise<string | null> {
  const models = await apiGetJson(request, `${API_BASE}/api/models`)
  if (!Array.isArray(models)) return null
  const model = models.find((row) => isRecord(row) && row.provider === 'openai_compatible')
  return isRecord(model) && typeof model.id === 'string' ? model.id : null
}

/**
 * A fully-configured, fixed-identity agent: LiteLLM model + opener questions +
 * tools + skill + subagent. Fixed identity + openai_compatible model are required
 * for scheduled triggers; opener questions populate the opener tab. (Settings
 * captures never chat with it, so the real model is never called.)
 */
export async function createConfiguredAgent(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
): Promise<{ agentId: string; childId: string | null }> {
  const modelId = (await openaiCompatibleModelId(request)) ?? (await scriptedModelId(request))
  const skillId = await installDocxSkill(request, csrfHeaders)
  const toolIds = await systemToolIds(request, 3)
  const child = await apiPostJson(request, `${API_BASE}/api/agents`, csrfHeaders, {
    name: '预约处理助手',
    description: '课程预约/取消专用子 Agent',
    system_prompt: '只负责预约和取消。',
    model_id: modelId,
  })
  const childId = isRecord(child) && typeof child.id === 'string' ? child.id : null
  const agent = await apiPostJson(request, `${API_BASE}/api/agents`, csrfHeaders, {
    name: 'FitLife 会员支持机器人',
    description: '处理健身房会员咨询、预约和取消的客户支持 Agent',
    system_prompt:
      '你是 FitLife Fitness 的客户支持客服。帮助查询会员积分、预约课程和取消会员。一次只处理一件事，友好且简洁地回应。',
    model_id: modelId,
    identity_mode: 'fixed',
    opener_questions: [
      '告诉我会员积分还剩多少',
      '我想预约本周的瑜伽课',
      '要怎么取消会员？',
    ],
    tool_ids: toolIds,
    skill_ids: skillId ? [skillId] : [],
    sub_agent_ids: childId ? [childId] : [],
  })
  if (!isRecord(agent) || typeof agent.id !== 'string')
    throw new Error('configured agent create failed')
  return { agentId: agent.id, childId }
}

export async function addIntervalTrigger(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
  agentId: string,
  minutes: number,
): Promise<void> {
  await apiPostJson(request, `${API_BASE}/api/agents/${agentId}/triggers`, csrfHeaders, {
    name: '每日会员报告',
    trigger_type: 'interval',
    schedule_config: { interval_minutes: minutes },
    input_message: '总结一下今天的会员情况。',
  }).catch(() => {})
}

export async function createConversation(
  request: APIRequestContext,
  csrfHeaders: CsrfHeaders,
  agentId: string,
  title: string,
): Promise<string> {
  const convo = await apiPostJson(
    request,
    `${API_BASE}/api/agents/${agentId}/conversations`,
    csrfHeaders,
    { title },
  )
  if (!isRecord(convo) || typeof convo.id !== 'string')
    throw new Error('conversation create failed')
  return convo.id
}

/**
 * A 320×200 solid-color PNG so the inline attachment renders as a visible
 * thumbnail in captures (a 1×1 PNG is technically "visible" but invisibly small).
 */
export const TINY_PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAUAAAADICAIAAAAWZq/8AAABvUlEQVR42u3TQQkAAAgEwesq2N8GhvAlDEyChU31AE9FAjAwYGDAwGBgwMCAgQEDg4EBAwMGBgMDBgYMDBgYDAwYGDAwYGAwMGBgwMBgYMDAgIEBA4OBAQMDBgYMDAYGDAwYGAwMGBgwMGBgMDBgYMDAYGAVwMCAgQEDg4EBAwMGBgwMBgYMDBgYDAwYGDAwYGAwMGBgwMCAgcHAgIEBA4OBAQMDBgYMDAYGDAwYGDAwGBgwMGBgMDBgYMDAgIHBwICBAQODgQEDAwYGDAwGBgwMGBgwMBgYMDBgYMDAYGDAwYGDAwGBgwMCAgcHAgIEBAwMGBgMDBgYMDAYGDAwGBgwMGBgwMBgYMDBgYMDAYGDAwICBwcCAgQEDAwYGAwMGBgwMBgYMDBgYMDAYGDAwYGDAwGBgwMCAgYHBwICBAQMDBgYDAwYGDAwYGAwMGBgwMBgYMDBgYMDAYGDAwICBwcAqgIEBAwMGBgMDBgYMDBgYDAwYGDAwGBgwMGBgwMBgYMDAgIEBA4OBAQMDBgYDAwYGDAwYGAwMGBgwMGBgMDBgYMDAYGDAwICBAQODgQEDAwYGAwMGBgwMGBgMDBgYMDBgYDAwYGDgYgGi4L1CRSPgHQAAAABJRU5ErkJggg=='
