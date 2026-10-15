/** 稿纸键位（参考岚笺）：回车按版式续下一段（段间空行 + 首行缩进），Shift+回车普通换行，Tab 插入两个全角空格；跟随输入。 */
import { EditorState, type EditorState as State, type Extension, type Transaction, type TransactionSpec } from '@codemirror/state'
import { EditorView, keymap } from '@codemirror/view'
import { paragraphBreak, type ParagraphFormat } from '@/utils/manuscript'

export interface ManuscriptKeysConfig {
  /** 每次按键时读取当前版式 */
  format: () => ParagraphFormat
  /** 每次输入时读取「跟随输入」开关 */
  typewriter: () => boolean
}

export function insertSpec(state: State, text: string): TransactionSpec {
  return { ...state.replaceSelection(text), userEvent: 'input.type', scrollIntoView: true }
}

/** 跟随输入：作者输入或删除时把当前行拉到视野中央（载入新正文等非输入改动不动） */
export function shouldCenter(tr: Transaction, enabled: boolean): boolean {
  return enabled && tr.docChanged && (tr.isUserEvent('input') || tr.isUserEvent('delete'))
}

function insert(view: EditorView, text: string): boolean {
  if (view.composing || view.state.readOnly) return false
  view.dispatch(insertSpec(view.state, text))
  return true
}

export function manuscriptKeys(config: ManuscriptKeysConfig): Extension {
  return [
    keymap.of([
      { key: 'Enter', run: (view) => insert(view, paragraphBreak(config.format())) },
      { key: 'Shift-Enter', run: (view) => insert(view, '\n') },
      { key: 'Tab', run: (view) => insert(view, '\u3000\u3000') },
    ]),
    EditorState.transactionExtender.of((tr) => shouldCenter(tr, config.typewriter())
      ? { effects: EditorView.scrollIntoView(tr.newSelection.main.head, { y: 'center' }) }
      : null),
  ]
}
