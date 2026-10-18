import { describe, expect, it } from 'vitest'
import { EditorSelection, EditorState } from '@codemirror/state'
import { acceptSpec, setSuggestion, shouldAutoComplete, suggestionField } from './inlineSuggestion'

const DOC = '林尘推开门，'

function withSuggestion(doc = DOC, text = '屋里很暗，他摸出火折子。', pos = doc.length) {
  const state = EditorState.create({ doc, selection: { anchor: pos }, extensions: [suggestionField] })
  return state.update({ effects: setSuggestion.of({ pos, text }) }).state
}

const suggestion = (state: EditorState) => state.field(suggestionField)

describe('suggestionField', () => {
  it('设置与清除建议', () => {
    const state = withSuggestion()
    expect(suggestion(state)).toEqual({ pos: DOC.length, text: '屋里很暗，他摸出火折子。' })
    expect(suggestion(state.update({ effects: setSuggestion.of(null) }).state)).toBeNull()
    expect(suggestion(state.update({ effects: setSuggestion.of({ pos: 0, text: '' }) }).state)).toBeNull()
  })

  it('顺着建议打字：只吃掉打出的那几个字', () => {
    const state = withSuggestion()
    const next = state.update({ changes: { from: DOC.length, insert: '屋里' }, selection: { anchor: DOC.length + 2 }, userEvent: 'input.type' }).state
    expect(suggestion(next)).toEqual({ pos: DOC.length + 2, text: '很暗，他摸出火折子。' })
  })

  it('打了别的字、在别处改动或移动光标：建议作废', () => {
    const state = withSuggestion()
    expect(suggestion(state.update({ changes: { from: DOC.length, insert: '外面' }, userEvent: 'input.type' }).state)).toBeNull()
    expect(suggestion(state.update({ changes: { from: 0, insert: '那天，' }, userEvent: 'input.type' }).state)).toBeNull()
    expect(suggestion(state.update({ selection: { anchor: 2 } }).state)).toBeNull()
    expect(suggestion(state.update({ selection: EditorSelection.range(0, DOC.length) }).state)).toBeNull()
  })

  it('打完整条建议后不再显示', () => {
    const state = withSuggestion(DOC, '屋里')
    expect(suggestion(state.update({ changes: { from: DOC.length, insert: '屋里' }, userEvent: 'input.type' }).state)).toBeNull()
  })
})

describe('acceptSpec', () => {
  it('Tab：整条采用，光标放到末尾', () => {
    const state = withSuggestion()
    const next = state.update(acceptSpec(state, 'all')!).state
    expect(next.doc.toString()).toBe(DOC + '屋里很暗，他摸出火折子。')
    expect(next.selection.main.head).toBe(next.doc.length)
    expect(suggestion(next)).toBeNull()
  })

  it('Ctrl+→：只采用下一小句，剩下的继续显示', () => {
    const state = withSuggestion()
    const next = state.update(acceptSpec(state, 'chunk')!).state
    expect(next.doc.toString()).toBe(DOC + '屋里很暗，')
    expect(suggestion(next)).toEqual({ pos: next.doc.length, text: '他摸出火折子。' })
  })

  it('没有建议或光标不在建议处：不处理（Tab 交给下一个键位）', () => {
    const plain = EditorState.create({ doc: DOC, extensions: [suggestionField] })
    expect(acceptSpec(plain, 'all')).toBeNull()
  })
})

describe('shouldAutoComplete（停笔后自动要建议的条件）', () => {
  const at = (doc: string, anchor: number, head = anchor) =>
    EditorState.create({ doc, selection: EditorSelection.single(anchor, head), extensions: [suggestionField] })

  it('光标在段尾、前面有字、没有选区、没有正在显示的建议', () => {
    expect(shouldAutoComplete(at('他推开门\n下一段', 4))).toBe(true)
    expect(shouldAutoComplete(at('他推开门\n下一段', 2))).toBe(false) // 段中在改字
    expect(shouldAutoComplete(at('他推开门', 0, 4))).toBe(false) // 有选区
    expect(shouldAutoComplete(at('', 0))).toBe(false) // 空文档要按 Alt+\ 手动要
    expect(shouldAutoComplete(withSuggestion())).toBe(false)
  })
})
