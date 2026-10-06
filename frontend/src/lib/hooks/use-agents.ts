'use client'

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { agentsApi } from '@/lib/api/agents'
import { agentQueryKeys } from '@/lib/query-keys/agents'
import type { AgentCreateRequest, AgentUpdateRequest } from '@/lib/types'

// 保存 skill_ids 会改变技能列表/详情的连接计数（反向聚合）（Phase 2 §2.3）。
// used_by_count 只存在于列表（['skills', params]）·详情（['skills', id]）— 长度为 2 的 key —
// 中。如果用 skillQueryKeys.all（['skills'] prefix）全量清除，staleTime: Infinity
// 契约下的 revision snapshot·evaluation subtree（长度 3+）也会在每次 agent 保存时失效，
// 使不可变 snapshot cache 降级为每次访问都 refetch 的层（R5）。
function invalidateSkillLinkCounts(qc: QueryClient) {
  void qc.invalidateQueries({
    predicate: (query) => query.queryKey[0] === 'skills' && query.queryKey.length === 2,
  })
}

export function useAgents(options?: { readonly enabled?: boolean }) {
  return useQuery({
    queryKey: agentQueryKeys.all,
    queryFn: agentsApi.list,
    enabled: options?.enabled ?? true,
  })
}

export function useAgentSummaries() {
  return useQuery({ queryKey: agentQueryKeys.summary, queryFn: agentsApi.summary })
}

export function useAgent(id: string) {
  return useQuery({
    queryKey: agentQueryKeys.detail(id),
    queryFn: () => agentsApi.get(id),
    enabled: !!id,
  })
}

export function useAgentRuntimeReadiness(id: string) {
  return useQuery({
    queryKey: agentQueryKeys.readiness(id),
    queryFn: () => agentsApi.runtimeReadiness(id),
    enabled: !!id,
    staleTime: 30_000,
  })
}

export function useCreateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: AgentCreateRequest) => agentsApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentQueryKeys.all })
      invalidateSkillLinkCounts(qc)
    },
  })
}

export function useUpdateAgent(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: AgentUpdateRequest) => agentsApi.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentQueryKeys.all })
      qc.invalidateQueries({ queryKey: agentQueryKeys.detail(id) })
      invalidateSkillLinkCounts(qc)
    },
  })
}

export function useDeleteAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => agentsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentQueryKeys.all })
      invalidateSkillLinkCounts(qc)
    },
  })
}

export function useToggleFavorite() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => agentsApi.toggleFavorite(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: agentQueryKeys.all }),
  })
}

export function useGenerateAgentImage(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => agentsApi.generateImage(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentQueryKeys.all })
      qc.invalidateQueries({ queryKey: agentQueryKeys.detail(id) })
    },
  })
}
