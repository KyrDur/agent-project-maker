'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useSession } from '@/lib/auth/session'
import { personalAiQueryKeys } from '@/lib/query-keys/personal-ai'
import { systemLlmSettingsApi } from '@/lib/api/system-llm-settings'
import type {
  SystemLlmRole,
  SystemLlmSettingUpdate,
  SystemLlmTestRequest,
} from '@/lib/types/system-llm-setting'

export function useSystemLlmSettings() {
  const { data: user } = useSession()
  return useQuery({
    queryKey: personalAiQueryKeys.settings(user?.id),
    enabled: !!user?.id,
    queryFn: systemLlmSettingsApi.list,
    staleTime: 30_000,
  })
}

export function useSystemLlmReadiness() {
  const { data: user } = useSession()
  return useQuery({
    queryKey: personalAiQueryKeys.readiness(user?.id),
    enabled: !!user?.id,
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
      void qc.invalidateQueries({ queryKey: personalAiQueryKeys.all })
    },
  })
}

export function useTestSystemLlmSetting() {
  return useMutation({
    mutationFn: (data: SystemLlmTestRequest) => systemLlmSettingsApi.test(data),
  })
}
