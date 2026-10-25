/**
 * 拆书进度：当前阶段 + 拆书卡三色进度（成功 / 失败 / 还没抽）+ 已运行 / 预计还需 + 失败章节入口。
 * 剩余时间按页面开着时最近 10 分钟的抽取速度估（只在拆书卡阶段有意义）；已运行取后台任务的开始时间（与时区无关）。
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Clock, Loader2, Sparkles } from 'lucide-react'

import type { BookDissectTask } from '@/types'
import type { AIJobSummary } from '@/types/ai_job'
import { estimateRemainingSeconds, formatDuration, stageLabel, type RateSample } from './taskState'

const RATE_WINDOW_MS = 10 * 60 * 1000

function useNow(intervalMs: number | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (intervalMs == null) return
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

interface TaskProgressPanelProps {
  task: BookDissectTask
  job: AIJobSummary | null
  /** 拆书结果已就绪：右上角给「去知识库看」 */
  showKnowledgeLink?: boolean
  onShowFailed?: () => void
}

export function TaskProgressPanel({ task, job, showKnowledgeLink = false, onShowFailed }: TaskProgressPanelProps) {
  const running = task.status === 'running'
  const total = task.chapters_total ?? 0
  const ok = task.chapters_extracted ?? 0
  const failed = task.chapters_failed ?? 0
  const pending = Math.max(0, total - ok - failed)
  const overall = Math.max(0, Math.min(100, Math.round(job?.progress?.pct ?? task.progress ?? 0)))
  const message = running ? job?.progress?.message : null
  const phase = task.extraction_phase ?? task.stage
  const now = useNow(running ? 5000 : null)

  const samples = useRef<RateSample[]>([])
  const [eta, setEta] = useState<number | null>(null)
  const inCards = running && phase === 'cards'
  useEffect(() => {
    if (!inCards) {
      samples.current = []
      setEta(null)
      return
    }
    const at = Date.now()
    samples.current = [...samples.current.filter((s) => at - s.at <= RATE_WINDOW_MS), { at, done: ok + failed }]
    setEta(estimateRemainingSeconds(samples.current, pending))
  }, [inCards, ok, failed, pending])

  const width = (n: number) => `${total > 0 ? (n / total) * 100 : 0}%`

  return (
    <div className="hh-panel space-y-2.5 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-content-secondary">
        <span className="inline-flex items-center gap-1.5 font-medium text-content">
          {running && <Loader2 className="h-3.5 w-3.5 animate-spin text-brand" />}
          {running ? stageLabel(phase) || '准备中' : '拆书卡'}
          {running && <span className="font-normal text-content-tertiary">· 整体 {overall}%</span>}
        </span>
        {total > 0 && (
          <span>
            已抽 <strong className="font-semibold text-content">{ok}</strong> / {total} 章
          </span>
        )}
        {failed > 0 && (
          <button type="button" onClick={onShowFailed} className="text-rose-700 hover:underline" title="在逐章拆书表里只看失败的章">
            {failed} 章失败
          </button>
        )}
        {pending > 0 && <span>{pending} 章还没抽</span>}
        {running && job && (
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3 w-3" />
            已运行 {formatDuration(Math.max(0, (now - job.startedAt) / 1000))}
          </span>
        )}
        {eta != null && <span>预计还需 {formatDuration(eta)}</span>}
        {showKnowledgeLink && (
          <Link to="/knowledge" className="ml-auto inline-flex items-center gap-1 text-brand hover:underline">
            <Sparkles className="h-3 w-3" />
            去知识库看
          </Link>
        )}
      </div>
      {total > 0 ? (
        <div
          className="flex h-2 overflow-hidden rounded-full bg-surface-muted"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={ok}
          aria-label={`拆书卡：成功 ${ok} 章，失败 ${failed} 章，还没抽 ${pending} 章`}
        >
          <div className="h-full bg-brand transition-all duration-500" style={{ width: width(ok) }} />
          <div className="h-full bg-rose-400 transition-all duration-500" style={{ width: width(failed) }} />
        </div>
      ) : (
        running && (
          <div className="hh-progress">
            <div className="hh-progress-bar" style={{ width: `${overall}%` }} />
          </div>
        )
      )}
      {message && (
        <p className="truncate text-xs text-content-tertiary" title={message}>
          {message}
        </p>
      )}
    </div>
  )
}
