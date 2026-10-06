import fs from 'node:fs/promises'
import path from 'node:path'
import { test, expect, loginApi, API_BASE } from '../fixtures'
import {
  capture,
  DESKTOP_VIEWPORT,
  settle,
  TINY_PNG_BASE64,
  warmUpChatRoute,
} from './_capture-helpers'

/**
 * Skill Builder Phase 1.5 截图巡检 — 2 项新功能的实际运行证明。
 *
 * A. 自动首条消息：dialog 的 user_request 在进入 builder 时无需输入即可
 *    自动发出 + reload 时不会重复发送 (create/improve 共用)。
 * B. 二进制 finalize：workspace 中放有真实 PNG asset 的 draft
 *    可成功 finalize（旧版本会 BINARY_FILES_UNSUPPORTED fail-closed），
 *    保存后的 skill 磁盘中字节保持不变。
 *
 * 前提：throwaway stack + scripted system LLM (E2E_LLM_* 置空)。
 * E2E_CAPTURE_TOUR=1 gate（普通运行时 skip）。
 */

const WAVE = 'skill-builder-phase15'
// playwright cwd = frontend/ — backend data_root(./data) 是同级目录。
const BACKEND_DATA = path.join('..', 'backend', 'data')

const CREATE_REQUEST = '帮我创建一个把会议记录中的负责人、待办事项和截止日期整理成表格的 skill'
const IMPROVE_REQUEST = '把摘要格式改进为表格形式'
const SCRIPTED_REPLY = 'E2E scripted document model is ready.'

test.describe('Skill Builder Phase 1.5 — 自动首条消息 + 二进制 finalize 截图', () => {
  test.skip(process.env.E2E_CAPTURE_TOUR !== '1', 'Set E2E_CAPTURE_TOUR=1 to run the capture tour')
  test.skip(process.env.PW_SKIP_BACKEND === '1', 'Requires the FastAPI backend')

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(300_000)
    await warmUpChatRoute(browser)
  })

  test('A. create dialog 请求 → 进入后立即自动发送 → reload 不重复', async ({
    page,
    request,
  }) => {
    test.setTimeout(300_000)
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await loginApi(request)

    // ── 1. 请求来源："通过聊天构建" dialog ─────────────────────
    await page.goto('/skills', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await page.getByRole('button', { name: '通过聊天构建' }).first().click()
    const requestBox = page.locator('#skill-chat-request')
    await expect(requestBox).toBeVisible({ timeout: 15_000 })
    await requestBox.fill(CREATE_REQUEST)
    await settle(page, 300)
    await capture(page, WAVE, '01-create-dialog-request.png')

    // ── 2. 开始对话 → 进入 builder — 无需输入即可自动完成第一轮 ──
    await page.getByRole('button', { name: '开始聊天' }).click()
    await page.waitForURL(/\/skills\/builder\/[0-9a-f-]{36}/, { timeout: 120_000 })
    const composer = page.locator('textarea[data-moldy-composer-input="true"]').last()
    await expect(composer).toBeVisible({ timeout: 60_000 })
    // 为与 emptyContent 提示面板中的 user_request echo 区分，scope 到消息气泡。
    const autoSentBubble = page
      .locator('[data-moldy-message-id]')
      .filter({ hasText: CREATE_REQUEST })
    await expect(autoSentBubble.first()).toBeVisible({ timeout: 45_000 })
    await expect(page.getByText(SCRIPTED_REPLY).last()).toBeVisible({ timeout: 45_000 })
    await expect(composer).toHaveValue('') // 用户没有输入任何内容
    await settle(page)
    await capture(page, WAVE, '02-auto-first-message.png')

    // ── 3. reload — 通过 server truth guard（消息/run 历史）不会重新发送 ────
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByText(SCRIPTED_REPLY).first()).toBeVisible({ timeout: 60_000 })
    await settle(page, 1_500) // 如果发生重新发送，这之间会出现 optimistic bubble
    await expect(autoSentBubble).toHaveCount(1)
    await capture(page, WAVE, '03-reload-no-duplicate.png')
  })

  test('B. improve session 也会在进入后立即自动发送', async ({ page, request }) => {
    test.setTimeout(300_000)
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const csrf = await loginApi(request)

    const skillRes = await request.post(`${API_BASE}/api/skills`, {
      headers: csrf,
      data: {
        name: '会议摘要助手',
        content:
          '---\nname: meeting-summary\ndescription: "Use when summarizing meetings."\n---\n\n总结会议内容。\n',
      },
    })
    expect(skillRes.ok(), `create skill → ${skillRes.status()}`).toBeTruthy()
    const skill = (await skillRes.json()) as { id: string }

    const sessionRes = await request.post(`${API_BASE}/api/skill-builder`, {
      headers: csrf,
      data: { mode: 'improve', user_request: IMPROVE_REQUEST, source_skill_id: skill.id },
    })
    expect(sessionRes.ok(), `improve start → ${sessionRes.status()}`).toBeTruthy()
    const session = (await sessionRes.json()) as { id: string }

    await page.goto(`/skills/builder/${session.id}`, {
      waitUntil: 'domcontentloaded',
      timeout: 120_000,
    })
    await expect(
      page.locator('[data-moldy-message-id]').filter({ hasText: IMPROVE_REQUEST }).first(),
    ).toBeVisible({ timeout: 45_000 })
    await expect(page.getByText(SCRIPTED_REPLY).last()).toBeVisible({ timeout: 45_000 })
    await settle(page)
    await capture(page, WAVE, '04-improve-auto-first-message.png')
  })

  test('C. 含二进制 asset(PNG) 的 draft 成功 finalize', async ({ page, request }) => {
    test.setTimeout(300_000)
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const csrf = await loginApi(request)

    const res = await request.post(`${API_BASE}/api/skill-builder`, {
      headers: csrf,
      data: { mode: 'create', user_request: '帮我创建一个使用 logo 图片 asset 的会议记录 skill' },
    })
    expect(res.ok(), `start v2 → ${res.status()}`).toBeTruthy()
    const session = (await res.json()) as { id: string }
    const sessionId = session.id

    await page.goto(`/skills/builder/${sessionId}`, {
      waitUntil: 'domcontentloaded',
      timeout: 120_000,
    })
    const composer = page.locator('textarea[data-moldy-composer-input="true"]').last()
    await expect(composer).toBeVisible({ timeout: 60_000 })
    // 等待自动第一轮完成后继续 marker。
    await expect(page.getByText(SCRIPTED_REPLY).last()).toBeVisible({ timeout: 45_000 })

    const sendMessage = async (text: string) => {
      await composer.fill(text)
      await composer.press('Enter')
      await expect(composer).toHaveValue('', { timeout: 10_000 })
    }

    // ── 1. 编写 draft（scripted write_file 2 次）──────────────────────
    await sendMessage(`E2E_SKILL_BUILDER_WRITE /skill-drafts/${sessionId}`)
    await expect(page.getByText('已写入 draft 文件').last()).toBeVisible({
      timeout: 45_000,
    })

    // ── 2. 注入二进制 asset — 将真实 320×200 PNG 写入 workspace 磁盘 ──
    const pngBytes = Buffer.from(TINY_PNG_BASE64, 'base64')
    const assetDir = path.join(BACKEND_DATA, 'skill-drafts', sessionId, 'assets')
    await fs.mkdir(assetDir, { recursive: true })
    await fs.writeFile(path.join(assetDir, 'logo.png'), pngBytes)

    // ── 3. 验证 — 填充 rail 状态卡/文件列表 ─────────────────────────
    await sendMessage('E2E_SKILL_BUILDER_VALIDATE')
    await expect(page.getByText('已执行 draft 验证').last()).toBeVisible({
      timeout: 45_000,
    })
    await expect(page.getByTestId('skill-builder-rail').getByTestId('builder-draft-files')).toBeVisible(
      { timeout: 30_000 },
    )
    await settle(page)
    await capture(page, WAVE, '05-binary-draft-validated.png')

    // ── 4. finalize approval card（旧版本则批准后出现 BINARY_FILES_UNSUPPORTED）──
    await sendMessage('E2E_SKILL_BUILDER_FINALIZE')
    await expect(page.getByText('finalize_skill').last()).toBeVisible({ timeout: 45_000 })
    await settle(page, 300)
    await capture(page, WAVE, '06-binary-finalize-approval.png')

    // ── 5. 批准 → 保存成功 + 完成 banner ───────────────────────────
    await page.getByTestId('approval-approve-button').last().click()
    await expect(page.getByText('已保存 skill').last()).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('builder-completed-banner')).toBeVisible({ timeout: 30_000 })
    await settle(page)
    await capture(page, WAVE, '07-binary-finalize-completed.png')

    // ── 6. 验证保存结果 — session completed + 保存树中字节完全一致 ──
    const after = (await (
      await request.get(`${API_BASE}/api/skill-builder/${sessionId}`)
    ).json()) as { status: string; finalized_skill_id: string | null }
    expect(after.status).toBe('completed')
    expect(after.finalized_skill_id).toBeTruthy()
    const stored = path.join(
      BACKEND_DATA,
      'skills',
      after.finalized_skill_id as string,
      'assets',
      'logo.png',
    )
    const storedBytes = await fs.readFile(stored)
    expect(storedBytes.equals(pngBytes)).toBe(true)

    // ── 7. 完成 deeplink → 生成的 package skill source tab ─────────────
    await page.getByRole('link', { name: '开放技能' }).click()
    await page.waitForURL(/\/skills\/[^/]+\/source/, { timeout: 60_000 })
    await expect(page.getByRole('button', { name: '通过聊天改进' })).toBeVisible({
      timeout: 30_000,
    })
    await settle(page)
    await capture(page, WAVE, '08-binary-skill-detail.png')
  })
})
