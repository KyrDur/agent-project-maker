export const personalAiQueryKeys = {
  all: ['personal-ai'] as const,
  settings: (userId: string | undefined) => ['personal-ai', userId, 'settings'] as const,
  readiness: (userId: string | undefined) => ['personal-ai', userId, 'readiness'] as const,
}
