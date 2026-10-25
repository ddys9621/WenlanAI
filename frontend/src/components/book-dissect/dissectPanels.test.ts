import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { describe, expect, it } from 'vitest'

import type { BookDissectTask } from '@/types'
import { ChapterCheckPanel } from './ChapterCheckPanel'
import { TaskProgressPanel } from './TaskProgressPanel'

/** 拆书页新面板：服务端渲染冒烟（无 jsdom，只验证不抛 + 关键内容在场） */

const task = (over: Partial<BookDissectTask> = {}): BookDissectTask => ({
  id: 't1',
  user_id: 'u1',
  status: 'running',
  progress: 40,
  stage: 'cards',
  extraction_phase: 'cards',
  file_size: 1,
  chapter_count: 10,
  total_words: 30000,
  chapters_total: 10,
  chapters_extracted: 5,
  chapters_failed: 2,
  created_at: '2026-10-22T00:00:00Z',
  ...over,
})

const inRouter = (node: ReturnType<typeof h>) => renderToStaticMarkup(h(StaticRouter, { location: '/book-dissect' }, node))

describe('TaskProgressPanel', () => {
  it('运行中：阶段、成功 / 失败 / 没抽的章数、三色进度', () => {
    const html = inRouter(h(TaskProgressPanel, { task: task(), job: null }))
    for (const s of ['逐章拆书卡', '整体 40%', '已抽', '/ 10 章', '2 章失败', '3 章还没抽', 'role="progressbar"']) expect(html).toContain(s)
    expect(html).not.toContain('去知识库看')
  })

  it('跑完：不转圈，结果就绪时给知识库入口', () => {
    const html = inRouter(h(TaskProgressPanel, {
      task: task({ status: 'completed', stage: 'done', extraction_phase: 'done', chapters_extracted: 10, chapters_failed: 0 }),
      job: null,
      showKnowledgeLink: true,
    }))
    expect(html).toContain('去知识库看')
    expect(html).not.toContain('animate-spin')
    expect(html).not.toContain('章失败')
  })
})

describe('ChapterCheckPanel', () => {
  it('刚上传：默认展开切章检查，底部给「设置抽取范围」（SSR 不拉数据）', () => {
    const html = renderToStaticMarkup(h(ChapterCheckPanel, { taskId: 't1', defaultOpen: true, onStart: () => undefined }))
    expect(html).toContain('切章检查')
    expect(html).toContain('设置抽取范围')
  })

  it('抽过之后：叫章节目录，默认收起', () => {
    const html = renderToStaticMarkup(h(ChapterCheckPanel, { taskId: 't1' }))
    expect(html).toContain('章节目录')
    expect(html).not.toContain('设置抽取范围')
  })
})
