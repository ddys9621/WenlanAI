import { describe, expect, it } from 'vitest'
import type { MapLocation } from '@/types/writing'
import { changedMarkers, clampPercent, matchLocations, rebaseDrafts, toDrafts } from './worldMap'

const loc = (id: string, name: string, x: number | null, y: number | null, extra: Partial<MapLocation> = {}): MapLocation => ({
  id, name, x, y, kind: 'other', region: null, description: null, source_names: [], origin: 'author', ...extra,
})

describe('toDrafts / changedMarkers', () => {
  it('只把坐标真的变了的已定位地点交给保存', () => {
    const saved = [loc('a', '青云宗', 10, 10), loc('b', '黑风岭', 20, 20), loc('c', '小镇', null, null)]
    const drafts = toDrafts(saved)
    expect(changedMarkers(saved, drafts)).toEqual([])
    drafts[0] = { ...drafts[0], x: 12.5 }
    drafts[2] = { ...drafts[2], x: 50, y: 60, unplaced: false }  // 新定位
    expect(changedMarkers(saved, drafts)).toEqual([
      { id: 'a', name: '青云宗', x: 12.5, y: 10 },
      { id: 'c', name: '小镇', x: 50, y: 60 },
    ])
  })
})

describe('rebaseDrafts', () => {
  it('重新读取后保留本地还没保存的坐标调整，其余跟服务端走', () => {
    const oldSaved = [loc('a', '青云宗', 10, 10), loc('b', '黑风岭', 20, 20)]
    const drafts = toDrafts(oldSaved)
    drafts[0] = { ...drafts[0], x: 15, y: 15 }  // 本地拖过、没保存
    const newSaved = [loc('a', '青云宗', 10, 10), loc('b', '黑风岭', 25, 25), loc('c', '新地点', null, null)]
    const next = rebaseDrafts(oldSaved, drafts, newSaved, true)
    expect(next.map((d) => [d.id, d.x, d.y, d.unplaced])).toEqual([
      ['a', 15, 15, false], ['b', 25, 25, false], ['c', 0, 0, true],
    ])
    expect(rebaseDrafts(oldSaved, drafts, newSaved, false)[0]).toMatchObject({ x: 10, y: 10 })
  })

  it('本地调整过的地点在服务端被删了就丢掉', () => {
    const oldSaved = [loc('a', '青云宗', 10, 10)]
    const drafts = [{ ...toDrafts(oldSaved)[0], x: 30 }]
    expect(rebaseDrafts(oldSaved, drafts, [], true)).toEqual([])
  })
})

describe('matchLocations', () => {
  it('按地点名、区域、绑定的原文地点搜（精确子串，不拆词）', () => {
    const list = [
      loc('a', '青云宗', 1, 1, { region: '东荒', source_names: ['青云宗·藏经阁'] }),
      loc('b', '黑风岭', 2, 2),
    ]
    expect(matchLocations(list, '藏经阁').map((l) => l.id)).toEqual(['a'])
    expect(matchLocations(list, '东荒').map((l) => l.id)).toEqual(['a'])
    expect(matchLocations(list, '').map((l) => l.id)).toEqual(['a', 'b'])
    expect(matchLocations(list, '不存在')).toEqual([])
  })
})

describe('clampPercent', () => {
  it('落在底图外的坐标返回 null（不贴边造点）', () => {
    expect(clampPercent(50, 50)).toEqual([50, 50])
    expect(clampPercent(-1, 50)).toBeNull()
    expect(clampPercent(50, 101)).toBeNull()
    expect(clampPercent(33.333, 66.666)).toEqual([33.33, 66.67])
  })
})
