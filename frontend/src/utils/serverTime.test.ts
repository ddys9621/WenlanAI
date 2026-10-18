import { describe, expect, it } from 'vitest'
import { formatServerTime, parseServerTime } from './serverTime'

describe('parseServerTime', () => {
  it('没有时区标记的按 UTC 解析（SQLite CURRENT_TIMESTAMP / utcnow）', () => {
    const utc = Date.UTC(2026, 9, 14, 0, 27, 30)
    expect(parseServerTime('2026-10-14T00:27:30')?.getTime()).toBe(utc)
    expect(parseServerTime('2026-10-14 00:27:30')?.getTime()).toBe(utc)
    expect(parseServerTime('2026-10-14T00:27:30.123456')?.getTime()).toBe(utc + 123)
  })

  it('带时区的照原样解析', () => {
    expect(parseServerTime('2026-10-14T00:27:30Z')?.getTime()).toBe(Date.UTC(2026, 9, 14, 0, 27, 30))
    expect(parseServerTime('2026-10-14T08:27:30+08:00')?.getTime()).toBe(Date.UTC(2026, 9, 14, 0, 27, 30))
  })

  it('空值或无法解析返回 null / 空串', () => {
    expect(parseServerTime(null)).toBeNull()
    expect(parseServerTime('不是时间')).toBeNull()
    expect(formatServerTime(undefined)).toBe('')
  })
})
