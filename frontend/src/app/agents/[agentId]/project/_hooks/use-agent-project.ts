'use client'

import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { agentProjectApi } from '../_lib/agent-project-api'

export const agentProjectKeys = {
  project: (agentId: string) => ['agent-project', agentId] as const,
  versions: (agentId: string) => [...agentProjectKeys.project(agentId), 'versions'] as const,
  version: (agentId: string, id: string) => [...agentProjectKeys.versions(agentId), id] as const,
  sets: (agentId: string) => [...agentProjectKeys.project(agentId), 'sets'] as const,
  runs: (agentId: string) => [...agentProjectKeys.project(agentId), 'runs'] as const,
  compare: (agentId: string, left: string, right: string) =>
    [...agentProjectKeys.project(agentId), 'compare', left, right] as const,
}

export function useAgentProject(agentId: string) {
  const queryClient = useQueryClient()
  const project = useQuery({
    queryKey: agentProjectKeys.project(agentId),
    queryFn: () => agentProjectApi.get(agentId),
    refetchInterval: (query) =>
      ['pending', 'running'].includes(query.state.data?.report_json?.optimization?.state ?? '')
        ? 1500
        : false,
  })
  const versions = useQuery({
    queryKey: agentProjectKeys.versions(agentId),
    queryFn: () => agentProjectApi.versions(agentId),
    enabled: !!project.data,
  })
  const optimization = project.data?.report_json?.optimization
  useEffect(() => {
    if (optimization) {
      void queryClient.invalidateQueries({ queryKey: agentProjectKeys.versions(agentId) })
      void queryClient.invalidateQueries({ queryKey: agentProjectKeys.runs(agentId) })
    }
  }, [optimization, agentId, queryClient])
  const create = useMutation({
    mutationFn: () => agentProjectApi.create(agentId),
    onSuccess: (data) => {
      queryClient.setQueryData(agentProjectKeys.project(agentId), data)
      void queryClient.invalidateQueries({ queryKey: agentProjectKeys.versions(agentId) })
    },
  })
  return { project, versions, create }
}
