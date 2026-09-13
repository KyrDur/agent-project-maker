'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import { agentProjectApi } from '../_lib/agent-project-api'
import type { ResumeStyle } from '../_lib/agent-project-types'
import { agentProjectKeys } from './use-agent-project'

export function useProjectPortfolio(agentId: string) {
  const report = useQuery({
    queryKey: agentProjectKeys.report(agentId),
    queryFn: () => agentProjectApi.report(agentId),
  })
  const generate = useMutation({
    mutationFn: () => agentProjectApi.report(agentId, true),
    onSuccess: () => report.refetch(),
  })
  const resume = useMutation({
    mutationFn: (style: ResumeStyle) => agentProjectApi.resume(agentId, style),
  })
  const share = useMutation({
    mutationFn: (revoke: boolean) => agentProjectApi.share(agentId, revoke),
  })
  return { report, generate, resume, share }
}
