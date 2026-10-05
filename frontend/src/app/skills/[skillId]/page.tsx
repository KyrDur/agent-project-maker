import { redirect } from 'next/navigation'

/** skill scope 默认 tab — 跳转到与 legacy content tab 对应的 source（规范 AD-1）。 */
export default async function SkillIndexPage({ params }: { params: Promise<{ skillId: string }> }) {
  const { skillId } = await params
  redirect(`/skills/${skillId}/source`)
}
