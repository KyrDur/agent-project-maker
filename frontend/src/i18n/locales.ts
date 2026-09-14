export const LOCALE_COOKIE_NAME = 'moldy_locale'
export const DEFAULT_LOCALE = 'zh-CN'
export const SUPPORTED_LOCALES = ['zh-CN', 'en', 'ko'] as const

export type AppLocale = (typeof SUPPORTED_LOCALES)[number]

export function isSupportedLocale(value: string | undefined): value is AppLocale {
  return SUPPORTED_LOCALES.some((locale) => locale === value)
}
