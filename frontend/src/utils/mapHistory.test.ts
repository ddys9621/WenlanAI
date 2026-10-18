import { describe, expect, it } from 'vitest'
import { MAX_HISTORY, createHistory, markSaved, pushSnapshot, undo, type MarkerDraft } from './mapHistory'

const m = (name: string, x: number, y: number): MarkerDraft => ({ id: name, name, x, y })

describe('mapHistory', () => {
  it('每次改动记一步，撤销回到上一步', () => {
    let h = createHistory()
    h = pushSnapshot(h, [m('甲', 10, 10)])
    h = pushSnapshot(h, [m('甲', 20, 20)])
    const { history, snapshot } = undo(h)
    expect(snapshot).toEqual([m('甲', 20, 20)])
    expect(history.past).toHaveLength(1)
  })

  it('最多保留 50 步，超出丢最早的', () => {
    let h = createHistory()
    for (let i = 0; i < MAX_HISTORY + 5; i += 1) h = pushSnapshot(h, [m('甲', i, i)])
    expect(h.past).toHaveLength(MAX_HISTORY)
    expect(h.past[0]).toEqual([m('甲', 5, 5)])
  })

  it('保存只清掉提交前的步骤，提交后的修改仍可撤销', () => {
    let h = createHistory()
    h = pushSnapshot(h, [m('甲', 1, 1)])
    h = pushSnapshot(h, [m('甲', 2, 2)])
    const submitted = h.past.length
    h = pushSnapshot(h, [m('甲', 3, 3)])  // 保存请求在路上时又拖了一下
    h = markSaved(h, submitted)
    expect(h.past).toEqual([[m('甲', 3, 3)]])
  })

  it('空历史撤销返回 null', () => {
    expect(undo(createHistory()).snapshot).toBeNull()
  })
})
