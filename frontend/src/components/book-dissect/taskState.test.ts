import { describe, expect, it } from 'vitest'

import type { BookDissectChapterItem, BookDissectTask } from '@/types'
import {
  estimateRemainingSeconds,
  formatDuration,
  pendingChapters,
  primaryAction,
  splitReport,
  taskBadge,
} from './taskState'

const task = (over: Partial<BookDissectTask> = {}): BookDissectTask => ({
  id: 't1',
  user_id: 'u1',
  status: 'completed',
  progress: 100,
  stage: 'done',
  file_size: 1,
  chapter_count: 10,
  total_words: 30000,
  chapters_total: 10,
  chapters_extracted: 10,
  chapters_failed: 0,
  created_at: '2026-10-22T00:00:00Z',
  ...over,
})

describe('taskBadge', () => {
  it('运行中显示当前阶段', () => {
    expect(taskBadge(task({ status: 'running', stage: 'cards', extraction_phase: 'cards' }))).toEqual({ label: '逐章拆书卡', tone: 'running' })
  })

  it('中断 / 停止 / 失败', () => {
    expect(taskBadge(task({ status: 'interrupted' }))).toEqual({ label: '已中断', tone: 'warning' })
    expect(taskBadge(task({ status: 'cancelled' }))).toEqual({ label: '已停止', tone: 'warning' })
    expect(taskBadge(task({ status: 'failed' }))).toEqual({ label: '失败', tone: 'danger' })
  })

  it('刚上传还没抽', () => {
    expect(taskBadge(task({ stage: 'split_done', chapters_total: 0, chapters_extracted: 0 }))).toEqual({ label: '待抽取', tone: 'idle' })
  })

  it('有章节失败或结果缺维度是「部分完成」，结果不可用单列', () => {
    expect(taskBadge(task({ chapters_extracted: 7, chapters_failed: 3 })).label).toBe('部分完成')
    expect(taskBadge(task({ pack_status: 'partial' }))).toEqual({ label: '部分完成', tone: 'partial' })
    expect(taskBadge(task({ pack_status: 'failed' }))).toEqual({ label: '结果不可用', tone: 'danger' })
    expect(taskBadge(task({ pack_status: 'ready' }))).toEqual({ label: '完成', tone: 'success' })
  })
})

describe('primaryAction', () => {
  it('没抽过：开始抽取（全部）', () => {
    expect(primaryAction(task({ stage: 'split_done', chapters_total: 0, chapters_extracted: 0 }))).toEqual({ label: '开始抽取', mode: 'full' })
    expect(primaryAction(task({ status: 'failed', stage: 'cards', chapters_extracted: 0, chapters_failed: 0 }))).toEqual({ label: '开始抽取', mode: 'full' })
  })

  it('中断 / 停止 / 失败且有卡：继续抽取', () => {
    for (const status of ['interrupted', 'cancelled', 'failed'] as const) {
      expect(primaryAction(task({ status, stage: 'cards', chapters_extracted: 4, chapters_failed: 0 }))).toEqual({ label: '继续抽取', mode: 'resume' })
    }
  })

  it('完成但有失败章节：重试失败章节；只缺维度：重建结果；都齐了：重新抽取', () => {
    expect(primaryAction(task({ chapters_extracted: 8, chapters_failed: 2 }))).toEqual({ label: '重试失败章节', mode: 'resume' })
    expect(primaryAction(task({ pack_status: 'partial' }))).toEqual({ label: '重建结果', mode: 'rebuild_post' })
    expect(primaryAction(task({ pack_status: 'ready' }))).toEqual({ label: '重新抽取…', mode: 'resume' })
  })

  it('运行中没有主操作', () => {
    expect(primaryAction(task({ status: 'running' }))).toBeNull()
  })

  it('待抽章数 = 范围内没成功的', () => {
    expect(pendingChapters(task({ chapters_total: 10, chapters_extracted: 7, chapters_failed: 1 }))).toBe(3)
  })
})

const ch = (number: number, word_count: number, kind = 'chapter'): BookDissectChapterItem => ({
  number, title: `标题${number}`, raw_title: `第${number}章`, word_count, kind, status: null, error: null,
})

describe('splitReport', () => {
  it('统计与异常章', () => {
    const report = splitReport([ch(1, 120, 'preamble'), ch(2, 3000), ch(3, 3200), ch(4, 35000), ch(5, 60000), ch(6, 150)])
    expect(report.count).toBe(6)
    expect(report.median).toBe(3100)
    expect(report.giant.map((c) => c.number)).toEqual([4, 5])
    expect(report.resplitTriggers.map((c) => c.number)).toEqual([5])
    expect(report.tiny.map((c) => c.number)).toEqual([6])
    expect(report.special.map((c) => c.number)).toEqual([1])
    expect(report.willResplit).toBe(true)
  })

  it('整本只切出一章且很长也会触发 AI 重新切章', () => {
    expect(splitReport([ch(1, 40000)]).willResplit).toBe(true)
    expect(splitReport([ch(1, 3000), ch(2, 3000)]).willResplit).toBe(false)
  })
})

describe('剩余时间', () => {
  it('按最近的抽取速度估算', () => {
    const samples = [{ at: 0, done: 10 }, { at: 60_000, done: 16 }, { at: 120_000, done: 22 }]
    expect(estimateRemainingSeconds(samples, 30)).toBe(300)
  })

  it('样本太少 / 时间太短 / 没进展时不估', () => {
    expect(estimateRemainingSeconds([{ at: 0, done: 1 }], 10)).toBeNull()
    expect(estimateRemainingSeconds([{ at: 0, done: 1 }, { at: 5_000, done: 2 }], 10)).toBeNull()
    expect(estimateRemainingSeconds([{ at: 0, done: 1 }, { at: 60_000, done: 1 }], 10)).toBeNull()
  })

  it('时长文案', () => {
    expect(formatDuration(40)).toBe('不到 1 分钟')
    expect(formatDuration(180)).toBe('约 3 分钟')
    expect(formatDuration(4000)).toBe('约 1 小时 7 分')
  })
})
