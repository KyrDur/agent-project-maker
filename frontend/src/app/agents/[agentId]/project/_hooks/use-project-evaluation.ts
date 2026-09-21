'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { agentProjectApi } from '../_lib/agent-project-api'
import { agentProjectKeys } from './use-agent-project'
import type { EvaluationCase } from '../_lib/agent-project-types'

export function useEvaluationReports(agentId: string) {
  const cache = useQueryClient()
  const query = useQuery({
    queryKey: agentProjectKeys.evaluationReports(agentId),
    queryFn: () => agentProjectApi.evaluationReports(agentId),
    refetchInterval: (query) => (query.state.data?.active ? 1500 : false),
  })
  useEffect(() => {
    if (query.data && !query.data.active) {
      void cache.invalidateQueries({ queryKey: agentProjectKeys.report(agentId) })
      void cache.invalidateQueries({ queryKey: agentProjectKeys.comparisons(agentId) })
    }
  }, [query.data, agentId, cache])
  return query
}

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
      query.state.data?.some(
        (run) =>
          run.status === 'pending' ||
          run.status === 'running' ||
          ['pending', 'running'].includes(run.comparison_json?.optimization?.state ?? ''),
      )
        ? 1500
        : false,
  })
  const save = useMutation({
    mutationFn: (data: { id?: string; name: string; cases: EvaluationCase[] }) =>
      agentProjectApi.saveSet(agentId, data),
    onSuccess: () => cache.invalidateQueries({ queryKey: agentProjectKeys.sets(agentId) }),
  })
  const quality = useMutation({
    mutationFn: (setId: string) => agentProjectApi.judgeSet(agentId, setId),
    onSuccess: () => cache.invalidateQueries({ queryKey: agentProjectKeys.sets(agentId) }),
  })
  const start = useMutation({
    mutationFn: (data: { request_id: string; version_id: string; eval_set_id: string }) =>
      agentProjectApi.createRun(agentId, data),
    onSuccess: () => cache.invalidateQueries({ queryKey: agentProjectKeys.project(agentId) }),
  })
  return { sets, runs, save, start, quality }
}

export function useProjectProposals(agentId: string, runId: string) {
  const cache = useQueryClient()
  const refresh = () => cache.invalidateQueries({ queryKey: agentProjectKeys.project(agentId) })
  const generate = useMutation({
    mutationFn: (requestId: string) => agentProjectApi.propose(agentId, runId, requestId),
    onSuccess: refresh,
  })
  const decide = useMutation({
    mutationFn: (data: { id: string; decision: 'accepted' | 'rejected'; reason?: string }) =>
      agentProjectApi.decideProposal(agentId, runId, data.id, data.decision, data.reason),
    onSuccess: refresh,
  })
  const regression = useMutation({
    mutationFn: (data: { id: string; requestId: string }) =>
      agentProjectApi.proposalRegression(agentId, runId, data.id, data.requestId),
    onSuccess: refresh,
  })
  return { generate, decide, regression }
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
    mutationFn: (data: {
      versionId: string
      evaluation_focus: string[]
      evaluation_focus_reason?: string | null
    }) => agentProjectApi.generateCases(agentId, data.versionId, data),
    onSuccess: () => cache.invalidateQueries({ queryKey: agentProjectKeys.sets(agentId) }),
  })
  return { project, plan, cases }
}

export function useProjectOptimization(agentId: string, runId: string) {
  const cache = useQueryClient()
  const refresh = () => cache.invalidateQueries({ queryKey: agentProjectKeys.project(agentId) })
  const analyze = useMutation({
    mutationFn: () => agentProjectApi.analyze(agentId, runId),
    onSuccess: refresh,
  })
  return { analyze }
}
