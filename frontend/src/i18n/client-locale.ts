import { DEFAULT_LOCALE, isSupportedLocale, LOCALE_COOKIE_NAME } from './locales'

const LOCALE_COOKIE_MAX_AGE_SECONDS = 31_536_000

export function persistLocaleCookie(locale: string) {
  if (typeof document === 'undefined') return
  document.cookie = `${LOCALE_COOKIE_NAME}=${encodeURIComponent(locale)}; path=/; max-age=${LOCALE_COOKIE_MAX_AGE_SECONDS}; SameSite=Lax`
}

/** Read on every message/resume, including after a locale switch. */
export function getActiveClientLocale() {
  if (typeof document === 'undefined') return DEFAULT_LOCALE
  const value = document.cookie
    .split('; ')
    .find((part) => part.startsWith(`${LOCALE_COOKIE_NAME}=`))
    ?.split('=')[1]
  try {
    const locale = value ? decodeURIComponent(value) : document.documentElement.lang
    return isSupportedLocale(locale) ? locale : DEFAULT_LOCALE
  } catch {
    return DEFAULT_LOCALE
  }
}
