import { ProjectWorkbench } from './_components/project-workbench'
import { ScopedIntlProvider } from '@/i18n/scoped-messages'

export default async function AgentProjectPage({
  params,
}: {
  params: Promise<{ agentId: string }>
}) {
  const { agentId } = await params
  return (
    <ScopedIntlProvider namespaces={['agentProject']}>
      <ProjectWorkbench agentId={agentId} />
    </ScopedIntlProvider>
  )
}
