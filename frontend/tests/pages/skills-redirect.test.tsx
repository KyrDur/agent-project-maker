import { describe, expect, it, vi } from 'vitest'

// legacy `?detailId=&tab=` server redirect 的安全网契约 (R5) —
// encodeURIComponent 不会转义 dot-segment，因此 `..` 会
// `/skills/../source` → 经浏览器规范化后逃逸到 /skills 之外。
// 仅对安全的单一 segment（排除 dot-segment）进行 redirect，其余渲染列表。

vi.mock('next/navigation', () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`)
  }),
}))

vi.mock('@/app/skills/_components/skills-page-client', () => ({
  SkillsPageClient: () => null,
}))

import SkillsPage from '@/app/skills/page'

const VALID_ID = '11111111-2222-4333-8444-555555555555'

async function run(params: Record<string, string>) {
  return SkillsPage({ searchParams: Promise.resolve(params) })
}

describe('SkillsPage legacy redirect', () => {
  it('正常 detailId 会 redirect 到 studio route（包含 tab 映射）', async () => {
    await expect(run({ detailId: VALID_ID, tab: 'history' })).rejects.toThrow(
      `REDIRECT:/skills/${VALID_ID}/versions`,
    )
    await expect(run({ detailId: VALID_ID })).rejects.toThrow(
      `REDIRECT:/skills/${VALID_ID}/source`,
    )
    // mock E2E fixture 使用非 UUID id — 如果强制收窄为 UUID，这一契约会被破坏。
    await expect(run({ detailId: 'skill-history', tab: 'history' })).rejects.toThrow(
      'REDIRECT:/skills/skill-history/versions',
    )
  })

  it('dot-segment/路径逃逸 detailId 不会 redirect，而是收敛到列表', async () => {
    // `..` → /skills/../source → /source 逃逸类别 (R5)
    await expect(run({ detailId: '..' })).resolves.toBeTruthy()
    await expect(run({ detailId: '.' })).resolves.toBeTruthy()
    await expect(run({ detailId: 'a/b' })).resolves.toBeTruthy()
    await expect(run({ detailId: 'a b' })).resolves.toBeTruthy()
  })
})
