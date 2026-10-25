/**
 * 切章检查 / 章节目录：上传后先看切得对不对（超长章多半是几章并成了一章、很短的多是作者的话、前言番外），
 * 免得花了调用才发现切错；抽取后同一张表看每章拆书卡的状态。数据走 GET /book-dissect/{id}/chapters，展开时才拉。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, ListTree, Loader2, Play } from 'lucide-react'

import { bookDissectApi } from '@/services/api'
import type { BookDissectChapterItem } from '@/types'
import { GIANT_CHAPTER_WORDS, RESPLIT_CHAPTER_WORDS, TINY_CHAPTER_WORDS, splitReport } from './taskState'

const PAGE_SIZE = 200

type DirFilter = 'all' | 'odd' | 'failed' | 'pending'

interface ChapterCheckPanelProps {
  taskId: string
  /** 变了就重新拉（抽取中每完成一批） */
  refreshKey?: string
  defaultOpen?: boolean
  /** 刚上传、还没抽：底部给「设置抽取范围」 */
  onStart?: () => void
}

function chapterList(items: BookDissectChapterItem[], limit = 6): string {
  const nums = items.slice(0, limit).map((c) => c.number)
  return `第 ${nums.join('、')} 章${items.length > limit ? ` 等 ${items.length} 章` : ''}`
}

export function ChapterCheckPanel({ taskId, refreshKey, defaultOpen = false, onStart }: ChapterCheckPanelProps) {
  const [open, setOpen] = useState(defaultOpen)
  const [items, setItems] = useState<BookDissectChapterItem[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<DirFilter>('all')
  const [limit, setLimit] = useState(PAGE_SIZE)

  // 开始抽取后（不再是切章检查）收起来，把位置让给进度和拆书卡
  const checkMode = Boolean(onStart)
  const wasCheckMode = useRef(checkMode)
  useEffect(() => {
    if (wasCheckMode.current && !checkMode) setOpen(false)
    wasCheckMode.current = checkMode
  }, [checkMode])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    bookDissectApi
      .listChapters(taskId)
      .then((data) => {
        if (!cancelled) setItems(data ?? [])
      })
      .catch(() => {
        if (!cancelled) setItems((prev) => prev ?? [])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, taskId, refreshKey])

  const report = useMemo(() => splitReport(items ?? []), [items])
  const odd = useMemo(
    () => new Set([...report.giant, ...report.tiny, ...report.special].map((c) => c.number)),
    [report],
  )
  const failed = (items ?? []).filter((c) => c.status === 'failed').length
  const pending = (items ?? []).filter((c) => c.status == null).length
  const extracted = (items ?? []).some((c) => c.status != null)
  const visible = useMemo(() => {
    const list = items ?? []
    if (filter === 'odd') return list.filter((c) => odd.has(c.number))
    if (filter === 'failed') return list.filter((c) => c.status === 'failed')
    if (filter === 'pending') return list.filter((c) => c.status == null)
    return list
  }, [items, filter, odd])

  const chips: Array<[DirFilter, string, number]> = [
    ['all', '全部', items?.length ?? 0],
    ['odd', '需要看一眼', odd.size],
    ...(extracted ? ([['failed', '失败', failed], ['pending', '还没抽', pending]] as Array<[DirFilter, string, number]>) : []),
  ]

  return (
    <div className="hh-panel">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm"
        aria-expanded={open}
      >
        {open ? <ChevronDown className="h-4 w-4 text-content-tertiary" /> : <ChevronRight className="h-4 w-4 text-content-tertiary" />}
        <ListTree className="h-4 w-4 text-brand" />
        <span className="font-medium text-content">{onStart ? '切章检查' : '章节目录'}</span>
        {items && (
          <span className="text-xs text-content-tertiary">
            共 {report.count} 章 · 每章中位 {report.median.toLocaleString('zh-CN')} 字
            {odd.size > 0 && <span className="ml-1 text-amber-700">· {odd.size} 章需要看一眼</span>}
          </span>
        )}
        {loading && <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-content-tertiary" />}
      </button>

      {open && (
        <div className="space-y-3 border-t border-surface-border-light px-4 py-3">
          {report.willResplit && (
            <Hint tone="warning">
              {report.resplitTriggers.length > 0 ? `${chapterList(report.resplitTriggers)}超过 ${RESPLIT_CHAPTER_WORDS / 10000} 万字` : '整本只切出了一章'}
              ，开始抽取时会请 AI 重新判断整本书的切法，切出来的章可能和这里不一样。多半是原文这几处的章节标题格式没被识别，改好再上传更稳。
            </Hint>
          )}
          {!report.willResplit && report.giant.length > 0 && (
            <Hint tone="warning">
              {chapterList(report.giant)}超过 {GIANT_CHAPTER_WORDS / 10000} 万字，可能是几章并成了一章（标题格式没识别出来）。不影响抽取，但这几章只会送章首和章末给模型。
            </Hint>
          )}
          {report.tiny.length > 0 && (
            <Hint tone="info">{chapterList(report.tiny)}不到 {TINY_CHAPTER_WORDS} 字，多是作者的话 / 请假条；抽出来的卡会很空，可以忽略。</Hint>
          )}
          {report.special.length > 0 && <Hint tone="info">前言 / 番外 / 非正文 {report.special.length} 章：{chapterList(report.special)}。</Hint>}

          {items && items.length > 0 && (
            <>
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                {chips
                  .filter(([key, , n]) => key === 'all' || n > 0)
                  .map(([key, label, n]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => {
                        setFilter(key)
                        setLimit(PAGE_SIZE)
                      }}
                      className={`hh-chip !py-0.5 ${filter === key ? 'hh-chip--active' : ''}`}
                    >
                      {label} <span className="opacity-70">{n}</span>
                    </button>
                  ))}
              </div>
              <div className="max-h-[360px] overflow-auto rounded border border-surface-border-light">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-surface text-left text-content-tertiary">
                    <tr>
                      <th className="w-14 px-2 py-1.5 font-medium">章</th>
                      <th className="px-2 py-1.5 font-medium">标题</th>
                      <th className="w-24 px-2 py-1.5 text-right font-medium">字数</th>
                      {extracted && <th className="w-28 px-2 py-1.5 font-medium">拆书卡</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {visible.slice(0, limit).map((c) => (
                      <tr key={c.number} className="border-t border-surface-border-light">
                        <td className="px-2 py-1 tabular-nums text-content-secondary">{c.number}</td>
                        <td className="max-w-[320px] truncate px-2 py-1 text-content" title={c.raw_title || c.title}>
                          {c.title || c.raw_title || '—'}
                          {c.kind !== 'chapter' && <span className="ml-1.5 text-[11px] text-content-tertiary">非正文</span>}
                        </td>
                        <td
                          className={`px-2 py-1 text-right tabular-nums ${
                            c.word_count >= GIANT_CHAPTER_WORDS ? 'font-medium text-amber-700' : c.word_count < TINY_CHAPTER_WORDS ? 'text-content-tertiary' : 'text-content-secondary'
                          }`}
                        >
                          {c.word_count.toLocaleString('zh-CN')}
                        </td>
                        {extracted && (
                          <td className="px-2 py-1">
                            <CardStatus item={c} />
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {visible.length > limit && (
                <button type="button" onClick={() => setLimit((n) => n + PAGE_SIZE)} className="text-xs text-brand hover:underline">
                  再显示 {Math.min(PAGE_SIZE, visible.length - limit)} 章（共 {visible.length} 章）
                </button>
              )}
            </>
          )}

          {onStart && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-surface-border-light pt-3">
              <p className="text-xs text-content-tertiary">切得没问题就设置抽取范围；不必拆完整本，借鉴开篇节奏抽前 30-50 章就够。</p>
              <button type="button" onClick={onStart} className="hh-btn-primary hh-btn-sm">
                <Play className="h-3.5 w-3.5" />
                设置抽取范围
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CardStatus({ item }: { item: BookDissectChapterItem }) {
  if (item.status === 'success') {
    return (
      <span className="inline-flex items-center gap-1 text-emerald-700">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        已抽
      </span>
    )
  }
  if (item.status === 'failed') {
    return (
      <span className="inline-flex items-center gap-1 text-rose-700" title={item.error ?? undefined}>
        <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
        失败
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-content-tertiary">
      <span className="h-1.5 w-1.5 rounded-full bg-surface-border" />
      还没抽
    </span>
  )
}

function Hint({ tone, children }: { tone: 'warning' | 'info'; children: React.ReactNode }) {
  const cls = tone === 'warning' ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-surface-border-light bg-surface-paper text-content-secondary'
  return (
    <div className={`flex items-start gap-2 rounded border px-3 py-2 text-xs leading-5 ${cls}`}>
      {tone === 'warning' && <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
      <p className="min-w-0">{children}</p>
    </div>
  )
}
