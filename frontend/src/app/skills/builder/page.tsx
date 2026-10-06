import { Suspense } from 'react'

import { SkillBuilderIndexClient } from './_components/skill-builder-index-client'

/** builder index — session history + 启动 CTA。用 Suspense 处理 useSearchParams CSR bailout。 */
export default function SkillBuilderIndexPage() {
  return (
    <Suspense fallback={null}>
      <SkillBuilderIndexClient />
    </Suspense>
  )
}
