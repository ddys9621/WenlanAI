import type { Chapter, ChapterBatchEvent } from '@/types'

/** 批量生成范围内待生成的章：按序号升序，跳过已有正文的（不论状态，和服务端一致），避免覆盖 */
export function selectBatchChapters(chapters: Chapter[], from: number, to: number): { toGenerate: Chapter[]; skipped: number } {
  const inRange = chapters
    .filter((c) => c.chapter_number >= from && c.chapter_number <= to)
    .sort((a, b) => a.chapter_number - b.chapter_number)
  const toGenerate = inRange.filter((c) => !(c.word_count > 0))
  return { toGenerate, skipped: inRange.length - toGenerate.length }
}

/** 服务端批量要写的章数：现有待写章节 + 超出现有章节、需要服务端自动规划（滚动展开桥段）的章节 */
export function countBatchTargets(chapters: Chapter[], from: number, to: number): number {
  if (to < from) return 0
  const { toGenerate } = selectBatchChapters(chapters, from, to)
  const lastExisting = chapters.reduce((max, c) => Math.max(max, c.chapter_number), 0)
  return toGenerate.length + Math.max(0, to - Math.max(lastExisting, from - 1))
}

/** 服务端批量的逐章事件 → 进度文案（跳过 / 完成等不需要单独提示的返回空串） */
export function describeBatchEvent(e: ChapterBatchEvent): string {
  const n = e.chapter_number
  switch (e.status) {
    case 'generating': return (e.attempt ?? 1) > 1 ? `第 ${n} 章重新生成（第 ${e.attempt} 次）` : `正在生成第 ${n} 章`
    case 'retrying': return `第 ${n} 章生成失败，稍后重试：${e.error ?? ''}`
    case 'quality_retry': return `第 ${n} 章质检未过（${e.reason ?? ''}），重写一次`
    case 'generated': return `第 ${n} 章已写完${typeof e.quality_score === 'number' ? `（AI 味 ${e.quality_score}）` : ''}`
    case 'analyzing': return `正在分析第 ${n} 章`
    case 'analysis_failed': return `第 ${n} 章分析失败，后续章节缺少这一章的记忆`
    case 'paused': return `第 ${n} 章检测到 ${e.critical ?? 0} 个严重一致性问题，已暂停`
    case 'no_outline': return `第 ${n} 章没有章纲，批量停止`
    case 'outline_unconfirmed': return `第 ${n} 章章纲未确认（AI 草拟或上游已改），批量停止`
    case 'failed': return `第 ${n} 章多次生成失败：${e.error ?? ''}`
    default: return ''
  }
}
