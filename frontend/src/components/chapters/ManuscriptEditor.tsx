/**
 * 稿纸正文编辑器（CodeMirror 6，参考岚笺 PlainTextEditor）：纯文本、自动换行、撤销历史、回车续段 / Tab 缩进、
 * 行内补全（灰字建议）、跟随输入。字体 / 字号 / 行距 / 横线 / 纸色由外层 .lj-paper 的 CSS 变量控制。
 * 换章（docKey 变化）整体换 EditorState：不把上一章的撤销历史带过来。
 */
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { EditorState, Prec, Transaction, type Extension } from '@codemirror/state'
import { EditorView, keymap, placeholder as placeholderText } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, redo, redoDepth, undo, undoDepth } from '@codemirror/commands'
import { inlineCompletion, type CompletionFetcher, type CompletionStatus } from '@/editor/inlineSuggestion'
import { manuscriptKeys } from '@/editor/manuscriptKeys'
import type { ParagraphFormat } from '@/utils/manuscript'
import type { TextSelection } from '@/utils/selectionOffsets'

export interface ManuscriptEditorHandle {
  focus(): void
  getContent(): string
  /** 外部换了正文（采用候选稿 / 恢复旧版 / 载入最新）：整篇替换，不进撤销历史 */
  setContent(text: string): void
  /** 一键排版等整篇改写：可撤销 */
  replaceAll(text: string): void
  /** 接在末尾（可撤销） */
  appendText(text: string): void
  /** 全部替换：一次可撤销的批量替换 */
  replaceMatches(starts: number[], length: number, insert: string): void
  select(from: number, to: number): void
  undo(): void
  redo(): void
}

interface ManuscriptEditorProps {
  docKey: string
  initialContent: string
  placeholder: string
  format: ParagraphFormat
  typewriter: boolean
  completionEnabled: boolean
  fetchCompletion: CompletionFetcher
  onChange: (content: string) => void
  onSelection?: (selection: TextSelection) => void
  onHistory?: (canUndo: boolean, canRedo: boolean) => void
  onCompletionStatus?: (status: CompletionStatus) => void
  onSave?: () => void
}

const paperTheme = EditorView.theme({
  '&': { height: '100%', backgroundColor: 'transparent', color: 'var(--manuscript-ink)', fontSize: 'var(--manuscript-font-size)' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { overflow: 'auto', fontFamily: 'var(--manuscript-font)', lineHeight: 'var(--manuscript-line-height)', scrollbarWidth: 'thin' },
  '.cm-content': { padding: 'var(--manuscript-pad-top) 0 38vh', minHeight: '100%', caretColor: 'var(--manuscript-caret)', letterSpacing: '0.02em' },
  '.cm-line': { padding: '0 var(--manuscript-pad-x)' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--manuscript-caret)', borderLeftWidth: '2px' },
  '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground': { background: 'var(--manuscript-selection) !important' },
  '.cm-placeholder': { color: 'var(--manuscript-ghost)' },
})

export const ManuscriptEditor = forwardRef<ManuscriptEditorHandle, ManuscriptEditorProps>(function ManuscriptEditor(props, ref) {
  const hostRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const propsRef = useRef(props)
  propsRef.current = props

  const createState = (doc: string): EditorState => {
    const extensions: Extension[] = [
      history(),
      EditorView.lineWrapping,
      placeholderText(propsRef.current.placeholder),
      EditorView.contentAttributes.of({ 'aria-label': '章节正文', spellcheck: 'false' }),
      EditorView.cursorScrollMargin.of({ x: 8, y: 96 }),
      inlineCompletion({
        fetch: (request, signal, onText) => propsRef.current.fetchCompletion(request, signal, onText),
        isEnabled: () => propsRef.current.completionEnabled,
        onStatus: (status) => propsRef.current.onCompletionStatus?.(status),
      }),
      Prec.high(manuscriptKeys({ format: () => propsRef.current.format, typewriter: () => propsRef.current.typewriter })),
      keymap.of([{ key: 'Mod-s', run: () => { propsRef.current.onSave?.(); return true } }, ...defaultKeymap, ...historyKeymap]),
      EditorView.updateListener.of((update) => {
        const p = propsRef.current
        if (update.docChanged) p.onChange(update.state.doc.toString())
        if (update.docChanged || update.selectionSet) {
          const range = update.state.selection.main
          p.onSelection?.({ start: range.from, end: range.to, text: update.state.sliceDoc(range.from, range.to) })
        }
        if (update.transactions.length) p.onHistory?.(undoDepth(update.state) > 0, redoDepth(update.state) > 0)
      }),
      paperTheme,
    ]
    return EditorState.create({ doc, extensions })
  }

  useEffect(() => {
    const view = new EditorView({ state: createState(propsRef.current.initialContent), parent: hostRef.current! })
    viewRef.current = view
    return () => {
      view.destroy()
      viewRef.current = null
    }
    // 只在挂载时建一次；换章由下面的 docKey effect 处理
  }, [])

  const firstKey = useRef(true)
  useEffect(() => {
    if (firstKey.current) {
      firstKey.current = false
      return
    }
    const view = viewRef.current
    if (!view) return
    view.setState(createState(propsRef.current.initialContent))
    view.scrollDOM.scrollTop = 0
    propsRef.current.onHistory?.(false, false)
    // 只跟章节走：同一章里的正文变化由编辑器自己维护
  }, [props.docKey])

  useImperativeHandle(ref, () => ({
    focus: () => viewRef.current?.focus(),
    getContent: () => viewRef.current?.state.doc.toString() ?? '',
    setContent: (text) => {
      const view = viewRef.current
      if (!view || view.state.doc.toString() === text) return
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text }, annotations: Transaction.addToHistory.of(false) })
    },
    replaceAll: (text) => {
      const view = viewRef.current
      if (!view || view.state.doc.toString() === text) return
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text }, userEvent: 'input.format', scrollIntoView: true })
      view.focus()
    },
    appendText: (text) => {
      const view = viewRef.current
      if (!view || !text) return
      const doc = view.state.doc.toString()
      const sep = doc.trim() ? (doc.endsWith('\n') ? '\n' : '\n\n') : ''
      const end = view.state.doc.length
      view.dispatch({
        changes: { from: end, insert: sep + text },
        selection: { anchor: end + sep.length + text.length },
        userEvent: 'input.paste',
        scrollIntoView: true,
      })
      view.focus()
    },
    replaceMatches: (starts, length, insert) => {
      const view = viewRef.current
      if (!view || !starts.length) return
      view.dispatch({ changes: starts.map((from) => ({ from, to: from + length, insert })), userEvent: 'input.replace.all' })
    },
    select: (from, to) => {
      const view = viewRef.current
      if (!view) return
      view.dispatch({ selection: { anchor: from, head: to }, effects: EditorView.scrollIntoView(from, { y: 'center' }) })
    },
    undo: () => { const view = viewRef.current; if (view && !view.composing) { undo(view); view.focus() } },
    redo: () => { const view = viewRef.current; if (view && !view.composing) { redo(view); view.focus() } },
  }), [])

  return <div ref={hostRef} className="h-full min-h-0" />
})
