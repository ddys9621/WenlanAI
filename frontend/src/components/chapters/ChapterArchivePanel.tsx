/**
 * 本章档案（码字侧栏）：分析状态（未分析 / 过期 / 失败）+ 摘要与章末状态（作者可改，之后重新分析不覆盖，
 * AI 新结果作为建议采用 / 忽略）+ 本章结算出的人物状态变化、出场人物、地点。
 * 摘要和章末状态是「前情脉络 / 近期剧情」的地基：写后面的章节时直接用它们。
 */
import { useState, type ReactNode } from 'react'
import { AlertTriangle, Check, Loader2, Pencil, RefreshCw, X } from 'lucide-react'
import { toast } from 'sonner'
import { chapterApi } from '@/services/api'
import { Pill } from '@/components/ui/Pill'
import { describeStateChange, type NormalizedAnalysisData } from '@/utils/chapterAnalysis'

interface Props {
  chapterId: string
  data: NormalizedAnalysisData | null
  loading: boolean
  /** 本章有正文（没有正文不给分析按钮） */
  hasContent: boolean
  analyzing: boolean
  onAnalyze: () => void
  /** 档案被作者改过 / 采用或忽略建议之后：让父组件重新拉分析结果 */
  onChanged: () => void
}

function Banner({ tone, children, action }: { tone: 'red' | 'gold' | 'gray'; children: ReactNode; action?: ReactNode }) {
  const cls = tone === 'red'
    ? 'border-red-200 bg-red-50 text-red-700'
    : tone === 'gold'
      ? 'border-amber-200 bg-amber-50 text-amber-800'
      : 'border-surface-border bg-surface-hover text-content-secondary'
  return (
    <div className={`mb-3 flex items-start gap-2 border px-3 py-2 text-xs leading-5 ${cls}`}>
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="min-w-0 flex-1">{children}</div>
      {action}
    </div>
  )
}

export function ChapterArchivePanel({ chapterId, data, loading, hasContent, analyzing, onAnalyze, onChanged }: Props) {
  const [editing, setEditing] = useState(false)
  const [summary, setSummary] = useState('')
  const [endState, setEndState] = useState('')
  const [busy, setBusy] = useState(false)

  if (loading) return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>

  const analyzeButton = hasContent ? (
    <button onClick={onAnalyze} disabled={analyzing} className="hh-btn-secondary hh-btn-sm shrink-0">
      {analyzing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
      {data?.analyzed ? '重新分析' : '分析本章'}
    </button>
  ) : null

  if (!data) {
    return (
      <div className="py-8 text-center text-xs leading-6 text-content-tertiary">
        <p>本章还没分析。</p>
        <p>分析后会记下摘要、章末状态、人物状态变化与伏笔动作，写后面的章节时按需召回。</p>
        {analyzeButton && <div className="mt-3 flex justify-center">{analyzeButton}</div>}
      </div>
    )
  }

  const digest = data.digest
  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true)
    try {
      await action()
      toast.success(done)
      setEditing(false)
      onChanged()
    } catch {
      /* 全局已 toast */
    } finally {
      setBusy(false)
    }
  }

  const startEdit = () => {
    setSummary(digest?.summary ?? '')
    setEndState(digest?.end_state ?? '')
    setEditing(true)
  }

  return (
    <div>
      {data.task?.status === 'failed' && (
        <Banner tone="red" action={analyzeButton}>
          <p className="font-medium">最近一次分析失败</p>
          <p>{data.task.message}</p>
          {data.analyzed && <p className="opacity-80">之前的分析结果仍在用。</p>}
        </Banner>
      )}
      {data.task?.status !== 'failed' && (data.is_stale || digest?.stale) && (
        <Banner tone="gold" action={analyzeButton}>正文在分析之后改过，下面的档案与状态可能过期。</Banner>
      )}
      {data.task?.status === 'completed' && data.task.message && (
        <Banner tone="gray">{data.task.message}</Banner>
      )}

      <section className="hh-subpanel mb-3 p-3">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-sm font-semibold text-content">章节档案</span>
          {digest && <Pill tone={digest.source === 'author' ? 'brand' : 'default'}>{digest.source === 'author' ? '作者版本' : 'AI 分析'}</Pill>}
          {!editing && (
            <button onClick={startEdit} className="hh-icon-btn-plain ml-auto h-7 w-7 hover:text-brand" title="修改摘要 / 章末状态（之后重新分析不会覆盖）" aria-label="修改档案">
              <Pencil className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {editing ? (
          <div className="space-y-2">
            <label className="block text-xs text-content-tertiary">
              摘要（本章发生了什么、结果如何）
              <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={5} maxLength={1000} className="mt-1 w-full text-[13px] leading-6" />
            </label>
            <label className="block text-xs text-content-tertiary">
              章末状态（主要人物各在哪、处境如何）
              <textarea value={endState} onChange={(e) => setEndState(e.target.value)} rows={3} maxLength={500} className="mt-1 w-full text-[13px] leading-6" />
            </label>
            <div className="flex justify-end gap-2">
              <button onClick={() => setEditing(false)} disabled={busy} className="hh-btn-ghost hh-btn-sm"><X className="h-3.5 w-3.5" />取消</button>
              <button
                onClick={() => void run(() => chapterApi.updateDigest(chapterId, { summary, end_state: endState }), '档案已保存，之后重新分析不会覆盖')}
                disabled={busy || !summary.trim()}
                className="hh-btn-primary hh-btn-sm"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}保存
              </button>
            </div>
          </div>
        ) : digest ? (
          <div className="space-y-2 text-[13px] leading-6 text-content">
            <p>{digest.summary || <span className="text-content-tertiary">（无摘要）</span>}</p>
            {digest.end_state && (
              <p className="text-content-secondary"><span className="text-content-tertiary">章末：</span>{digest.end_state}</p>
            )}
          </div>
        ) : (
          <p className="text-xs text-content-tertiary">还没有档案，点右上角可以手写一份。</p>
        )}
        {digest?.suggestion && !editing && (
          <div className="mt-3 border border-dashed border-brand/40 bg-brand/[0.04] p-2.5 text-xs leading-5">
            <p className="mb-1 font-medium text-brand">AI 重新分析的结果（你的版本没被覆盖）</p>
            <p className="text-content">{digest.suggestion.summary}</p>
            {digest.suggestion.end_state && <p className="mt-1 text-content-secondary">章末：{digest.suggestion.end_state}</p>}
            <div className="mt-2 flex justify-end gap-2">
              <button onClick={() => void run(() => chapterApi.dismissDigest(chapterId), '已忽略 AI 建议')} disabled={busy} className="hh-btn-ghost hh-btn-sm">忽略</button>
              <button onClick={() => void run(() => chapterApi.acceptDigest(chapterId), '已采用 AI 的档案')} disabled={busy} className="hh-btn-secondary hh-btn-sm">采用</button>
            </div>
          </div>
        )}
      </section>

      {data.state_changes.length > 0 && (
        <section className="hh-subpanel mb-3 p-3">
          <p className="mb-2 text-sm font-semibold text-content">人物状态变化</p>
          <ul className="space-y-1 text-[13px] leading-6 text-content">
            {data.state_changes.map((change, index) => (
              <li key={index} title={change.evidence ? `原文：${change.evidence}` : undefined}>{describeStateChange(change)}</li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-content-tertiary">记错了？到「故事账本 → 人物状态」里修正，重新分析也不会冲掉。</p>
        </section>
      )}

      {data.characters.length > 0 && (
        <section className="hh-subpanel mb-3 p-3">
          <p className="mb-2 text-sm font-semibold text-content">出场人物</p>
          <ul className="space-y-1 text-[13px] leading-6">
            {data.characters.map((c) => (
              <li key={c.name}><span className="font-medium text-content">{c.name}</span>{c.change && <span className="text-content-secondary">：{c.change}</span>}</li>
            ))}
          </ul>
        </section>
      )}

      {data.locations.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {data.locations.map((loc) => <Pill key={loc}>📍 {loc}</Pill>)}
        </div>
      )}
    </div>
  )
}
