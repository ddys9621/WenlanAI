/**
 * 拆书任务的派生状态（纯函数，便于单测）：徽标、主操作、切章检查、剩余时间估算。
 */
import type { BookDissectChapterItem, BookDissectRunMode, BookDissectStage, BookDissectTask } from '@/types'

export const STAGE_LABELS: Record<string, string> = {
  splitting: '章节切分',
  cards: '逐章拆书卡',
  arcs: '划分剧情单元',
  skeleton: '分卷 / 全书骨架',
  style: '文风指纹',
  pack: '写入拆书结果',
  split_done: '待抽取',
  queued: '排队中',
  done: '完成',
}

export function stageLabel(stage?: BookDissectStage | null): string {
  if (!stage) return ''
  return STAGE_LABELS[stage] ?? stage
}

export type TaskTone = 'running' | 'success' | 'partial' | 'warning' | 'danger' | 'idle'

export interface TaskBadge {
  label: string
  tone: TaskTone
}

/** 抽过拆书卡（哪怕全失败）或已经跑完过：之后的启动都是「继续 / 重抽」 */
export function hasCards(task: BookDissectTask): boolean {
  return (task.chapters_extracted ?? 0) + (task.chapters_failed ?? 0) > 0 || task.stage === 'done'
}

/** 范围内还没成功的章（失败的 + 没抽到的） */
export function pendingChapters(task: BookDissectTask): number {
  return Math.max(0, (task.chapters_total ?? 0) - (task.chapters_extracted ?? 0))
}

function finished(task: BookDissectTask): boolean {
  return task.status === 'completed' && task.stage === 'done'
}

export function taskBadge(task: BookDissectTask): TaskBadge {
  switch (task.status) {
    case 'running':
      return { label: stageLabel(task.extraction_phase ?? task.stage) || '抽取中', tone: 'running' }
    case 'interrupted':
      return { label: '已中断', tone: 'warning' }
    case 'cancelled':
      return { label: '已停止', tone: 'warning' }
    case 'failed':
      return { label: '失败', tone: 'danger' }
  }
  if (!finished(task)) return { label: '待抽取', tone: 'idle' }
  if (task.pack_status === 'failed') return { label: '结果不可用', tone: 'danger' }
  if ((task.chapters_failed ?? 0) > 0 || task.pack_status === 'partial') return { label: '部分完成', tone: 'partial' }
  return { label: '完成', tone: 'success' }
}

export interface PrimaryAction {
  label: string
  mode: BookDissectRunMode
}

/** 详情头部的主按钮：打开抽取弹窗时预选的运行方式 */
export function primaryAction(task: BookDissectTask): PrimaryAction | null {
  if (task.status === 'running') return null
  if (!hasCards(task)) return { label: '开始抽取', mode: 'full' }
  if (!finished(task)) return { label: '继续抽取', mode: 'resume' }
  if ((task.chapters_failed ?? 0) > 0) return { label: '重试失败章节', mode: 'resume' }
  if (task.pack_status === 'partial' || task.pack_status === 'failed') return { label: '重建结果', mode: 'rebuild_post' }
  return { label: '重新抽取…', mode: 'resume' }
}

// ---------------- 切章检查 ----------------

/** 超过这么多字的章值得看一眼（多半是标题没识别出来，把几章并成了一章） */
export const GIANT_CHAPTER_WORDS = 30_000
/** 与后端 llm_chapter_splitter.VERY_LARGE_CHAPTER 一致：有一章超过它，抽取时会请 AI 重新判断整本的切法 */
export const RESPLIT_CHAPTER_WORDS = 50_000
export const TINY_CHAPTER_WORDS = 300

export interface SplitReport {
  count: number
  totalWords: number
  median: number
  max: number
  giant: BookDissectChapterItem[]
  resplitTriggers: BookDissectChapterItem[]
  tiny: BookDissectChapterItem[]
  special: BookDissectChapterItem[]
  willResplit: boolean
}

export function splitReport(chapters: BookDissectChapterItem[]): SplitReport {
  const words = chapters.map((c) => c.word_count).sort((a, b) => a - b)
  const mid = Math.floor(words.length / 2)
  const median = words.length === 0 ? 0 : words.length % 2 ? words[mid] : Math.round((words[mid - 1] + words[mid]) / 2)
  const resplitTriggers = chapters.filter((c) => c.word_count > RESPLIT_CHAPTER_WORDS)
  return {
    count: chapters.length,
    totalWords: words.reduce((a, b) => a + b, 0),
    median,
    max: words[words.length - 1] ?? 0,
    giant: chapters.filter((c) => c.word_count >= GIANT_CHAPTER_WORDS),
    resplitTriggers,
    tiny: chapters.filter((c) => c.kind === 'chapter' && c.word_count < TINY_CHAPTER_WORDS),
    special: chapters.filter((c) => c.kind !== 'chapter'),
    willResplit: resplitTriggers.length > 0 || (chapters.length === 1 && (words[0] ?? 0) > GIANT_CHAPTER_WORDS),
  }
}

// ---------------- 剩余时间 ----------------

export interface RateSample {
  /** 毫秒时间戳 */
  at: number
  /** 当时已处理（成功 + 失败）的章数 */
  done: number
}

/** 按最近几次采样的抽取速度估算剩余秒数；样本不够（跨度不到 20 秒或没进展）返回 null */
export function estimateRemainingSeconds(samples: RateSample[], remaining: number): number | null {
  if (samples.length < 2 || remaining <= 0) return null
  const first = samples[0]
  const last = samples[samples.length - 1]
  const seconds = (last.at - first.at) / 1000
  const progressed = last.done - first.done
  if (seconds < 20 || progressed <= 0) return null
  return Math.round(remaining / (progressed / seconds))
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return '不到 1 分钟'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `约 ${minutes} 分钟`
  return `约 ${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`
}
