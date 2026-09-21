export const agentQueryKeys = {
  readiness: (agentId: string) => ['agents', agentId, 'runtime-readiness'] as const,
  all: ['agents'] as const,
  summary: ['agents', 'summary'] as const,
  detail: (agentId: string | null | undefined) => ['agents', agentId] as const,
}
