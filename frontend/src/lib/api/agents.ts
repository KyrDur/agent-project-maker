import { apiFetch } from './client'
import type { Agent, AgentCreateRequest, AgentSummary, AgentUpdateRequest } from '@/lib/types'

export interface AgentRuntimeReadiness {
  ready: boolean
  code: string | null
  model: {
    id: string
    provider: string
    model_name: string
    display_name: string
  } | null
  credential: {
    id: string
    name: string
    status: string
    masked: boolean
  } | null
}

export const agentsApi = {
  list: () => apiFetch<Agent[]>('/api/agents'),
  summary: () => apiFetch<AgentSummary[]>('/api/agents/summary'),
  get: (id: string) => apiFetch<Agent>(`/api/agents/${id}`),
  create: (data: AgentCreateRequest) =>
    apiFetch<Agent>('/api/agents', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: AgentUpdateRequest) =>
    apiFetch<Agent>(`/api/agents/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => apiFetch<void>(`/api/agents/${id}`, { method: 'DELETE' }),
  toggleFavorite: (id: string) =>
    apiFetch<Agent>(`/api/agents/${id}/favorite`, { method: 'PATCH' }),
  generateImage: (id: string) =>
    apiFetch<{ image_url: string }>(`/api/agents/${id}/image`, { method: 'POST' }),
  runtimeReadiness: (id: string) =>
    apiFetch<AgentRuntimeReadiness>(`/api/agents/${id}/runtime-readiness`),
}
