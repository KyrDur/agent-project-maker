import { SkillTabPageClient } from '../_components/skill-tab-page-client'

export default async function SkillSourcePage({
  params,
  searchParams,
}: {
  params: Promise<{ skillId: string }>
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const { skillId } = await params
  const query = await searchParams
  // `?revision=` — versions tab 的 "查看此版本的源代码" read-only 模式（规范 AD-6）。
  const revision = typeof query.revision === 'string' ? query.revision : null
  return <SkillTabPageClient skillId={skillId} tab="source" revisionId={revision} />
}
