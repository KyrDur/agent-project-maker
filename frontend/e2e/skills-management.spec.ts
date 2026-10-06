import { test, expect } from './fixtures'

// E2E: Skills page — create text skill.

test.describe('Skills page', () => {
  test('user can create a text skill and see it in the table', async ({ page }) => {
    let skills: Array<Record<string, unknown>> = []
    await page.route(/\/api\/skills(\?.*)?$/, (route) => {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON() as Record<string, unknown>
        const created = {
          id: 'skill-1',
          name: body.name,
          slug: 'snippet',
          description: body.description ?? null,
          kind: 'text',
          version: null,
          storage_path: null,
          content_hash: 'abc',
          size_bytes: ((body.content as string) ?? '').length,
          used_by_count: 0,
          package_metadata: null,
          last_modified_at: new Date().toISOString(),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }
        skills = [created]
        return route.fulfill({ status: 201, json: created })
      }
      return route.fulfill({ json: skills })
    })

    await page.goto('/skills')
    await page
      .getByRole('button', { name: /新技能|创建第一个技能/ })
      .first()
      .click()

    await page.getByRole('tab', { name: '文字' }).click()
    await page.getByLabel(/名称/).fill('Greeting snippet')
    await page.getByLabel(/内容 \(Markdown\)/).fill('# Hello\nThis is a snippet.')

    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('已创建')).toBeVisible()
    await expect(page.getByText('Greeting snippet')).toBeVisible()
  })

  test('user can bulk-delete selected skills from the table', async ({ page }) => {
    const now = new Date().toISOString()
    function makeSkill(id: string, name: string, usedByCount: number) {
      return {
        id,
        name,
        slug: id,
        description: null,
        kind: 'text',
        version: null,
        storage_path: null,
        content_hash: 'abc',
        size_bytes: 10,
        used_by_count: usedByCount,
        package_metadata: null,
        health: null,
        latest_evaluation_summary: null,
        last_modified_at: now,
        created_at: now,
        updated_at: now,
      }
    }
    let skills = [makeSkill('skill-a', 'Bulk Target A', 1), makeSkill('skill-b', 'Bulk Target B', 0)]
    const deleted: string[] = []

    await page.route(/\/api\/skills(\?.*)?$/, (route) => route.fulfill({ json: skills }))
    await page.route(/\/api\/skills\/skill-[ab]$/, (route) => {
      const id = new URL(route.request().url()).pathname.split('/').at(-1) ?? ''
      if (route.request().method() === 'DELETE') {
        deleted.push(id)
        skills = skills.filter((skill) => skill.id !== id)
        return route.fulfill({ status: 204, body: '' })
      }
      const match = skills.find((skill) => skill.id === id)
      return match
        ? route.fulfill({ json: match })
        : route.fulfill({ status: 404, json: { detail: 'not found' } })
    })

    await page.goto('/skills')
    await expect(page.getByText('Bulk Target A')).toBeVisible()

    // 通过 row checkbox 选择（不是全选）— 点击 checkbox 不应触发行导航
    // 泄漏（review R 中发现的真实 bug 回归守卫）。
    for (const name of ['Bulk Target A', 'Bulk Target B']) {
      await page
        .getByRole('row')
        .filter({ hasText: name })
        .getByRole('checkbox', { name: '选择行' })
        .check()
    }
    await expect(page).toHaveURL(/\/skills$/)
    await expect(page.getByTestId('skill-bulk-bar')).toContainText('已选择 2 个')
    await page.getByTestId('skill-bulk-bar').getByRole('button', { name: '删除' }).click()

    const dialog = page.getByRole('alertdialog')
    await expect(dialog).toContainText('删除 2 个 skill')
    await expect(dialog).toContainText('Bulk Target A')
    await expect(dialog).toContainText('已连接 1 个 Agent')
    await dialog.getByRole('button', { name: '删除' }).click()

    await expect.poll(() => deleted.length, { timeout: 15_000 }).toBe(2)
    await expect(page.getByText('已删除 2 个 skill')).toBeVisible()
    await expect(page.getByText('Bulk Target A')).toBeHidden()
    // 删除后选择状态会重置（key remount 契约）。
    await expect(page.getByTestId('skill-bulk-bar')).toBeHidden()
  })
})
