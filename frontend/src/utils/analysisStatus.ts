/** 章节分析状态的说明文字（目录状态点 / 章节档案列表共用） */
import type { ChapterAnalysisStatus } from '@/types'

export const ANALYSIS_STATUS_LABELS: Record<ChapterAnalysisStatus, string> = {
  ok: '已分析',
  stale: '正文在分析之后改过，档案与人物状态可能过期',
  failed: '最近一次分析失败',
  missing: '还没分析',
  running: '分析中',
}

export function analysisStatusLabel(status: ChapterAnalysisStatus | null | undefined, message?: string | null): string {
  const base = ANALYSIS_STATUS_LABELS[status ?? 'missing'] ?? ANALYSIS_STATUS_LABELS.missing
  return message && status !== 'running' ? `${base}：${message}` : base
}
