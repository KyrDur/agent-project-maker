export const systemLlmSettingQueryKeys = {
  lists: ['system-llm-settings'] as const,
  list: (personal: boolean) => ['system-llm-settings', personal] as const,
  readiness: ['system-llm-readiness'] as const,
}
