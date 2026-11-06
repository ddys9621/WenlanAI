/** 工作台左右两栏可拖宽：宽度夹在上下限内，存 localStorage；没拖过时按视口比例给默认宽度 */

export interface PaneLimits {
  min: number
  max: number
  /** 拿不到视口宽度时的默认宽度 */
  fallback: number
  /** 默认宽度占视口的比例（2048 宽时左栏 360、右栏 576） */
  defaultRatio: number
  /** 最多占视口宽度的比例：窄屏上别把中栏挤没 */
  maxRatio: number
}

export const LEFT_PANE: PaneLimits = { min: 232, max: 440, fallback: 288, defaultRatio: 0.175, maxRatio: 0.3 }
export const RIGHT_PANE: PaneLimits = { min: 340, max: 720, fallback: 420, defaultRatio: 0.28, maxRatio: 0.45 }

export const LEFT_PANE_KEY = 'project-pane-left'
export const RIGHT_PANE_KEY = 'project-pane-right'

export function clampWidth(value: number, limits: PaneLimits, viewport?: number): number {
  if (!Number.isFinite(value)) return defaultWidth(limits, viewport)
  const max = viewport ? Math.max(limits.min, Math.min(limits.max, Math.floor(viewport * limits.maxRatio))) : limits.max
  return Math.round(Math.min(max, Math.max(limits.min, value)))
}

export function defaultWidth(limits: PaneLimits, viewport?: number): number {
  return viewport ? clampWidth(viewport * limits.defaultRatio, limits, viewport) : limits.fallback
}

export function readWidth(key: string, limits: PaneLimits, viewport?: number): number {
  const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(key)
  return raw ? clampWidth(Number(raw), limits, viewport) : defaultWidth(limits, viewport)
}

export function writeWidth(key: string, value: number): void {
  if (typeof localStorage !== 'undefined') localStorage.setItem(key, String(Math.round(value)))
}

export function viewportWidth(): number | undefined {
  return typeof window === 'undefined' ? undefined : window.innerWidth
}
