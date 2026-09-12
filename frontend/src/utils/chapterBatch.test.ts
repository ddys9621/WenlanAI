import { describe, expect, it } from 'vitest'
import type { Chapter } from '@/types'
import { selectBatchChapters } from './chapterBatch'

const ch = (n: number, status: Chapter['status'] = 'draft', words = 0): Chapter => ({
  id: `c${n}`, project_id: 'p', title: `第${n}章`, chapter_number: n, word_count: words, status,
  created_at: '', updated_at: '',
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

  it('范围颠倒或为空时返回空', () => {
    expect(selectBatchChapters([ch(1), ch(2)], 2, 1)).toEqual({ toGenerate: [], skipped: 0 })
    expect(selectBatchChapters([], 1, 9)).toEqual({ toGenerate: [], skipped: 0 })
  })
})
