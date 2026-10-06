const TIMEZONE = 'Asia/Seoul'
const LOCALE = 'zh-CN'

const dayKeyFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

const todayTimeFmt = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIMEZONE,
  hour: 'numeric',
  minute: '2-digit',
})

const monthDayFmt = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIMEZONE,
  month: 'numeric',
  day: 'numeric',
})

const longDateFmt = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIMEZONE,
  year: 'numeric',
  month: 'long',
  day: 'numeric',
})

const mediumDateFmt = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIMEZONE,
  year: 'numeric',
  month: 'short',
  day: 'numeric',
})

function dayKey(d: Date): string {
  return dayKeyFmt.format(d)
}

/**
 * 将 backend timestamp（timezone-naive UTC）按 UTC 解析为 Date。
 * 若已包含 'Z' / '+09:00' 等 timezone 标记，则原样使用。
 */
export function parseTimestamp(value: Date | string): Date {
  if (value instanceof Date) return value
  const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(value)
  return new Date(hasTz ? value : value + 'Z')
}

/**
 * 简短的韩语相对时间（基于 KST）：
 * - 今天  → "上午 10:30"
 * - 昨天  → yesterdayLabel
 * - 其他 → "5. 22."
 *
 * use-intl `dateTime` 在某些情况下不会一致应用选项中的 `timeZone`，
 * 因此直接使用 Intl.DateTimeFormat，确保行为不依赖环境。
 */
export function formatRelativeShort(
  date: Date | string,
  yesterdayLabel: string,
  now: Date = new Date(),
): string {
  const d = parseTimestamp(date)
  const dKey = dayKey(d)
  const nowKey = dayKey(now)

  if (dKey === nowKey) {
    return todayTimeFmt.format(d)
  }

  const yesterday = new Date(now.getTime() - 86_400_000)
  if (dKey === dayKey(yesterday)) {
    return yesterdayLabel
  }

  return monthDayFmt.format(d)
}

/**
 * "2026年5月1日" — KST-anchored long date for editorial / hero surfaces.
 * Backend returns timezone-naive UTC; ``parseTimestamp`` normalizes that
 * before formatting so visitors in any TZ see the same date the author saw.
 */
export function formatLongDate(date: Date | string): string {
  return longDateFmt.format(parseTimestamp(date))
}

/** "2026. 5. 1." — KST-anchored short date for footer / meta strips. */
export function formatMediumDate(date: Date | string): string {
  return mediumDateFmt.format(parseTimestamp(date))
}

const shortMonthDayFmt = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIMEZONE,
  month: 'short',
  day: 'numeric',
})

const relativeFmt = new Intl.RelativeTimeFormat(LOCALE, {
  numeric: 'auto',
})

/**
 * "刚刚 / N分钟前 / N小时前 / N天前 / 5月22日" — KST-anchored relative time
 * for compact meta strips (e.g., agent card footer "last used").
 */
export function formatRelativeKo(date: Date | string, now: Date = new Date()): string {
  const d = parseTimestamp(date)
  const diffSec = Math.max(0, (now.getTime() - d.getTime()) / 1000)
  if (diffSec < 60) return relativeFmt.format(0, 'second')
  if (diffSec < 3600) return relativeFmt.format(-Math.floor(diffSec / 60), 'minute')
  if (diffSec < 86_400) return relativeFmt.format(-Math.floor(diffSec / 3600), 'hour')
  if (diffSec < 86_400 * 7) return relativeFmt.format(-Math.floor(diffSec / 86_400), 'day')
  return shortMonthDayFmt.format(d)
}
