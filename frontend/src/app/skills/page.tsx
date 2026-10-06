import { redirect } from 'next/navigation'

import { SkillsPageClient } from './_components/skills-page-client'
import { legacyDetailTabToStudioTab } from './_lib/skill-studio-tabs'

/**
 * list tab。legacy `?detailId=&tab=` deeplink（旧 detail dialog）会由 server redirect
 * 到 studio route — 即使外部域名再次产生新的入口，这里也作为
 * 永久 safety net（Phase 2 规范 AD-1）。
 */
export default async function SkillsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const params = await searchParams
  const detailId = typeof params.detailId === 'string' ? params.detailId : null
  // encodeURIComponent 不会 escape dot-segment（`.`/`..`），因此
  // `?detailId=..` 会形成 `/skills/../source` → 被浏览器规范化后逃逸到 /skills 之外。
  // 逃逸 (R5). 只允许单一 segment 字符集并明确拒绝 dot-segment
  // （强制 UUID 会破坏使用非 UUID fixture 的 mock E2E 契约）。异常值统一
  // 收敛到列表。
  if (detailId && SAFE_DETAIL_ID.test(detailId)) {
    const tab = typeof params.tab === 'string' ? params.tab : null
    redirect(`/skills/${encodeURIComponent(detailId)}/${legacyDetailTabToStudioTab(tab)}`)
  }
  return <SkillsPageClient />
}

const SAFE_DETAIL_ID = /^(?!\.{1,2}$)[A-Za-z0-9._-]+$/
