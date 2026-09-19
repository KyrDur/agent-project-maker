'use client'

import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { agentProjectApi } from '../_lib/agent-project-api'

export const agentProjectKeys = {
  evaluationReports: (agentId: string) =>
    [...agentProjectKeys.project(agentId), 'evaluation-reports'] as const,
  report: (agentId: string) => ['agent-project', agentId, 'portfolio-report'] as const,
  project: (agentId: string) => ['agent-project', agentId] as const,
  versions: (agentId: string) => [...agentProjectKeys.project(agentId), 'versions'] as const,
  version: (agentId: string, id: string) => [...agentProjectKeys.versions(agentId), id] as const,
  sets: (agentId: string) => [...agentProjectKeys.project(agentId), 'sets'] as const,
  runs: (agentId: string) => [...agentProjectKeys.project(agentId), 'runs'] as const,
  comparisons: (agentId: string) => [...agentProjectKeys.project(agentId), 'compare'] as const,
  compare: (agentId: string, left: string, right: string) =>
    [...agentProjectKeys.comparisons(agentId), left, right] as const,
}

export function useAgentProject(agentId: string) {
  const queryClient = useQueryClient()
  const project = useQuery({
    queryKey: agentProjectKeys.project(agentId),
    queryFn: () => agentProjectApi.get(agentId),
    refetchInterval: (query) =>
      (query.state.data?.builder_session_id &&
        query.state.data?.requirements_json?.bootstrap?.stage !== 'results') ||
      ['pending', 'running'].includes(query.state.data?.report_json?.optimization?.state ?? '')
        ? query.state.data?.requirements_json?.bootstrap?.error
          ? 5000
          : 1500
        : false,
  })
  const versions = useQuery({
    queryKey: agentProjectKeys.versions(agentId),
    queryFn: () => agentProjectApi.versions(agentId),
    enabled: !!project.data,
  })
  const resumed = useRef(new Set<string>())
  const builderSessionId = project.data?.builder_session_id
  const bootstrapStage = project.data?.requirements_json?.bootstrap?.stage
  const bootstrap = useMutation({
    mutationFn: () => agentProjectApi.bootstrap(agentId),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: agentProjectKeys.project(agentId) }),
  })
  const resumeBootstrap = bootstrap.mutate
  useEffect(() => {
    if (builderSessionId && !resumed.current.has(agentId) && bootstrapStage !== 'results') {
      resumed.current.add(agentId)
      resumeBootstrap()
    }
  }, [agentId, builderSessionId, bootstrapStage, resumeBootstrap])
  useEffect(() => {
    if (bootstrapStage) {
      void queryClient.invalidateQueries({ queryKey: agentProjectKeys.evaluationReports(agentId) })
      void queryClient.invalidateQueries({ queryKey: agentProjectKeys.sets(agentId) })
      void queryClient.invalidateQueries({ queryKey: agentProjectKeys.runs(agentId) })
      void queryClient.invalidateQueries({ queryKey: agentProjectKeys.versions(agentId) })
    }
  }, [bootstrapStage, agentId, queryClient])
  const optimization = project.data?.report_json?.optimization
  useEffect(() => {
    if (optimization) {
      void queryClient.invalidateQueries({ queryKey: agentProjectKeys.evaluationReports(agentId) })
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
  return { project, versions, create, bootstrap }
}
