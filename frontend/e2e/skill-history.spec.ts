import { mkdir } from 'node:fs/promises'
import path from 'node:path'

import { test, expect } from './fixtures'

const now = '2026-06-01T00:00:00.000Z'

const skill = {
  id: 'skill-history',
  name: 'Korea Weather',
  slug: 'korea-weather',
  description: '稳定整理韩国天气响应。',
  kind: 'package',
  version: '0.1.0',
  storage_path: null,
  content_hash: '333333333333',
  size_bytes: 2048,
  used_by_count: 1,
  package_metadata: null,
  current_revision_id: 'rev-3',
  health: {
    state: 'ready',
    label: '已验证',
    reason: 'Latest evaluation passed for the current skill.',
    severity: 'success',
  },
  latest_evaluation_summary: {
    status: 'completed',
    latest_run_id: 'run-1',
    evaluation_set_id: 'set-1',
    pass_rate: 0.92,
    skill_content_hash: '333333333333',
    created_at: now,
    completed_at: '2026-06-01T00:01:00.000Z',
  },
  last_modified_at: now,
  created_at: now,
  updated_at: now,
  origin_summary: null,
  publication_summary: null,
  installation: null,
}

const revisionOne = {
  id: 'rev-1',
  skill_id: 'skill-history',
  revision_number: 1,
  operation: 'create',
  skill_version: '0.1.0',
  content_hash: '111111111111',
  size_bytes: 512,
  file_count: 1,
  changelog_summary: '首次创建',
  created_at: '2026-06-01T00:00:00.000Z',
}

const revisionThree = {
  id: 'rev-3',
  skill_id: 'skill-history',
  revision_number: 3,
  operation: 'builder_improvement',
  skill_version: '0.1.0',
  content_hash: '333333333333',
  size_bytes: 2048,
  file_count: 3,
  changelog_summary: '改进天气摘要规则',
  created_at: '2026-06-03T00:00:00.000Z',
}

const revisionTwo = {
  id: 'rev-2',
  skill_id: 'skill-history',
  revision_number: 2,
  operation: 'manual_content_update',
  skill_version: '0.1.0',
  content_hash: '222222222222',
  size_bytes: 1024,
  file_count: 2,
  changelog_summary: '修改文案',
  created_at: '2026-06-02T00:00:00.000Z',
}

const revisions = [revisionOne, revisionThree, revisionTwo]

const revisionDetails = {
  'rev-1': {
    ...revisionOne,
    parent_revision_id: null,
    changed_files: [],
    changelog_items: [],
    compatibility_result: null,
    evaluation_summary: null,
    metadata_json: {},
  },
  'rev-2': {
    ...revisionTwo,
    parent_revision_id: 'rev-1',
    changed_files: [{ path: 'SKILL.md', status: 'modified' }],
    changelog_items: [{ title: '修改天气响应语气', path: 'SKILL.md' }],
    compatibility_result: { targets: { openai_codex: { status: 'ok' } } },
    evaluation_summary: { status: 'completed', mean_score: 0.88 },
    metadata_json: {},
  },
  'rev-3': {
    ...revisionThree,
    parent_revision_id: 'rev-2',
    changed_files: [{ path: 'references/weather.md', status: 'added' }],
    changelog_items: [{ title: '添加按地区摘要规则', path: 'references/weather.md' }],
    compatibility_result: { targets: { openai_codex: { status: 'ok' } } },
    evaluation_summary: { status: 'completed', mean_score: 0.92 },
    metadata_json: {},
  },
}

// M4 — revision snapshot file API（diff/read-only source）fixture。
const revisionSkillMd: Record<string, string> = {
  'rev-1': '---\nname: weather\n---\n\n摘要规则 v1\n',
  'rev-2': '---\nname: weather\n---\n\n摘要规则 v2\n',
  'rev-3': '---\nname: weather\n---\n\n摘要规则 v3\n添加按地区摘要\n',
}

function getRevisionDetail(revisionId: string) {
  switch (revisionId) {
    case 'rev-1':
      return revisionDetails['rev-1']
    case 'rev-2':
      return revisionDetails['rev-2']
    case 'rev-3':
      return revisionDetails['rev-3']
    default:
      return null
  }
}

test.describe('Skill history tab', () => {
  test('shows revision history newest first', async ({ page }) => {
    await page.route('**/api/skills**', (route) => {
      const url = new URL(route.request().url())
      const method = route.request().method()
      const pathName = url.pathname

      if (method === 'GET' && pathName === '/api/skills') {
        return route.fulfill({ json: [skill] })
      }
      if (method === 'GET' && pathName === '/api/skills/skill-history') {
        return route.fulfill({ json: skill })
      }
      if (method === 'GET' && pathName === '/api/skills/skill-history/revisions') {
        return route.fulfill({ json: revisions })
      }
      // M4 — revision 文件列表/内容（先于 detail matcher：路径 prefix 重叠）。
      const filesMatch = pathName.match(
        /^\/api\/skills\/skill-history\/revisions\/(rev-\d)\/files$/,
      )
      if (method === 'GET' && filesMatch) {
        const body = revisionSkillMd[filesMatch[1]]
        return route.fulfill({
          json: {
            snapshot_pruned: false,
            files: [{ path: 'SKILL.md', size: body?.length ?? 0, is_binary: false }],
          },
        })
      }
      const contentMatch = pathName.match(
        /^\/api\/skills\/skill-history\/revisions\/(rev-\d)\/files\/content$/,
      )
      if (method === 'GET' && contentMatch) {
        const body = revisionSkillMd[contentMatch[1]]
        if (body && url.searchParams.get('path') === 'SKILL.md') {
          return route.fulfill({ json: { path: 'SKILL.md', content: body } })
        }
        return route.fulfill({ status: 404, json: { detail: 'file not found' } })
      }
      if (method === 'GET' && pathName.startsWith('/api/skills/skill-history/revisions/')) {
        const revisionId = pathName.split('/').at(-1) ?? ''
        const detail = getRevisionDetail(revisionId)
        if (detail) {
          return route.fulfill({ json: detail })
        }
      }

      return route.fulfill({ status: 404, json: { detail: pathName } })
    })

    // Phase 2 studio — 验证 legacy deeplink 也会 redirect 到 versions tab route。
    await page.goto('/skills?detailId=skill-history&tab=history')
    await page.waitForURL(/\/skills\/skill-history\/versions/)
    await expect(page.getByTestId('studio-context-bar')).toContainText('Korea Weather')
    await expect(page.getByRole('heading', { name: 'revision 3', exact: true })).toBeVisible()
    await expect(page.getByText('当前', { exact: true }).first()).toBeVisible()
    await expect(page.getByText(/빌더 개선/)).toBeVisible()
    await expect(page.getByText('revision 3 详情')).toBeVisible()
    await expect(page.getByRole('button', { name: 'revision 3 回滚' })).toBeDisabled()

    await page.getByRole('button', { name: '查看 revision 2' }).click()
    await expect(page.getByText('revision 2 详情')).toBeVisible()
    await expect(page.getByText('修改天气响应语气 · SKILL.md')).toBeVisible()
    await expect(page.getByText('便携兼容性')).toBeVisible()
    await expect(page.getByText('OpenAI/Codex')).toBeVisible()
    // 与 studio context bar 的 "通过率 N%" 发生 substring 冲突 — exact 匹配。
    await expect(page.getByText('通行证', { exact: true })).toBeVisible()

    // ── M4: SKILL.md diff (rev-2 vs parent rev-1) ──────────────────────
    const diffCard = page.getByTestId('revision-diff-card')
    await expect(diffCard).toBeVisible()
    await expect(diffCard).toContainText('- 摘要规则 v1')
    await expect(diffCard).toContainText('+ 摘要规则 v2')

    // ── M4：查看此版本 source → read-only revision viewer ──────────────────
    await diffCard.getByRole('link', { name: '查看此版本的源代码' }).click()
    await page.waitForURL(/\/skills\/skill-history\/source\?revision=rev-2/)
    await expect(page.getByText('revision 2 source')).toBeVisible()
    await expect(page.getByText('只读')).toBeVisible()
    await expect(page.getByText('摘要规则 v2')).toBeVisible()
    // 不应存在编辑 UI（read-only 契约）。
    await expect(page.getByRole('button', { name: '保存文件' })).toBeHidden()

    const captureDir = path.resolve(process.cwd(), '../output/e2e-captures/20260615-skill-history')
    await mkdir(captureDir, { recursive: true })
    await page.screenshot({
      path: path.join(captureDir, 'history-tab-detail.png'),
      fullPage: false,
    })
  })
})
