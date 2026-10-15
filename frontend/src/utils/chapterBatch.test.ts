import { describe, expect, it } from 'vitest'
import type { Chapter, ChapterBatchEvent } from '@/types'
import { countBatchTargets, describeBatchEvent, selectBatchChapters } from './chapterBatch'

const ch = (n: number, status: Chapter['status'] = 'draft', words = 0): Chapter => ({
  id: `c${n}`, project_id: 'p', title: `第${n}章`, chapter_number: n, word_count: words, status,
  created_at: '', updated_at: '',
})

const ev = (status: ChapterBatchEvent['status'], extra: Partial<ChapterBatchEvent> = {}): ChapterBatchEvent => ({
  type: 'batch_chapter', chapter_number: 7, chapter_id: 'c7', status, ...extra,
})

describe('selectBatchChapters', () => {
  it('只取范围内且未完成的章，按序号升序', () => {
    const chapters = [ch(3), ch(1), ch(2, 'completed', 3000), ch(4), ch(5)]
    const { toGenerate, skipped } = selectBatchChapters(chapters, 2, 4)
    expect(toGenerate.map((c) => c.chapter_number)).toEqual([3, 4])
    expect(skipped).toBe(1)
  })

  it('已完成但没有字数的章仍要生成', () => {
    const { toGenerate, skipped } = selectBatchChapters([ch(1, 'completed', 0)], 1, 1)
    expect(toGenerate).toHaveLength(1)
    expect(skipped).toBe(0)
  })

  it('有正文的章不论状态都跳过（和服务端一致：手写的草稿章不会被批量覆盖）', () => {
    const { toGenerate, skipped } = selectBatchChapters([ch(1, 'draft', 1200), ch(2)], 1, 2)
    expect(toGenerate.map((c) => c.chapter_number)).toEqual([2])
    expect(skipped).toBe(1)
    expect(countBatchTargets([ch(1, 'draft', 1200), ch(2)], 1, 2)).toBe(1)
  })

  it('范围颠倒或为空时返回空', () => {
    expect(selectBatchChapters([ch(1), ch(2)], 2, 1)).toEqual({ toGenerate: [], skipped: 0 })
    expect(selectBatchChapters([], 1, 9)).toEqual({ toGenerate: [], skipped: 0 })
  })
})

describe('countBatchTargets', () => {
  it('现有待写章节 + 超出现有章节、需要服务端自动规划的章节', () => {
    const chapters = [ch(1, 'completed', 3000), ch(2), ch(3)]
    expect(countBatchTargets(chapters, 1, 3)).toBe(2)
    expect(countBatchTargets(chapters, 2, 10)).toBe(9) // 2、3 + 4..10
    expect(countBatchTargets([], 1, 5)).toBe(5)
    expect(countBatchTargets(chapters, 3, 2)).toBe(0)
  })
})

describe('describeBatchEvent', () => {
  it('把逐章事件翻成进度文案', () => {
    expect(describeBatchEvent(ev('generating'))).toBe('正在生成第 7 章')
    expect(describeBatchEvent(ev('generating', { attempt: 2 }))).toContain('第 2 次')
    expect(describeBatchEvent(ev('quality_retry', { reason: 'AI 味分 80' }))).toContain('AI 味分 80')
    expect(describeBatchEvent(ev('generated', { quality_score: 12 }))).toContain('AI 味 12')
    expect(describeBatchEvent(ev('paused', { critical: 2 }))).toContain('2 个严重一致性问题')
    expect(describeBatchEvent(ev('outline_unconfirmed'))).toContain('未确认')
    expect(describeBatchEvent(ev('skipped'))).toBe('')
  })
})
