/** 写作链路的展示辅助：审校结论、版本来源、候选稿采用后的效果预览（与后端 chapter_candidate_service._apply 一致）。 */
import type { AdherenceReport, CandidateMode } from '@/types/writing'

export type Tone = 'ok' | 'stale' | 'muted' | 'draft'

export function adherenceVerdict(report: AdherenceReport | null | undefined): { tone: Tone; label: string; detail?: string } {
  if (!report) return { tone: 'muted', label: '未审校' }
  if (report.status === 'error') return { tone: 'muted', label: '审校没跑成', detail: report.message }
  if (report.passed) return { tone: 'ok', label: '照章纲写了' }
  return { tone: 'stale', label: `有 ${report.issues.length} 处偏离章纲` }
}

const REASON_LABELS: Record<string, string> = {
  manual_edit: '手动修改前',
  adopt_candidate: '采用候选稿前',
  restore: '恢复旧版前',
  assistant: '助笔修改前',
}

export function versionReasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason
}

export const CANDIDATE_MODE_LABELS: Record<CandidateMode, string> = {
  replace_all: '整章替换',
  append: '接在末尾',
  replace_range: '替换选段',
}

interface ApplyTarget {
  mode: CandidateMode
  range_start: number | null
  range_end: number | null
  original_text: string | null
}

const AUTO_ANALYZE_KEY = 'wenlan-candidate-auto-analyze'

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>

const browserStorage = (): StorageLike | null => (typeof localStorage === 'undefined' ? null : localStorage)

/** 候选稿面板「采用后自动分析本章」：记住上次的勾选（本机） */
export function loadAutoAnalyze(storage: StorageLike | null = browserStorage()): boolean {
  try {
    return storage?.getItem(AUTO_ANALYZE_KEY) === '1'
  } catch {
    return false
  }
}

export function saveAutoAnalyze(value: boolean, storage: StorageLike | null = browserStorage()): void {
  try {
    storage?.setItem(AUTO_ANALYZE_KEY, value ? '1' : '0')
  } catch {
    /* 写不进 localStorage：仅本次生效 */
  }
}

/** 采用后正文会变成什么样；选段对不上（采用会被拒绝）返回 null */
export function candidateApplyPreview(content: string, candidate: ApplyTarget, text: string): string | null {
  if (candidate.mode === 'append') {
    const base = content.replace(/\s+$/, '')
    const addition = text.trim()
    return base ? `${base}\n\n${addition}` : addition
  }
  if (candidate.mode === 'replace_range') {
    const original = candidate.original_text ?? ''
    const { range_start: start, range_end: end } = candidate
    if (start !== null && end !== null && content.slice(start, end) === original) {
      return content.slice(0, start) + text + content.slice(end)
    }
    const idx = original ? content.indexOf(original) : -1
    if (idx < 0 || content.indexOf(original, idx + 1) >= 0) return null
    return content.slice(0, idx) + text + content.slice(idx + original.length)
  }
  return text
}
