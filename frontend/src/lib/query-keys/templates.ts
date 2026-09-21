export const templateQueryKeys = {
  list: (category?: string) => ['templates', category] as const,
  localized: (category: string | undefined, locale: string) =>
    ['templates', category, locale] as const,
}
