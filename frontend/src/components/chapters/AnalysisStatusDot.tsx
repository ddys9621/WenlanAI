/** 章节目录里的分析状态点：绿 = 已分析；琥珀 = 正文改过待重新分析；红 = 最近一次分析失败；空心 = 未分析；转圈 = 分析中 */
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ChapterAnalysisStatus } from '@/types'
import { analysisStatusLabel } from '@/utils/analysisStatus'

const DOT_CLASS: Record<Exclude<ChapterAnalysisStatus, 'running'>, string> = {
  ok: 'bg-emerald-500',
  stale: 'bg-amber-400',
  failed: 'bg-red-500',
  missing: 'border border-content-tertiary bg-transparent',
}

export function AnalysisStatusDot({ status, message, className }: {
  status: ChapterAnalysisStatus | null | undefined
  message?: string | null
  className?: string
}) {
  const label = analysisStatusLabel(status, message)
  if (status === 'running') {
    return <Loader2 className={cn('h-2.5 w-2.5 shrink-0 animate-spin text-brand', className)} aria-label={label} />
  }
  return (
    <span role="img" aria-label={label} title={label}
      className={cn('inline-block h-2 w-2 shrink-0 rounded-full', DOT_CLASS[status ?? 'missing'] ?? DOT_CLASS.missing, className)} />
  )
}
