'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { systemLlmSettingsApi } from '@/lib/api/system-llm-settings'
import type {
  SystemLlmRole,
  SystemLlmSettingUpdate,
  SystemLlmTestRequest,
} from '@/lib/types/system-llm-setting'

const KEY_LIST = ['system-llm-settings'] as const
const KEY_READINESS = ['system-llm-readiness'] as const

export function useSystemLlmSettings() {
  return useQuery({
    queryKey: KEY_LIST,
    queryFn: systemLlmSettingsApi.list,
    staleTime: 30_000,
  })
}

export function useSystemLlmReadiness() {
  return useQuery({
    queryKey: KEY_READINESS,
    queryFn: systemLlmSettingsApi.readiness,
    staleTime: 30_000,
  })
}

export function useUpdateSystemLlmSetting() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ role, data }: { role: SystemLlmRole; data: SystemLlmSettingUpdate }) =>
      systemLlmSettingsApi.update(role, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: KEY_LIST })
      void qc.invalidateQueries({ queryKey: KEY_READINESS })
    },
  })
}

export function useTestSystemLlmSetting() {
  return useMutation({
    mutationFn: (data: SystemLlmTestRequest) => systemLlmSettingsApi.test(data),
  })
}
