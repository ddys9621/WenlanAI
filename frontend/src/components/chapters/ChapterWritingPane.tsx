/**
 * 章节写作 ·「正文」稿纸（参考岚笺正文编辑器）：
 * 稿纸顶上一行章节标题栏（不再单独占一行工具栏）：第 N 章 + 可直接改的标题，
 * 右边一排图标工具（撤销 / 重做 / 查找替换 ｜ 版式 ｜ AI 补全 ｜ 专注模式 ｜ 更多：一键排版 · 跟随输入 · 标注 · 补全长度），
 * 再右边是正文 / 候选稿 / 历史版本（headerRight）；工具平时淡一些，鼠标移上去才清楚。下面横线正文、底部状态栏
 * （保存状态 · 本章 / 选区 / 全书字数 · 段数 · 历史版本 · 立即保存）。
 * 停笔 1.5 秒自动保存（带正文指纹；别处改过就暂停并让作者选）；AI 补全打开后停笔约 1 秒在光标后给出灰色建议，Tab 采用。
 */
import {
  forwardRef, useCallback, useDeferredValue, useEffect, useImperativeHandle, useMemo, useRef, useState,
  type CSSProperties, type KeyboardEvent, type ReactNode,
} from 'react'
import {
  AlertTriangle, AlignLeft, Check, Copy, Crosshair, Highlighter, History, LayoutTemplate, Loader2, Maximize2, Minimize2,
  MoreHorizontal, Redo2, Save, Search, Sparkles, Undo2,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { chapterApi } from '@/services/api'
import { useChapterAutosave } from '@/hooks/useChapterAutosave'
import type { CompletionFetcher, CompletionStatus } from '@/editor/inlineSuggestion'
import { DEFAULT_EDITOR_PREFS, EDITOR_FONT_CSS, loadEditorPrefs, saveEditorPrefs, type EditorPrefs } from '@/utils/editorPrefs'
import { countParagraphs, countWords, formatParagraphs } from '@/utils/manuscript'
import type { TextSelection } from '@/utils/selectionOffsets'
import type { Chapter } from '@/types'
import { ManuscriptEditor, type ManuscriptEditorHandle } from './ManuscriptEditor'
import { ManuscriptFindBar } from './ManuscriptFindBar'
import { ManuscriptLayoutPanel } from './ManuscriptLayoutPanel'
import { PromiseReminderBar } from './PromiseReminderBar'

export interface ChapterWritingPaneHandle {
  flush(): Promise<void>
}

interface ChapterWritingPaneProps {
  projectId: string
  chapter: Chapter
  /** 全书已保存字数（章节列表合计） */
  bookWords: number
  /** 工具栏右侧（正文 / 候选稿 / 历史版本、分析面板开关）；专注模式下隐藏 */
  headerRight?: ReactNode
  /** 有记忆标注时可切换的只读标注视图 */
  readView?: ReactNode
  onSaved: (saved: Chapter) => void
  onTitleSaved: (saved: Chapter) => void
  onSelection: (selection: TextSelection | null) => void
  onOpenHistory: () => void
  onAskAssistant: () => void
}

const COMPLETION_TIP = '停笔约 1 秒，光标后出现灰色建议：Tab 采用，Ctrl+→ 采用一小句，Esc 收起，继续打字则忽略；Alt+\\ 随时要一条'
const EMPTY_SELECTION: TextSelection = { start: 0, end: 0, text: '' }

function clock(date: Date) {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

/** 标题栏里的图标工具：只有图标，说明在 title 里；keepFocus = 点了不抢走正文的光标（撤销 / 重做）；
 * holdOutside = 弹层开着时按下这个按钮不算「点在弹层外」（否则弹层先关、再被这次点击打开，关不掉） */
function ToolButton({ label, onClick, active, disabled, keepFocus, holdOutside, children }: {
  label: string; onClick: () => void; active?: boolean; disabled?: boolean; keepFocus?: boolean; holdOutside?: boolean
  children: ReactNode
}) {
  return (
    <button
      onMouseDown={(e) => {
        if (keepFocus) e.preventDefault()
        if (holdOutside) e.nativeEvent.stopImmediatePropagation()
      }}
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      aria-label={label}
      title={label}
      className={cn('lj-tool h-7 w-7 justify-center px-0', active && 'lj-tool--active')}
    >
      {children}
    </button>
  )
}

export const ChapterWritingPane = forwardRef<ChapterWritingPaneHandle, ChapterWritingPaneProps>(function ChapterWritingPane(props, ref) {
  const { chapter } = props
  const editorRef = useRef<ManuscriptEditorHandle>(null)
  const callbacks = useRef(props)
  callbacks.current = props

  const [prefs, setPrefs] = useState<EditorPrefs>(() => loadEditorPrefs())
  const prefsRef = useRef(prefs)
  prefsRef.current = prefs
  const [content, setContent] = useState(chapter.content ?? '')
  const [selection, setSelection] = useState<TextSelection>(EMPTY_SELECTION)
  const [history, setHistory] = useState({ canUndo: false, canRedo: false })
  const [completion, setCompletion] = useState<CompletionStatus>({ state: 'idle' })
  const [focusMode, setFocusMode] = useState(false)
  const [findOpen, setFindOpen] = useState(false)
  const [layoutOpen, setLayoutOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [readMode, setReadMode] = useState(false)
  const [titleDraft, setTitleDraft] = useState(chapter.title)
  const [sessionStart, setSessionStart] = useState(() => countWords(chapter.content ?? ''))

  const autosave = useChapterAutosave(chapter, (saved) => callbacks.current.onSaved(saved))
  const { update: autosaveUpdate, flush, reset: autosaveReset } = autosave

  // 换章：本地状态回到新章
  useEffect(() => {
    setContent(chapter.content ?? '')
    setSelection(EMPTY_SELECTION)
    setReadMode(false)
    setFindOpen(false)
    setCompletion({ state: 'idle' })
    setSessionStart(countWords(chapter.content ?? ''))
    // 只跟章节走
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter.id])

  useEffect(() => { setTitleDraft(chapter.title) }, [chapter.id, chapter.title])

  // 外部换了正文（采用候选稿 / 恢复旧版 / 助笔回填后重新载入）：没有未保存的修改就跟上；
  // 有的话留着，下一次保存会因指纹不符停下来让作者选
  useEffect(() => {
    const ctl = autosave.controller()
    if (!ctl || chapter.content_hash == null || chapter.content_hash === ctl.baseHash || ctl.dirty) return
    const text = chapter.content ?? ''
    autosaveReset(text, chapter.content_hash)
    editorRef.current?.setContent(text)
    setContent(text)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter.content_hash])

  // 选中的正文交给智能助笔（与已保存的正文逐字一致：有未保存的修改先存）
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!selection.text) {
        callbacks.current.onSelection(null)
        return
      }
      const report = () => callbacks.current.onSelection(selection)
      if (autosave.controller()?.dirty) void flush().then(report)
      else report()
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection])

  useEffect(() => { editorRef.current?.focus() }, [focusMode])

  useImperativeHandle(ref, () => ({ flush }), [flush])

  const updatePrefs = useCallback((patch: Partial<EditorPrefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch }
      saveEditorPrefs(next)
      return next
    })
  }, [])

  const onChange = useCallback((text: string) => {
    setContent(text)
    autosaveUpdate(text)
  }, [autosaveUpdate])

  const fetchCompletion = useCallback<CompletionFetcher>((request, signal, onText) =>
    chapterApi.inlineCompletionStream(chapter.id, { ...request, length: prefsRef.current.completionLength }, {
      signal,
      onEvent: (message) => {
        if (message.type === 'suggestion' && typeof message.text === 'string') onText(message.text)
      },
    }).then((result) => result?.text ?? ''), [chapter.id])

  const toggleCompletion = () => {
    const on = !prefs.completion
    updatePrefs({ completion: on })
    if (on) toast.info(`AI 补全已打开。${COMPLETION_TIP}`)
    editorRef.current?.focus()
  }

  const formatAll = () => {
    const text = editorRef.current?.getContent() ?? ''
    if (!text.trim()) return
    editorRef.current?.replaceAll(formatParagraphs(text, { firstLineIndent: prefs.firstLineIndent, paragraphSpacing: prefs.paragraphSpacing }))
    toast.success('已按当前版式排好段落（Ctrl+Z 可撤销）')
  }

  const toggleReadMode = async () => {
    if (!readMode) await flush()
    setReadMode((v) => !v)
  }

  const saveTitle = async () => {
    const title = titleDraft.trim()
    if (!title || title === chapter.title) {
      setTitleDraft(chapter.title)
      return
    }
    try {
      callbacks.current.onTitleSaved(await chapterApi.updateChapter(chapter.id, { title }))
    } catch {
      setTitleDraft(chapter.title)
    }
  }

  const loadLatest = async () => {
    if (!confirm('载入最新版本会丢掉编辑器里还没保存的修改，确定吗？')) return
    const latest = await chapterApi.getChapter(chapter.id)
    const text = latest.content ?? ''
    autosaveReset(text, latest.content_hash ?? null)
    editorRef.current?.setContent(text)
    setContent(text)
    callbacks.current.onSaved(latest)
  }

  const copy = async (text: string, what: string) => {
    setMoreOpen(false)
    try {
      await navigator.clipboard.writeText(text)
      toast.success(`${what}已复制到剪贴板`)
    } catch {
      toast.error('复制失败，请稍后重试')
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const mod = event.ctrlKey || event.metaKey
    if (mod && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'f') {
      event.preventDefault()
      setFindOpen(true)
    } else if (mod && event.key.toLowerCase() === 's' && !event.defaultPrevented) {
      event.preventDefault()
      void flush()
    } else if (event.key === 'Escape' && focusMode && !event.defaultPrevented) {
      setFocusMode(false)
    }
  }

  const deferred = useDeferredValue(content)
  const words = useMemo(() => countWords(deferred), [deferred])
  const paragraphs = useMemo(() => countParagraphs(deferred), [deferred])
  const selectedWords = useMemo(() => countWords(selection.text), [selection.text])
  const bookWords = Math.max(0, props.bookWords - (chapter.word_count ?? 0) + words)
  const delta = words - sessionStart

  const { status, error, savedAt } = autosave.state
  const saveLabel = status === 'saving' ? '正在保存…'
    : status === 'dirty' ? '未保存'
      : status === 'error' ? `保存失败：${error ?? ''}，稍后自动重试`
        : status === 'conflict' ? '别处改过，自动保存已暂停'
          : savedAt ? `已保存 · ${clock(savedAt)}` : '正文已是最新'

  const paperStyle = {
    '--manuscript-font': EDITOR_FONT_CSS[prefs.fontFamily],
    '--manuscript-font-size': `${prefs.fontSize}px`,
    '--manuscript-line-height': `${Math.round(prefs.fontSize * prefs.leading * 100) / 100}px`,
    maxWidth: prefs.pageWidth,
  } as CSSProperties

  const dot = <i className="h-[3px] w-[3px] shrink-0 rounded-full bg-gold" />

  return (
    <section
      onKeyDown={onKeyDown}
      className={cn('flex min-h-0 min-w-0 flex-col bg-surface', focusMode ? 'fixed inset-0 z-40' : 'h-full flex-1')}
    >
      {findOpen && (
        <ManuscriptFindBar
          content={content}
          onSelect={(from, to) => editorRef.current?.select(from, to)}
          onReplace={(starts, length, text) => editorRef.current?.replaceMatches(starts, length, text)}
          onClose={() => { setFindOpen(false); editorRef.current?.focus() }}
        />
      )}

      {/* 稿纸：顶上一行章节标题栏（标题 + 工具 + 正文 / 候选稿 / 历史版本），下面横线正文 */}
      <div className={cn('min-h-0 flex-1 overflow-hidden', focusMode ? 'px-4 py-5' : 'p-3')}>
        <div className="lj-paper mx-auto flex h-full w-full flex-col" data-paper={prefs.paper} data-guide={prefs.guideStyle} style={paperStyle}>
          <div className="lj-chapter-head relative flex shrink-0 items-center gap-2 border-b border-[rgba(185,174,155,0.5)] px-[var(--manuscript-pad-x)] py-1.5">
            <label className="flex min-w-0 flex-1 items-baseline gap-2.5 font-serif">
              <span className="shrink-0 text-[13px] text-[color:var(--manuscript-ghost)]">第 {chapter.chapter_number} 章</span>
              <input
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={() => void saveTitle()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); editorRef.current?.focus() }
                  if (e.key === 'Escape') { setTitleDraft(chapter.title); editorRef.current?.focus() }
                }}
                placeholder="填写章节标题"
                maxLength={200}
                aria-label="章节标题"
                className="min-w-0 flex-1 !h-9 !rounded-none !border-0 !border-b !border-transparent !bg-transparent !px-0.5 text-[18px] font-semibold tracking-[0.02em] !text-[color:var(--manuscript-ink)] hover:!border-[rgba(40,91,77,0.4)] focus:!border-brand focus:!shadow-none"
              />
            </label>
            <div className="lj-chapter-tools flex flex-none items-center gap-0.5" role="toolbar" aria-label="写作工具">
              <ToolButton label="撤销（Ctrl+Z）" onClick={() => editorRef.current?.undo()} disabled={!history.canUndo} keepFocus>
                <Undo2 className="h-4 w-4" />
              </ToolButton>
              <ToolButton label="重做（Ctrl+Y 或 Ctrl+Shift+Z）" onClick={() => editorRef.current?.redo()} disabled={!history.canRedo} keepFocus>
                <Redo2 className="h-4 w-4" />
              </ToolButton>
              <ToolButton label="查找与替换（Ctrl+F）" onClick={() => setFindOpen((v) => !v)} active={findOpen}>
                <Search className="h-4 w-4" />
              </ToolButton>
              <span className="lj-tool-sep" />
              <ToolButton label="版式：字体、字号、行距、行宽、横线和纸色" onClick={() => setLayoutOpen((v) => !v)} active={layoutOpen} holdOutside={layoutOpen}>
                <LayoutTemplate className="h-4 w-4" />
              </ToolButton>
              <ToolButton label={`AI 补全${prefs.completion ? '（已打开）' : ''}：${COMPLETION_TIP}`} onClick={toggleCompletion} active={prefs.completion}>
                <span className="relative">
                  <Sparkles className="h-4 w-4" />
                  {prefs.completion && completion.state === 'loading' && <Loader2 className="absolute -right-1.5 -top-1.5 h-2.5 w-2.5 animate-spin" aria-label="正在想" />}
                  {prefs.completion && completion.state === 'error' && <AlertTriangle className="absolute -right-1.5 -top-1.5 h-2.5 w-2.5 text-cinnabar" aria-label="补全失败" />}
                </span>
              </ToolButton>
              <ToolButton label={focusMode ? '退出专注（Esc）' : '专注模式（Esc 退出）'} onClick={() => setFocusMode((v) => !v)} active={focusMode}>
                {focusMode ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </ToolButton>
              <div className="relative">
                <ToolButton label="更多：一键排版、跟随输入、标注、补全长度" onClick={() => setToolsOpen((v) => !v)} active={toolsOpen}>
                  <MoreHorizontal className="h-4 w-4" />
                </ToolButton>
                {toolsOpen && (
                  <div className="absolute right-0 top-full z-30 mt-1.5 grid w-48 gap-0.5 rounded border border-surface-border bg-white p-1 text-content shadow-lg" onMouseLeave={() => setToolsOpen(false)} role="menu">
                    <button onClick={() => { formatAll(); setToolsOpen(false) }} disabled={!content.trim()} className="lj-tool w-full justify-start" role="menuitem" title="按当前版式统一段落缩进和段间空行">
                      <AlignLeft className="h-4 w-4" />一键排版
                    </button>
                    <button onClick={() => { updatePrefs({ typewriter: !prefs.typewriter }); editorRef.current?.focus() }} className="lj-tool w-full justify-start" role="menuitemcheckbox" aria-checked={prefs.typewriter} title="让当前输入行保持在视野中央">
                      <Crosshair className="h-4 w-4" />跟随输入{prefs.typewriter && <Check className="ml-auto h-3.5 w-3.5 text-brand" />}
                    </button>
                    {props.readView && (
                      <button onClick={() => { void toggleReadMode(); setToolsOpen(false) }} className="lj-tool w-full justify-start" role="menuitemcheckbox" aria-checked={readMode} title="只读查看记忆标注（钩子 / 伏笔 / 情节点）">
                        <Highlighter className="h-4 w-4" />标注{readMode && <Check className="ml-auto h-3.5 w-3.5 text-brand" />}
                      </button>
                    )}
                    {prefs.completion && (
                      <div className="flex items-center gap-1.5 border-t border-surface-border-light px-2 pb-1 pt-1.5 text-xs text-content-secondary">
                        补全长度
                        <div className="ws-seg ml-auto" role="group" aria-label="补全长度">
                          {(['sentence', 'paragraph'] as const).map((value) => (
                            <button
                              key={value}
                              onClick={() => { updatePrefs({ completionLength: value }); editorRef.current?.focus() }}
                              aria-pressed={prefs.completionLength === value}
                              className={cn('ws-seg-item px-1.5 py-0.5 text-[11px]', prefs.completionLength === value && 'ws-seg-item--on')}
                            >
                              {value === 'sentence' ? '一句' : '一段'}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
            {!focusMode && props.headerRight && <div className="flex flex-none items-center">{props.headerRight}</div>}
            {/* 版式弹层挂在整条标题栏上、贴右边展开：按钮在右边，挂在按钮上往左展开会被稿纸左边的栏挡住 */}
            {layoutOpen && (
              <ManuscriptLayoutPanel
                align="right"
                prefs={prefs}
                onChange={updatePrefs}
                onReset={() => updatePrefs({ ...DEFAULT_EDITOR_PREFS, completion: prefs.completion, completionLength: prefs.completionLength })}
                onClose={() => setLayoutOpen(false)}
              />
            )}
          </div>
          <div className="relative min-h-0 flex-1 overflow-hidden">
            <div className={cn('h-full', readMode && 'hidden')}>
              <ManuscriptEditor
                ref={editorRef}
                docKey={chapter.id}
                initialContent={chapter.content ?? ''}
                placeholder="从这里开始写……（打开「AI 补全」后，停笔片刻会在光标后给出灰色建议；也可以点左侧 ⚡ 先让 AI 写一份候选稿）"
                format={{ firstLineIndent: prefs.firstLineIndent, paragraphSpacing: prefs.paragraphSpacing }}
                typewriter={prefs.typewriter}
                completionEnabled={prefs.completion}
                fetchCompletion={fetchCompletion}
                onChange={onChange}
                onSelection={setSelection}
                onHistory={(canUndo, canRedo) => setHistory({ canUndo, canRedo })}
                onCompletionStatus={setCompletion}
                onSave={() => void flush()}
              />
            </div>
            {readMode && <div className="h-full overflow-y-auto px-[var(--manuscript-pad-x)] py-5">{props.readView}</div>}
          </div>
        </div>
      </div>

      {/* 伏笔提醒：专注模式不显示 */}
      {!focusMode && <PromiseReminderBar projectId={props.projectId} chapterNumber={chapter.chapter_number} />}

      {status === 'conflict' && (
        <div role="alert" className="flex flex-wrap items-center gap-3 border-t border-cinnabar/30 bg-cinnabar-wash px-4 py-2.5 text-xs">
          <AlertTriangle className="h-4 w-4 shrink-0 text-cinnabar" />
          <span className="min-w-0 flex-1 text-content">
            这一章在别处被改过（采用了候选稿、恢复了旧版或在其他窗口编辑），自动保存已暂停；你的修改仍在编辑器里。
          </span>
          <button onClick={() => void autosave.overwrite()} className="hh-btn-secondary hh-btn-sm">保留我的版本（对方存入历史版本）</button>
          <button onClick={() => void loadLatest()} className="hh-btn-ghost hh-btn-sm">载入最新版本</button>
        </div>
      )}

      {/* 状态栏 */}
      <footer className="flex min-h-[34px] flex-wrap items-center gap-x-4 gap-y-1 border-t border-surface-border bg-surface-paper px-4 py-1 text-[12px] text-content-tertiary">
        <span
          className={cn(
            'flex items-center gap-1.5',
            (status === 'error' || status === 'conflict') && 'text-cinnabar',
            status === 'dirty' && 'text-amber-600',
          )}
          aria-live="polite"
        >
          {status === 'saving' ? <Loader2 className="h-3 w-3 animate-spin" />
            : status === 'saved' ? <Check className="h-3 w-3 text-brand" />
              : status === 'dirty' ? <i className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                : <AlertTriangle className="h-3 w-3" />}
          {saveLabel}
        </span>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 tabular-nums">
          <span>第 {chapter.chapter_number} 章</span>
          {dot}
          <span>本章 {words.toLocaleString()} 字</span>
          {selectedWords > 0 && (
            <>
              {dot}
              <span className="font-semibold text-signal">选区 {selectedWords.toLocaleString()} 字</span>
              <button onClick={props.onAskAssistant} className="inline-flex items-center gap-0.5 font-medium text-brand hover:underline">
                <Sparkles className="h-3 w-3" />交给智能助笔
              </button>
            </>
          )}
          {dot}
          <span className="text-brand">全书 {bookWords.toLocaleString()} 字</span>
          {dot}
          <span>{paragraphs} 段</span>
          {delta !== 0 && (
            <>
              {dot}
              <span className={delta > 0 ? 'text-brand' : ''}>本次 {delta > 0 ? '+' : ''}{delta.toLocaleString()}</span>
            </>
          )}
          {prefs.completion && completion.state === 'error' && (
            <span className="text-cinnabar" title={completion.message}>· 补全失败：{completion.message.slice(0, 40)}</span>
          )}
          {focusMode && <em className="ml-1 not-italic text-brand">按 Esc 退出专注</em>}
        </div>
        <div className="relative flex items-center gap-1.5">
          <button onClick={() => setMoreOpen((v) => !v)} aria-expanded={moreOpen} className="lj-tool h-7 w-7 justify-center px-0" title="更多">
            <MoreHorizontal className="h-4 w-4" />
          </button>
          {moreOpen && (
            <div className="absolute bottom-full right-0 z-30 mb-1.5 grid w-40 gap-0.5 rounded border border-surface-border bg-white p-1 shadow-lg" onMouseLeave={() => setMoreOpen(false)}>
              <button onClick={() => void copy(`第${chapter.chapter_number}章 ${titleDraft}`, '章节标题')} className="lj-tool w-full justify-start">
                <Copy className="h-4 w-4" />复制标题
              </button>
              <button onClick={() => void copy(editorRef.current?.getContent() ?? content, '正文')} disabled={!content.trim()} className="lj-tool w-full justify-start">
                <Copy className="h-4 w-4" />复制正文
              </button>
            </div>
          )}
          <button onClick={props.onOpenHistory} className="lj-tool h-7" title="历史版本：手改 / 采用候选稿 / 恢复前的旧稿">
            <History className="h-4 w-4" />历史版本
          </button>
          <button
            onClick={() => void flush()}
            disabled={status === 'saving' || status === 'conflict'}
            className="inline-flex h-7 items-center gap-1.5 rounded-lg border border-surface-border bg-white px-2.5 text-xs font-medium text-content hover:border-brand/50 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
            title="立即保存（Ctrl+S）"
          >
            <Save className="h-3.5 w-3.5" />
            {status === 'saving' ? '正在保存…' : status === 'error' ? '重试保存' : '立即保存'}
          </button>
        </div>
      </footer>
    </section>
  )
})
