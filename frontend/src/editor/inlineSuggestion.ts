/**
 * CodeMirror 6 行内补全（像写代码的 Copilot）：建议以灰字 widget 显示在光标后（不进文档、不破坏撤销与输入法），
 * Tab 整条采用、Ctrl+→ 采用一小句、Esc 收起、继续打字则顺着建议吃掉相同的字或让建议作废；Alt+\ 随时手动要一条。
 * 打开开关后，作者停笔 delay 毫秒且光标在段尾时自动请求；任何输入 / 移动光标都会取消正在进行的请求。
 */
import { Prec, StateEffect, StateField, type EditorState, type Extension, type TransactionSpec } from '@codemirror/state'
import { Decoration, EditorView, ViewPlugin, WidgetType, keymap, type ViewUpdate } from '@codemirror/view'
import { completionContext, consumeTyped, nextChunk, restOfLineIsBlank } from '@/utils/inlineCompletion'

export interface Suggestion {
  pos: number
  text: string
}

export interface CompletionRequest {
  prefix: string
  suffix: string
}

/** 拉取建议：onText 收到「截至目前的完整建议」（流式逐步变长），resolve 最终建议（空串 = 没有建议） */
export type CompletionFetcher = (request: CompletionRequest, signal: AbortSignal, onText: (text: string) => void) => Promise<string>

export type CompletionStatus = { state: 'idle' } | { state: 'loading' } | { state: 'error'; message: string }

export interface InlineCompletionConfig {
  fetch: CompletionFetcher
  /** 每次触发时读取（开关切换不必重建编辑器） */
  isEnabled: () => boolean
  delay?: number
  onStatus?: (status: CompletionStatus) => void
}

export const setSuggestion = StateEffect.define<Suggestion | null>()

export const suggestionField = StateField.define<Suggestion | null>({
  create: () => null,
  update(value, tr) {
    for (const effect of tr.effects) {
      if (effect.is(setSuggestion)) return effect.value && effect.value.text ? effect.value : null
    }
    if (!value) return null
    if (tr.docChanged) {
      const inserts: { from: number; to: number; text: string }[] = []
      tr.changes.iterChanges((from, to, _fromB, _toB, inserted) => inserts.push({ from, to, text: inserted.toString() }))
      const [only] = inserts
      if (inserts.length !== 1 || only.from !== value.pos || only.to !== value.pos || !only.text) return null
      const rest = consumeTyped(value.text, only.text)
      return rest ? { pos: value.pos + only.text.length, text: rest } : null
    }
    if (tr.selection) {
      const main = tr.state.selection.main
      return main.empty && main.head === value.pos ? value : null
    }
    return value
  },
  provide: (field) => EditorView.decorations.from(field, (value) => value
    ? Decoration.set([Decoration.widget({ widget: new GhostText(value.text), side: 1 }).range(value.pos)])
    : Decoration.none),
})

class GhostText extends WidgetType {
  readonly text: string

  constructor(text: string) {
    super()
    this.text = text
  }

  eq(other: GhostText) {
    return other.text === this.text
  }

  toDOM() {
    const span = document.createElement('span')
    span.className = 'cm-inline-suggestion'
    span.textContent = this.text
    span.setAttribute('aria-hidden', 'true')
    return span
  }

  ignoreEvent() {
    return false
  }
}

/** 采用建议：all = 整条，chunk = 下一小句（剩下的继续显示）；没有可采用的建议返回 null */
export function acceptSpec(state: EditorState, part: 'all' | 'chunk'): TransactionSpec | null {
  const value = state.field(suggestionField, false)
  const main = state.selection.main
  if (!value || !main.empty || main.head !== value.pos) return null
  const text = part === 'all' ? value.text : nextChunk(value.text)
  const rest = value.text.slice(text.length)
  return {
    changes: { from: value.pos, insert: text },
    selection: { anchor: value.pos + text.length },
    effects: setSuggestion.of(rest ? { pos: value.pos + text.length, text: rest } : null),
    userEvent: 'input.complete',
    scrollIntoView: true,
  }
}

/** 停笔后自动要建议：光标在段尾、前面有字、没有选区、没有正在显示的建议 */
export function shouldAutoComplete(state: EditorState): boolean {
  const main = state.selection.main
  if (!main.empty || state.field(suggestionField, false)) return false
  const line = state.doc.lineAt(main.head)
  if (!restOfLineIsBlank(line.text, main.head - line.from)) return false
  return state.sliceDoc(Math.max(0, main.head - 200), main.head).trim().length > 0
}

function accept(view: EditorView, part: 'all' | 'chunk'): boolean {
  if (view.composing || view.state.readOnly) return false
  const spec = acceptSpec(view.state, part)
  if (!spec) return false
  view.dispatch(spec)
  return true
}

function dismiss(view: EditorView): boolean {
  if (!view.state.field(suggestionField, false)) return false
  view.dispatch({ effects: setSuggestion.of(null) })
  return true
}

const ghostTheme = EditorView.baseTheme({
  '.cm-inline-suggestion': { color: 'var(--manuscript-ghost, #a3a89f)', pointerEvents: 'none' },
})

export function inlineCompletion(config: InlineCompletionConfig): Extension {
  const delay = config.delay ?? 1200

  const plugin = ViewPlugin.fromClass(class {
    timer: ReturnType<typeof setTimeout> | null = null
    abort: AbortController | null = null
    readonly view: EditorView

    constructor(view: EditorView) {
      this.view = view
    }

    update(update: ViewUpdate) {
      if (update.docChanged || update.selectionSet) this.cancel()
      const typed = update.docChanged && update.transactions.some((tr) => tr.isUserEvent('input') || tr.isUserEvent('delete'))
      if (typed && config.isEnabled()) this.timer = setTimeout(() => this.start(false), delay)
    }

    start(manual: boolean) {
      this.timer = null
      const { view } = this
      const { state } = view
      if (view.composing || state.readOnly) return
      if (!manual && (!config.isEnabled() || !view.hasFocus || !shouldAutoComplete(state))) return
      const pos = state.selection.main.head
      const abort = new AbortController()
      this.abort = abort
      config.onStatus?.({ state: 'loading' })
      const show = (text: string) => {
        const now = view.state
        if (abort.signal.aborted || now.doc !== state.doc || now.selection.main.head !== pos) return
        view.dispatch({ effects: setSuggestion.of(text ? { pos, text } : null) })
      }
      config.fetch(completionContext(state.doc.toString(), pos), abort.signal, show)
        .then((text) => {
          show(text)
          if (!abort.signal.aborted) config.onStatus?.({ state: 'idle' })
        })
        .catch((error: unknown) => {
          if (!abort.signal.aborted) config.onStatus?.({ state: 'error', message: error instanceof Error ? error.message : '补全失败' })
        })
        .finally(() => {
          if (this.abort === abort) this.abort = null
        })
    }

    cancel() {
      if (this.timer !== null) clearTimeout(this.timer)
      this.timer = null
      if (this.abort) {
        this.abort.abort()
        this.abort = null
        config.onStatus?.({ state: 'idle' })
      }
    }

    destroy() {
      this.cancel()
    }
  })

  const request = (view: EditorView): boolean => {
    const instance = view.plugin(plugin)
    if (!instance || view.composing) return false
    instance.cancel()
    if (view.state.field(suggestionField, false)) view.dispatch({ effects: setSuggestion.of(null) })
    instance.start(true)
    return true
  }

  return [
    suggestionField,
    plugin,
    ghostTheme,
    Prec.highest(keymap.of([
      { key: 'Tab', run: (view) => accept(view, 'all') },
      { key: 'Mod-ArrowRight', run: (view) => accept(view, 'chunk') },
      { key: 'Escape', run: dismiss },
      { key: 'Alt-\\', run: request },
    ])),
  ]
}
