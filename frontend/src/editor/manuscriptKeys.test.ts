import { describe, expect, it } from 'vitest'
import { EditorSelection, EditorState } from '@codemirror/state'
import { insertSpec, shouldCenter } from './manuscriptKeys'
import { paragraphBreak } from '@/utils/manuscript'

describe('insertSpec（回车续段 / Tab 缩进）', () => {
  it('回车按版式插入段间空行与首行缩进，光标到新段开头', () => {
    const doc = '\u3000\u3000第一段。'
    const state = EditorState.create({ doc, selection: { anchor: doc.length } })
    const next = state.update(insertSpec(state, paragraphBreak({ firstLineIndent: true, paragraphSpacing: true }))).state
    expect(next.doc.toString()).toBe('\u3000\u3000第一段。\n\n\u3000\u3000')
    expect(next.selection.main.head).toBe(next.doc.length)
  })

  it('有选区时替换选中的文字', () => {
    const state = EditorState.create({ doc: '甲乙丙', selection: EditorSelection.single(1, 2) })
    expect(state.update(insertSpec(state, '\u3000\u3000')).state.doc.toString()).toBe('甲\u3000\u3000丙')
  })
})

describe('shouldCenter（跟随输入）', () => {
  const state = EditorState.create({ doc: '正文' })

  it('打开后，作者输入或删除时把当前行拉到中间', () => {
    expect(shouldCenter(state.update({ changes: { from: 2, insert: '字' }, userEvent: 'input.type' }), true)).toBe(true)
    expect(shouldCenter(state.update({ changes: { from: 0, to: 1 }, userEvent: 'delete.backward' }), true)).toBe(true)
  })

  it('关闭时、或不是作者输入（载入新正文）时不动', () => {
    expect(shouldCenter(state.update({ changes: { from: 2, insert: '字' }, userEvent: 'input.type' }), false)).toBe(false)
    expect(shouldCenter(state.update({ changes: { from: 0, insert: '载入' } }), true)).toBe(false)
  })
})
