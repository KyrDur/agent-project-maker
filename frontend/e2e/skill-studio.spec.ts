import { test, expect } from './fixtures'

// Phase 2 — Skill Studio 6-tab IA：tab navigation/context bar/skill switcher/builder index。

const now = '2026-07-11T00:00:00.000Z'

function makeSkill(id: string, name: string, kind: 'text' | 'package') {
  return {
    id,
    name,
    slug: id,
    description: `${name} 描述`,
    kind,
    version: '1.0.0',
    storage_path: null,
    content_hash: `hash-${id}`,
    size_bytes: 256,
    used_by_count: 1,
    package_metadata: null,
    current_revision_id: null,
    credential_requirements: null,
    execution_profile: null,
    health: null,
    latest_evaluation_summary: null,
    last_modified_at: now,
    created_at: now,
    updated_at: now,
    origin_summary: null,
    publication_summary: null,
    installation: null,
  }
}

const alpha = makeSkill('skill-alpha', 'Alpha Notes', 'text')
const beta = makeSkill('skill-beta', 'Beta Package', 'package')
const skills = [alpha, beta]

const builderBrief = {
  id: '00000000-0000-4000-8000-00000000b1de',
  mode: 'improve',
  status: 'active',
  user_request: '帮我改进 Alpha Notes',
  source_skill_id: alpha.id,
  finalized_skill_id: null,
  conversation_id: null,
  created_at: now,
  updated_at: now,
}

async function mockStudioApis(page: import('@playwright/test').Page) {
  const sessionListRequests: Array<string | null> = []
  await page.route('**/api/skill-builder**', (route) => {
    const url = new URL(route.request().url())
    if (route.request().method() === 'GET' && url.pathname === '/api/skill-builder') {
      const scoped = url.searchParams.get('skill_id')
      sessionListRequests.push(scoped)
      // 对无 scope 请求使用另一套 fixture — 防止 scoping 回归通过 session history 断言
      // 伪装成通过的同义反复。
      return route.fulfill({
        json: scoped === alpha.id ? [builderBrief] : [],
      })
    }
    return route.fulfill({ status: 404, json: { detail: url.pathname } })
  })
  await page.route('**/api/skills**', (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    const pathName = url.pathname

    if (method !== 'GET') {
      return route.fulfill({ status: 405, json: { detail: 'read-only fixture' } })
    }
    if (pathName === '/api/skills') {
      return route.fulfill({ json: skills })
    }
    const detail = skills.find((skill) => pathName === `/api/skills/${skill.id}`)
    if (detail) {
      return route.fulfill({ json: detail })
    }
    if (pathName === `/api/skills/${alpha.id}/content`) {
      return route.fulfill({ json: { content: '# Alpha Notes\n摘要规则正文' } })
    }
    if (/\/api\/skills\/skill-(alpha|beta)\/revisions$/.test(pathName)) {
      return route.fulfill({ json: [] })
    }
    if (/\/api\/skills\/skill-(alpha|beta)\/evaluations$/.test(pathName)) {
      return route.fulfill({ json: [] })
    }
    if (/\/api\/skills\/skill-(alpha|beta)\/credential-(requirements|bindings)$/.test(pathName)) {
      return route.fulfill({ json: [] })
    }
    return route.fulfill({ status: 404, json: { detail: pathName } })
  })
  return { sessionListRequests }
}

test.describe('Skill studio IA', () => {
  test('list rows navigate to skill tabs; scoped tabs disabled without context', async ({
    page,
  }) => {
    await mockStudioApis(page)

    await page.goto('/skills')
    await expect(page.getByText('Alpha Notes')).toBeVisible()
    // 在 list tab 中，skill scope tab 为禁用状态。
    await expect(page.getByTestId('studio-tab-source')).toBeDisabled()
    await expect(page.getByTestId('studio-context-bar')).toBeHidden()

    // 点击 row → source tab。
    await page.getByText('Alpha Notes').click()
    await page.waitForURL(/\/skills\/skill-alpha\/source/)
    await expect(page.getByTestId('studio-context-bar')).toContainText('Alpha Notes')
    await expect(page.getByTestId('studio-context-bar')).toContainText('已连接 智能体')

    // tab navigation：evaluation → versions → settings。
    await page.getByTestId('studio-tab-evaluation').click()
    await page.waitForURL(/\/skills\/skill-alpha\/evaluation/)
    await page.getByTestId('studio-tab-versions').click()
    await page.waitForURL(/\/skills\/skill-alpha\/versions/)
    await page.getByTestId('studio-tab-settings').click()
    await page.waitForURL(/\/skills\/skill-alpha\/settings/)
    await expect(page.getByText('元数据')).toBeVisible()
    await expect(page.getByRole('button', { name: '删除技能' })).toBeVisible()
  })

  test('skill switcher keeps the active tab', async ({ page }) => {
    await mockStudioApis(page)

    await page.goto('/skills/skill-alpha/versions')
    await expect(page.getByTestId('studio-context-bar')).toContainText('Alpha Notes')

    await page.getByTestId('studio-skill-switcher').click()
    await page.getByRole('menuitem', { name: /Beta Package/ }).click()

    await page.waitForURL(/\/skills\/skill-beta\/versions/)
    await expect(page.getByTestId('studio-context-bar')).toContainText('Beta Package')
  })

  test('builder tab lands on the scoped builder index with session history', async ({ page }) => {
    const { sessionListRequests } = await mockStudioApis(page)

    await page.goto('/skills/skill-alpha/source')
    await page.getByTestId('studio-tab-builder').click()

    await page.waitForURL(/\/skills\/builder\?skillId=skill-alpha/)
    // shell 识别 ?skillId= scope 并保持 context — skill tab 不应错误显示为 disabled，
    // 也不应变成 "新技能草稿"（review R 回归守卫）。
    await expect(page.getByTestId('studio-context-bar')).toContainText('Alpha Notes')
    await expect(page.getByTestId('studio-tab-source')).toBeEnabled()
    await expect(page.getByRole('button', { name: /Alpha Notes 개선 시작/ })).toBeVisible()
    const sessionList = page.getByTestId('builder-session-list')
    await expect(sessionList).toContainText('帮我改进 Alpha Notes')
    await expect(sessionList.getByRole('link').first()).toHaveAttribute(
      'href',
      `/skills/builder/${builderBrief.id}`,
    )
    // 同时验证 list 请求本身是否按 skill_id 做了 scope — mock fixture 分支 + 双重防护。
    expect(sessionListRequests).toContain(alpha.id)
  })
})
