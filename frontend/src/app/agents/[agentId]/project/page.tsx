import { ProjectWorkbench } from './_components/project-workbench'

export default async function AgentProjectPage({
  params,
}: {
  params: Promise<{ agentId: string }>
}) {
  const { agentId } = await params
  return <ProjectWorkbench agentId={agentId} />
}
