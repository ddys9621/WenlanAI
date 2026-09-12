import type { Chapter } from '@/types'

/** 批量生成范围内待生成的章：按序号升序，跳过「已完成且有正文」的，避免覆盖 */
export function selectBatchChapters(chapters: Chapter[], from: number, to: number): { toGenerate: Chapter[]; skipped: number } {
  const inRange = chapters
    .filter((c) => c.chapter_number >= from && c.chapter_number <= to)
    .sort((a, b) => a.chapter_number - b.chapter_number)
  const toGenerate = inRange.filter((c) => !(c.status === 'completed' && c.word_count > 0))
  return { toGenerate, skipped: inRange.length - toGenerate.length }
}
