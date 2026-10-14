/** 世界地图标注的本地撤销（参考岚笺：最多 50 步；保存回执只清掉提交前的步骤，提交后的修改仍可撤销）。 */

export interface MarkerDraft {
  id?: string
  name: string
  x: number
  y: number
}

export const MAX_HISTORY = 50

export interface MapHistory {
  /** 每一步改动之前的完整标注快照 */
  past: MarkerDraft[][]
  /** past[0] 的绝对序号（超出上限丢掉最早的步骤时前移） */
  base: number
}

const clone = (snapshot: MarkerDraft[]): MarkerDraft[] => snapshot.map((m) => ({ ...m }))

export function createHistory(): MapHistory {
  return { past: [], base: 0 }
}

export function pushSnapshot(history: MapHistory, snapshot: MarkerDraft[]): MapHistory {
  const past = [...history.past, clone(snapshot)]
  const drop = Math.max(0, past.length - MAX_HISTORY)
  return { past: past.slice(drop), base: history.base + drop }
}

export function undo(history: MapHistory): { history: MapHistory; snapshot: MarkerDraft[] | null } {
  if (history.past.length === 0) return { history, snapshot: null }
  return {
    history: { past: history.past.slice(0, -1), base: history.base },
    snapshot: clone(history.past[history.past.length - 1]),
  }
}

/** 发起保存时记下的边界（绝对序号） */
export function historyBoundary(history: MapHistory): number {
  return history.base + history.past.length
}

/** 保存成功：只清掉边界之前的步骤 */
export function markSaved(history: MapHistory, boundary: number): MapHistory {
  const cut = Math.min(Math.max(0, boundary - history.base), history.past.length)
  return { past: history.past.slice(cut), base: history.base + cut }
}
