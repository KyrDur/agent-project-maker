export const middlewareQueryKeys = {
  all: ['middlewares'] as const,
  localized: (locale: string) => ['middlewares', locale] as const,
}
