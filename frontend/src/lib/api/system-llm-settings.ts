import { apiFetch } from './client'
import type {
  SystemLlmRole,
  SystemLlmSettingOut,
  SystemLlmTestRequest,
  SystemLlmSettingUpdate,
} from '@/lib/types/system-llm-setting'
import type { ModelTestResponse } from '@/lib/types/model'

export interface SystemLlmReadiness {
  role: Exclude<SystemLlmRole, 'image'>
  configured: boolean
  provider: string | null
  model_name: string | null
}

// Operator-managed System LLM role slots (ADR-019). super_user only; the PUT
// route requires CSRF — `apiFetch` injects `X-CSRF-Token` for mutations.
export const systemLlmSettingsApi = {
  list: () => apiFetch<SystemLlmSettingOut[]>('/api/system-llm-settings'),
  readiness: () => apiFetch<SystemLlmReadiness[]>('/api/system-llm-settings/readiness'),
  test: (data: SystemLlmTestRequest) =>
    apiFetch<ModelTestResponse>('/api/system-llm-settings/test', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (role: SystemLlmRole, data: SystemLlmSettingUpdate) =>
    apiFetch<SystemLlmSettingOut>(`/api/system-llm-settings/${role}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
}
