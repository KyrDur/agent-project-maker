'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { agentProjectApi } from '../_lib/agent-project-api'
import { agentProjectKeys } from './use-agent-project'
import type { EvaluationCase } from '../_lib/agent-project-types'

export function useProjectVersions(agentId: string, selected: string) {
  const cache = useQueryClient()
  const detail = useQuery({
    queryKey: agentProjectKeys.version(agentId, selected),
    queryFn: () => agentProjectApi.version(agentId, selected),
    enabled: !!selected,
  })
  const create = useMutation({
    mutationFn: (requestId: string) => agentProjectApi.createVersion(agentId, requestId),
    onSuccess: () => cache.invalidateQueries({ queryKey: agentProjectKeys.versions(agentId) }),
  })
  return { detail, create }
}

export function useProjectEvaluation(agentId: string) {
  const cache = useQueryClient()
  const sets = useQuery({
    queryKey: agentProjectKeys.sets(agentId),
    queryFn: () => agentProjectApi.sets(agentId),
  })
  const runs = useQuery({
    queryKey: agentProjectKeys.runs(agentId),
    queryFn: () => agentProjectApi.runs(agentId),
    refetchInterval: (query) =>
      query.state.data?.some((run) => run.status === 'pending' || run.status === 'running')
        ? 1500
        : false,
  })
  const save = useMutation({
    mutationFn: (data: { id?: string; name: string; cases: EvaluationCase[] }) =>
      agentProjectApi.saveSet(agentId, data),
    onSuccess: () => cache.invalidateQueries({ queryKey: agentProjectKeys.sets(agentId) }),
  })
  const start = useMutation({
    mutationFn: (data: { request_id: string; version_id: string; eval_set_id: string }) =>
      agentProjectApi.createRun(agentId, data),
    onSuccess: () => cache.invalidateQueries({ queryKey: agentProjectKeys.project(agentId) }),
  })
  return { sets, runs, save, start }
}

export function useProjectComparison(agentId: string, left: string, right: string) {
  return useQuery({
    queryKey: agentProjectKeys.compare(agentId, left, right),
    queryFn: () => agentProjectApi.compare(agentId, left, right),
    enabled: !!left && !!right && left !== right,
  })
}

export function useProjectGeneration(agentId: string) {
  const cache = useQueryClient()
  const project = useQuery({
    queryKey: agentProjectKeys.project(agentId),
    queryFn: () => agentProjectApi.get(agentId),
    refetchOnMount: false,
  })
  const plan = useMutation({
    mutationFn: (versionId: string) => agentProjectApi.generateSpec(agentId, versionId),
    onSuccess: () => cache.invalidateQueries({ queryKey: agentProjectKeys.project(agentId) }),
  })
  const cases = useMutation({
    mutationFn: (versionId: string) => agentProjectApi.generateCases(agentId, versionId),
    onSuccess: () => cache.invalidateQueries({ queryKey: agentProjectKeys.sets(agentId) }),
  })
  return { project, plan, cases }
}
