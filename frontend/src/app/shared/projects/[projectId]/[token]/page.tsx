import { ScopedIntlProvider } from '@/i18n/scoped-messages'
import { PublicProject } from './_components/public-project'

export const metadata = { robots: { index: false, follow: false }, referrer: 'no-referrer' }

export default async function Page({
  params,
}: {
  params: Promise<{ projectId: string; token: string }>
}) {
  const { projectId, token } = await params
  return (
    <ScopedIntlProvider namespaces={['agentProject']}>
      <PublicProject projectId={projectId} token={token} />
    </ScopedIntlProvider>
  )
}
