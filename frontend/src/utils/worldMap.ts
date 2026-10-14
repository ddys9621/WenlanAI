/** 世界地图的纯函数：标注草稿、改动比对、地点搜索、坐标校验。 */
import type { MapLocation, MapLocationKind } from '@/types/writing'
import type { MarkerDraft } from './mapHistory'

export const KIND_LABELS: Record<MapLocationKind, string> = {
  city: '城池', town: '城镇', village: '村落', sect: '宗门', palace: '宫殿', mountain: '山岳', forest: '森林',
  river: '河流', lake: '湖泊', sea: '海域', desert: '荒漠', ruin: '遗迹', pass: '关隘', island: '岛屿', other: '其他',
}

export interface LocationDraft extends MarkerDraft {
  id: string
  x: number
  y: number
  /** 未定位（坐标为空） */
  unplaced: boolean
}

/** 服务端地点 → 本地标注草稿（未定位的坐标先记 0，unplaced=true） */
export function toDrafts(locations: MapLocation[]): LocationDraft[] {
  return locations.map((l) => ({
    id: l.id, name: l.name, x: l.x ?? 0, y: l.y ?? 0, unplaced: l.x === null || l.y === null,
  }))
}

/** 需要保存的标注：已定位、且坐标与服务端不同（含新定位的） */
export function changedMarkers(saved: MapLocation[], drafts: LocationDraft[]): Array<{ id: string; name: string; x: number; y: number }> {
  const byId = new Map(saved.map((l) => [l.id, l]))
  return drafts
    .filter((d) => !d.unplaced)
    .filter((d) => {
      const s = byId.get(d.id)
      return !s || s.x !== d.x || s.y !== d.y
    })
    .map((d) => ({ id: d.id, name: d.name, x: d.x, y: d.y }))
}

/** 重新读取服务端地点后：keepLocal 时保留本地还没保存的坐标调整，其余跟服务端走；服务端删掉的地点直接丢掉 */
export function rebaseDrafts(
  oldSaved: MapLocation[], oldDrafts: LocationDraft[], newSaved: MapLocation[], keepLocal: boolean,
): LocationDraft[] {
  const fresh = toDrafts(newSaved)
  if (!keepLocal) return fresh
  const local = new Map(changedMarkers(oldSaved, oldDrafts).map((m) => [m.id, m]))
  return fresh.map((d) => {
    const mine = local.get(d.id)
    return mine ? { ...d, x: mine.x, y: mine.y, unplaced: false } : d
  })
}

/** 按地点名 / 区域 / 绑定的原文地点搜（精确子串） */
export function matchLocations(locations: MapLocation[], query: string): MapLocation[] {
  const q = query.trim()
  if (!q) return locations
  return locations.filter((l) => l.name.includes(q) || (l.region ?? '').includes(q) || l.source_names.some((s) => s.includes(q)))
}

const round2 = (v: number) => Math.round(v * 100) / 100

/** 指针位置换算出的百分比坐标：落在底图外返回 null（不贴边造点） */
export function clampPercent(x: number, y: number): [number, number] | null {
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > 100 || y < 0 || y > 100) return null
  return [round2(x), round2(y)]
}
