'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { systemLlmSettingsApi, userLlmSettingsApi } from '@/lib/api/system-llm-settings'
import { systemLlmSettingQueryKeys } from '@/lib/query-keys/system-llm-settings'
import type {
  SystemLlmRole,
  SystemLlmSettingUpdate,
  SystemLlmTestRequest,
} from '@/lib/types/system-llm-setting'

const api = (personal: boolean) => (personal ? userLlmSettingsApi : systemLlmSettingsApi)

export function useSystemLlmSettings(personal = false) {
  return useQuery({
    queryKey: systemLlmSettingQueryKeys.list(personal),
    queryFn: api(personal).list,
    staleTime: 30_000,
  })
}

export function useSystemLlmReadiness() {
  return useQuery({
    queryKey: systemLlmSettingQueryKeys.readiness,
    queryFn: userLlmSettingsApi.readiness,
    staleTime: 30_000,
  })
}

export function useUpdateSystemLlmSetting(personal = false) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ role, data }: { role: SystemLlmRole; data: SystemLlmSettingUpdate }) =>
      api(personal).update(role, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: systemLlmSettingQueryKeys.lists })
      void qc.invalidateQueries({ queryKey: systemLlmSettingQueryKeys.readiness })
    },
  })
}

export function useTestSystemLlmSetting(personal = false) {
  return useMutation({
    mutationFn: (data: SystemLlmTestRequest) => api(personal).test(data),
  })
}
