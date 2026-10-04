'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocale } from 'next-intl'
import { agentProjectApi } from '../_lib/agent-project-api'
import { agentProjectKeys } from './use-agent-project'
import type { BriefContent } from '../_lib/agent-project-types'

export function useProjectLearning(agentId: string, versionId: string) {
  const cache = useQueryClient()
  const locale = useLocale()
  const refresh = () => cache.invalidateQueries({ queryKey: agentProjectKeys.project(agentId) })
  const brief = useMutation({
    mutationFn: () => agentProjectApi.generateBrief(agentId, versionId, locale),
    onSuccess: refresh,
  })
  const confirm = useMutation({
    mutationFn: (data: { draftHash: string; content: BriefContent }) =>
      agentProjectApi.confirmBrief(agentId, versionId, data.draftHash, data.content),
    onSuccess: refresh,
  })
  const interview = useMutation({
    mutationFn: () => agentProjectApi.interview(agentId, versionId, locale),
  })
  const review = useMutation({
    mutationFn: (data: { runId: string; caseId: string; passed: boolean; reason: string }) =>
      agentProjectApi.reviewCase(agentId, data.runId, data.caseId, data.passed, data.reason),
    onSuccess: refresh,
  })
  const holdout = useMutation({
    mutationFn: (data: { setId: string; requestId: string }) =>
      agentProjectApi.holdout(agentId, data.setId, data.requestId),
    onSuccess: refresh,
  })
  const repeat = useMutation({
    mutationFn: (data: { runId: string; requestId: string; count: number }) =>
      agentProjectApi.repeat(agentId, data.runId, data.requestId, data.count),
    onSuccess: refresh,
  })
  const validate = useMutation({
    mutationFn: (data: { runId: string; setId: string; requestId: string; count: number }) =>
      agentProjectApi.validate(
        agentId,
        data.runId,
        versionId,
        data.setId,
        data.requestId,
        data.count,
      ),
    onSuccess: refresh,
  })
  return { brief, confirm, interview, review, holdout, repeat, validate }
}

export function useReliability(agentId: string, versionId: string, active: boolean) {
  return useQuery({
    queryKey: agentProjectKeys.reliability(agentId, versionId),
    queryFn: () => agentProjectApi.reliability(agentId, versionId),
    enabled: !!versionId,
    refetchInterval: active ? 1500 : false,
  })
}
