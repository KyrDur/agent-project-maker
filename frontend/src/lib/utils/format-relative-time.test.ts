import { describe, expect, it } from 'vitest'

import { formatDisplayDate } from './display-format'
import { formatRelativeShort, formatRelativeTime } from './format-relative-time'

describe('中文日期显示', () => {
  it('按上海午夜区分今天和昨天，并把无时区时间戳作为 UTC 解析', () => {
    const now = new Date('2026-10-06T16:30:00Z')
    expect(formatRelativeShort('2026-10-06T15:30:00', '昨天', now)).toBe('昨天')
    expect(formatRelativeShort('2026-10-06T16:00:00', '昨天', now)).toBe('0:00')
    expect(formatRelativeTime('2026-10-06T16:00:00', now)).toBe('30分钟前')
  })

  it('日期默认使用上海时区，同时保留显式时区覆盖', () => {
    const timestamp = '2026-10-06T15:30:00Z'
    const format = { year: 'numeric', month: '2-digit', day: '2-digit' } as const
    expect(formatDisplayDate(timestamp, { format })).toBe('2026/10/06')
    expect(formatDisplayDate(timestamp, { format, timeZone: 'Asia/Tokyo' })).toBe('2026/10/07')
  })
})
