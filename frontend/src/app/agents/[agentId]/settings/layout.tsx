import type { ReactNode } from 'react'
import { ScopedIntlProvider } from '@/i18n/scoped-messages'

export default function AgentSettingsLayout({ children }: { children: ReactNode }) {
  return <ScopedIntlProvider namespaces={['agentProject']}>{children}</ScopedIntlProvider>
}
