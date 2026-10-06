import { Suspense, type ReactNode } from 'react'
import { ScopedIntlProvider } from '@/i18n/scoped-messages'
import { SkillStudioShell } from './_components/skill-studio-shell'

const SKILL_MESSAGE_NAMESPACES = ['credentials', 'marketplace', 'skill'] as const

export default function SkillsLayout({ children }: { children: ReactNode }) {
  return (
    <ScopedIntlProvider namespaces={SKILL_MESSAGE_NAMESPACES}>
      {/* Studio shell(tab bar+context bar)包裹 /skills 下全部内容。flex chain
          (min-h-0)是保留 Builder chat 内部 scroll contract(app-layout → chat-client)的
          必要条件 — Phase 2 spec AD-2。Suspense 是 shell 的
          useSearchParams（Builder index ?skillId= scope）应对 CSR bailout。 */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <Suspense fallback={null}>
          <SkillStudioShell />
        </Suspense>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
      </div>
    </ScopedIntlProvider>
  )
}
