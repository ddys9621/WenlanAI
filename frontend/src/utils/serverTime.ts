/** 后端时间戳多是无时区的 UTC（SQLite CURRENT_TIMESTAMP / utcnow）：没有时区标记的一律按 UTC 解析，再按本地时区显示。 */

const ZONE = /([zZ]|[+-]\d{2}:?\d{2})$/

export function parseServerTime(value: string | null | undefined): Date | null {
  if (!value) return null
  const text = value.trim().replace(' ', 'T')
  const date = new Date(ZONE.test(text) ? text : `${text}Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatServerTime(value: string | null | undefined): string {
  const date = parseServerTime(value)
  return date ? date.toLocaleString('zh-CN', { hour12: false }) : ''
}
