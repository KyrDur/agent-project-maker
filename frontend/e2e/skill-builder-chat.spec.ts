import { test, expect } from './fixtures'
import type { APIRequestContext } from '@playwright/test'

// Skill Builder 聊天（skill-studio phase 1, M6）— 规范 §2 成功标准 E2E。
// scripted 序列：write_file（草稿 2 个文件）→ validate_skill →
// test_skill_draft（批准卡片 → "留出本次会议的剩余时间" → 再次执行无卡片）→
// finalize_skill（始终有批准卡片 → 批准 → skills row）+ reload replay。
// 后端 E2E_SCRIPTED_MODEL_ENABLED=true 会将 system LLM(text_primary)
// seed 为 scripted 模型（seed_e2e_scripted_model）。
const API =
  process.env.E2E_API_BASE_URL ?? `http://localhost:${process.env.E2E_BACKEND_PORT ?? '8001'}`
const EMAIL = process.env.E2E_USER_EMAIL ?? process.env.E2E_EMAIL ?? 'playwright-e2e@moldy.dev'
const PASSWORD =
  process.env.E2E_USER_PASSWORD ?? process.env.E2E_PASSWORD ?? 'correct horse battery staple 42'

async function login(request: APIRequestContext): Promise<Record<string, string>> {
  const res = await request.post(`${API}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
  })
  expect(res.ok()).toBeTruthy()
  return { 'X-CSRF-Token': (await res.json()).csrf_token as string }
}

test.describe('skill builder chat', () => {
  test.skip(process.env.PW_SKIP_BACKEND === '1', 'Requires the FastAPI backend')

  let csrf: Record<string, string>
  let sessionId: string
  let conversationId: string

  test.beforeAll(async ({ request }) => {
    csrf = await login(request)
    const res = await request.post(`${API}/api/skill-builder`, {
      headers: csrf,
      data: { mode: 'create', user_request: '帮我创建 E2E 会议记录 skill' },
    })
    expect(res.ok(), `start v2 → ${res.status()}`).toBeTruthy()
    const session = (await res.json()) as {
      id: string
      conversation_id: string | null
      agent_id: string | null
    }
    expect(session.conversation_id).toBeTruthy()
    expect(session.agent_id).toBeTruthy()
    sessionId = session.id
    conversationId = session.conversation_id as string
  })

  test('multiturn draft edit → validate → consent-gated test → finalize → reload replay', async ({
    page,
    request,
  }) => {
    test.setTimeout(240_000)
    // 首次进入时使用放宽的等待条件，以容忍 dev server cold-compile。
    await page.goto(`/skills/builder/${sessionId}`, {
      waitUntil: 'domcontentloaded',
      timeout: 120_000,
    })

    await expect(page.getByTestId('skill-builder-rail')).toBeVisible({ timeout: 60_000 })
    const composer = page.locator('textarea[data-moldy-composer-input="true"]:visible').last()
    await expect(composer).toBeVisible({ timeout: 60_000 })

    // 0) Phase 1.5 — dialog 的 user_request 会自动作为第一条消息发出
    //    （用户无需再次输入）。等待 scripted fallback 响应完成。
    //    注意：page-wide getByText 也会匹配 emptyContent 提示面板中的 user_request
    //    echo，从而形成同义反复 — 将作用域缩小到消息气泡。
    const autoSentBubble = page
      .locator('[data-moldy-message-id]')
      .filter({ hasText: '帮我创建 E2E 会议记录 skill' })
    await expect(autoSentBubble.first()).toBeVisible({ timeout: 45_000 })
    await expect(page.getByText('E2E scripted document model is ready.').last()).toBeVisible({
      timeout: 45_000,
    })

    // M8-1 回归守卫：run 结束后 Enter 发送也必须立即生效
    // （验证从根本上修复 post-run hydration 锁住 composer 的缺陷 —
    // 不使用 fallback，仅按 Enter 就必须清空值）。
    const sendMessage = async (text: string) => {
      // source rail toggle 可能会重新渲染 Builder。重新获取当前可见的 textarea，
      // 仅在其真正进入可编辑/可发送状态后验证 Enter 路径。
      // 有意不使用点击 fallback，因此一旦此契约被破坏就会立即失败。
      const currentComposer = page
        .locator('textarea[data-moldy-composer-input="true"]:visible')
        .last()
      const sendButton = page.getByRole('button', { name: '发送按钮' }).last()
      await expect(currentComposer).toBeVisible({ timeout: 45_000 })
      await expect(currentComposer).toBeEnabled({ timeout: 45_000 })
      // 响应文本可能会早于 stream 结束显示。Builder 发送按钮仅在
      // thread.isRunning=false 时渲染，因此等待真正可输入的状态。
      // 如果 post-run hydration 错误地持续保持 running，这个等待本身就会失败。
      await expect(sendButton).toBeVisible({ timeout: 45_000 })
      await currentComposer.fill(text)
      await expect(currentComposer).toHaveValue(text)
      await expect(sendButton).toBeEnabled({ timeout: 45_000 })
      await currentComposer.press('Enter')
      await expect(currentComposer).toHaveValue('', { timeout: 10_000 })
    }

    // M8-2 回归守卫：后端先于 trace 提交 interrupt 状态转移，然后 resume
    // handler 会短暂等待状态转移，因此批准必须无需重试、一次即可被接受
    // （如果出现重试文案，则说明 race 回归）。
    const approve = async () => {
      await page.getByTestId('approval-approve-button').last().click()
      await expect(page.getByText('无法发送批准响应。再试一次。')).toHaveCount(
        0,
      )
    }

    // 1) 渐进式编辑 — 2 次 write_file 在没有批准卡片的情况下执行（AD-3 防止过度审批）。
    await sendMessage(`E2E_SKILL_BUILDER_WRITE /skill-drafts/${sessionId}`)
    await expect(page.getByText('已写入 draft 文件').last()).toBeVisible({
      timeout: 45_000,
    })

    // 2) 验证 — 下一次 run 的 stream head 中 moldy.skill_draft 会填充 rail 文件列表。
    await sendMessage('E2E_SKILL_BUILDER_VALIDATE')
    await expect(page.getByText('已执行 draft 验证').last()).toBeVisible({
      timeout: 45_000,
    })
    const rail = page.getByTestId('skill-builder-rail')
    await expect(rail.getByTestId('builder-draft-files')).toBeVisible({ timeout: 30_000 })
    await expect(rail.getByText('SKILL.md').first()).toBeVisible()
    // M7 状态卡片 — 验证事件填充行状态色调 + runtime compatibility chip。
    await expect(rail.getByTestId('builder-status-rows')).toBeVisible({ timeout: 15_000 })
    await expect(rail.getByTestId('builder-runtime-chips')).toBeVisible({ timeout: 15_000 })

    // 2b) 查看 source — 基于文件 API 的 read-only viewer（M7）。
    await page.getByTestId('builder-open-source').click()
    await expect(rail.getByTestId('builder-source-pane')).toBeVisible({ timeout: 15_000 })
    await expect(rail.getByTestId('builder-source-viewer')).toContainText('e2e-notes', {
      timeout: 30_000,
    })
    await page.getByTestId('builder-open-source').click()
    await expect(rail.getByTestId('builder-status-rows')).toBeVisible({ timeout: 15_000 })

    // 3) 草稿测试 — CODE_EXECUTION 批准卡片 + session consent 勾选。
    await sendMessage('E2E_SKILL_BUILDER_TEST run=1')
    await expect(page.getByText('需要批准').last()).toBeVisible({ timeout: 45_000 })
    const consent = page.getByTestId('approval-session-consent').last()
    await expect(consent).toBeVisible()
    await consent.check()
    await approve()
    await expect(page.getByText('draft 测试执行已完成').last()).toBeVisible({
      timeout: 60_000,
    })

    // 4) consent 后再次执行 — 不出现批准卡片，直接执行（第 2 次无卡片）。
    await sendMessage('E2E_SKILL_BUILDER_RETEST run=2')
    await expect(page.getByText('draft 测试执行已完成').nth(1)).toBeVisible({
      timeout: 60_000,
    })
    await expect(page.getByText('需要批准')).toHaveCount(0)

    // 5) finalize — 始终显示批准卡片，不提供 session consent 选项。
    await sendMessage('E2E_SKILL_BUILDER_FINALIZE')
    await expect(page.getByText('finalize_skill').last()).toBeVisible({ timeout: 45_000 })
    await expect(page.getByTestId('approval-session-consent')).toHaveCount(0)
    // M8-3 回归守卫：由于前一个 resolved 卡片（test_skill_draft）与当前 interrupt 不同，
    // 不应被合并到 group container（"待批准 N 项"）中，而应渲染为单独卡片。
    await expect(page.getByText(/待批准 \d+项/)).toHaveCount(0)
    await approve()
    await expect(page.getByText('已保存 skill').last()).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('builder-completed-banner')).toBeVisible({ timeout: 30_000 })

    // 6) 真正的 skills row + session completed（规范 §2-3）。
    const skills = (await (await request.get(`${API}/api/skills`)).json()) as {
      slug: string
      kind: string
    }[]
    expect(skills.some((s) => s.slug.startsWith('e2e-notes') && s.kind === 'package')).toBe(true)
    const session = (await (await request.get(`${API}/api/skill-builder/${sessionId}`)).json()) as {
      status: string
      finalized_skill_id: string | null
    }
    expect(session.status).toBe('completed')
    expect(session.finalized_skill_id).toBeTruthy()

    // 7) reload replay — 恢复 rail（文件列表）+ 不存在 <redacted>（规范 §2-4/§7）。
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('skill-builder-rail')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('builder-draft-files')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('builder-completed-banner')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('body')).not.toContainText('<redacted>')
    // R4：多轮对话历史会从 checkpointer 恢复（§2-5 — 不仅是 rail，
    // transcript 气泡也会）。通过用户 marker 消息和最终响应文本断言。
    await expect(page.getByText('E2E_SKILL_BUILDER_VALIDATE').first()).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.getByText('已保存 skill').first()).toBeVisible({ timeout: 30_000 })
    // Phase 1.5 重发守卫 — reload 时自动首条消息不会重复发出
    // （存在对话历史/run 历史时 no-op）。按 transcript 气泡计算应恰好 1 条。
    await expect(autoSentBubble).toHaveCount(1)

    // 对话属于隐藏 Agent，不会泄漏到 navigator/Agent 列表中（§2 风险）。
    const agents = (await (await request.get(`${API}/api/agents`)).json()) as { id: string }[]
    const conversations = (await (
      await request.get(`${API}/api/conversations/page?limit=50`)
    ).json()) as { items: { id: string }[] }
    expect(conversations.items.map((c) => c.id)).not.toContain(conversationId)
    expect(agents.map((a) => a.id)).not.toContain(
      (await (await request.get(`${API}/api/skill-builder/${sessionId}`)).json()).agent_id,
    )
  })

  test('finalize conflict — source skill changed mid-session, agent explains (§2-3)', async ({
    page,
    request,
  }) => {
    test.setTimeout(180_000)
    // CSRF token 与请求 context（cookie）成对，因此使用本测试的 request context
    // 重新登录以获取新 token（beforeAll token 仅适用于其自身 context）。
    const csrfLocal = await login(request)
    // 1) 创建原始文本 skill → 启动 improve session → 从外部修改原始内容，
    //    使 content_hash 不一致（复现 SOURCE_SKILL_CHANGED）。
    const skillRes = await request.post(`${API}/api/skills`, {
      headers: csrfLocal,
      data: {
        name: `e2e-conflict-${Date.now()}`,
        content:
          '---\nname: e2e-conflict\ndescription: "Use when testing conflicts."\n---\n\noriginal\n',
      },
    })
    expect(skillRes.ok(), `create skill → ${skillRes.status()}`).toBeTruthy()
    const skill = (await skillRes.json()) as { id: string; version: string | null }

    const sessionRes = await request.post(`${API}/api/skill-builder`, {
      headers: csrfLocal,
      data: { mode: 'improve', user_request: '帮我改进这个 skill', source_skill_id: skill.id },
    })
    expect(sessionRes.ok(), `improve start → ${sessionRes.status()}`).toBeTruthy()
    const improveSession = (await sessionRes.json()) as { id: string }

    const putRes = await request.put(`${API}/api/skills/${skill.id}/content`, {
      headers: csrfLocal,
      data: {
        content:
          '---\nname: e2e-conflict\ndescription: "Use when testing conflicts."\n---\n\nchanged outside the session\n',
      },
    })
    expect(putRes.ok(), `mutate source → ${putRes.status()}`).toBeTruthy()
    const mutatedHash = ((await putRes.json()) as { content_hash: string }).content_hash

    // 2) 尝试 finalize → 批准卡片 → 批准 → 工具返回 SOURCE_SKILL_CHANGED →
    //    Agent 向用户解释（确定性复现 §2-3 契约）。
    await page.goto(`/skills/builder/${improveSession.id}`, {
      waitUntil: 'domcontentloaded',
      timeout: 120_000,
    })
    const composer = page.locator('textarea[data-moldy-composer-input="true"]').last()
    await expect(composer).toBeVisible({ timeout: 60_000 })
    // Phase 1.5 — improve session 的 user_request 也会自动发出。完成后继续。
    // （为与 emptyContent echo 区分，将作用域限定为消息气泡。）
    await expect(
      page.locator('[data-moldy-message-id]').filter({ hasText: '帮我改进这个 skill' }).first(),
    ).toBeVisible({ timeout: 45_000 })
    await expect(page.getByText('E2E scripted document model is ready.').last()).toBeVisible({
      timeout: 45_000,
    })
    await composer.fill('E2E_SKILL_BUILDER_FINALIZE_CONFLICT')
    await composer.press('Enter')
    await expect(composer).toHaveValue('', { timeout: 10_000 })
    await expect(page.getByText('finalize_skill').last()).toBeVisible({ timeout: 45_000 })
    await page.getByTestId('approval-approve-button').last().click()
    await expect(page.getByText('原始 skill 在 session 开始后发生了更改').last()).toBeVisible({
      timeout: 60_000,
    })

    // 3) session 未完成，原始 skill 也没有被 session 覆盖。
    const after = (await (
      await request.get(`${API}/api/skill-builder/${improveSession.id}`)
    ).json()) as { status: string; finalized_skill_id: string | null }
    expect(after.status).not.toBe('completed')
    expect(after.finalized_skill_id).toBeNull()
    // session 未覆盖原始内容 — 从外部修改后的 hash 应保持不变。
    const skillAfter = (await (await request.get(`${API}/api/skills/${skill.id}`)).json()) as {
      content_hash: string
    }
    expect(skillAfter.content_hash).toBe(mutatedHash)
  })
})
