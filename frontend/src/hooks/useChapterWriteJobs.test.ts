import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AIJobSnapshot } from '@/types/ai_job'
import type { SSEClientOptions, SSEMessage } from '@/utils/sseClient'

vi.mock('sonner', () => ({ toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() } }))
vi.mock('@/services/aiJobsApi', () => ({
  aiJobsApi: { list: vi.fn(), get: vi.fn(), events: vi.fn(), cancel: vi.fn(), dismiss: vi.fn() },
}))

import { toast } from 'sonner'
import { aiJobsApi } from '@/services/aiJobsApi'
import { useAIJobsStore } from '@/store/aiJobsStore'
import { useChapterWriteJobs } from './useChapterWriteJobs'

const api = aiJobsApi as unknown as Record<'get' | 'events', ReturnType<typeof vi.fn>>
const CHAPTER = { id: 'c1', title: '启程' }

const snapshot = (over: Partial<AIJobSnapshot> = {}): AIJobSnapshot => ({
  id: 'ja', kind: 'chapter_analyze', title: '分析第 1 章《启程》', project_id: 'p1', scope: 'chapter_analyze:c1',
  meta: { chapter_id: 'c1', task_id: 't1' }, status: 'running', started_at: 1000, finished_at: null, elapsed: 0, seq: 1,
  error: null, result: null, last_progress: { type: 'progress', message: '准备分析章节…', progress: 2, seq: 1 }, live: {},
  ...over,
})

/** 后端事件流：测试里逐条推，最后结束连接。store 的「终态已回调」记录跨用例保留，每个用例用不同的任务 id */
function controlledEvents() {
  const stream: { push: (m: Record<string, unknown>) => void; end: () => void } = { push: () => {}, end: () => {} }
  api.events.mockImplementation((_id: string, _since: number, options: SSEClientOptions<unknown>) => new Promise<boolean>((resolve) => {
    stream.push = (m) => options.onMessage?.(m as unknown as SSEMessage)
    stream.end = () => resolve(true)
  }))
  return stream
}

const flush = () => new Promise<void>((r) => setTimeout(r, 0))

function setup() {
  const refreshChapters = vi.fn().mockResolvedValue([])
  const onChapterWritten = vi.fn()
  let hook: ReturnType<typeof useChapterWriteJobs> | null = null
  const Probe = () => {
    hook = useChapterWriteJobs({ projectId: 'p1', chapters: [], refreshChapters, onChapterWritten })
    return null
  }
  const render = () => {
    renderToStaticMarkup(h(Probe))
    return hook!
  }
  return { render, refreshChapters, onChapterWritten }
}

beforeEach(() => {
  useAIJobsStore.setState({ jobs: {}, openJobId: null })
  vi.clearAllMocks()
})

describe('采用候选稿后接上服务端排的分析（followAnalysis）', () => {
  it('分析中：进托盘、目录转圈、侧栏拿得到进度，不弹窗；跑完提示并刷新目录与阅读区', async () => {
    api.get.mockResolvedValue(snapshot())
    const stream = controlledEvents()
    const { render, refreshChapters, onChapterWritten } = setup()
    await render().followAnalysis(CHAPTER, 'ja')
    stream.push({ type: 'progress', message: '模型分析章节中…', progress: 20, seq: 2 })

    const hook = render()
    expect(useAIJobsStore.getState().jobs.ja?.kind).toBe('chapter_analyze')
    expect(hook.analyzingChapterIds.has('c1')).toBe(true)
    expect(hook.analysisJobOf('c1')?.progress).toEqual({ message: '模型分析章节中…', pct: 20 })
    expect(useAIJobsStore.getState().openJobId).toBeNull()
    expect(refreshChapters).not.toHaveBeenCalled()

    stream.push({ type: 'result', data: { status: 'completed', warning: null }, seq: 3 })
    stream.push({ type: 'done', seq: 4 })
    stream.end()
    await flush()
    expect(toast.success).toHaveBeenCalledWith('「启程」分析完成')
    expect(refreshChapters).toHaveBeenCalledTimes(1)
    expect(onChapterWritten).toHaveBeenCalledWith('c1')
    expect(render().analyzingChapterIds.has('c1')).toBe(false)
  })

  it('分析失败：没开着任务弹窗时弹出错误原因，并刷新（目录变「分析失败」）', async () => {
    api.get.mockResolvedValue(snapshot({ id: 'jb' }))
    const stream = controlledEvents()
    const { render, refreshChapters } = setup()
    await render().followAnalysis(CHAPTER, 'jb')
    stream.push({ type: 'error', error: '分析第 1 章《启程》失败: 输出被截断', code: 500, seq: 2 })
    stream.end()
    await flush()
    expect(toast.error).toHaveBeenCalledWith('分析第 1 章《启程》失败: 输出被截断')
    expect(refreshChapters).toHaveBeenCalledTimes(1)
  })

  it('接上时分析已经跑完：直接按终态提示并刷新', async () => {
    api.get.mockResolvedValue(snapshot({ id: 'jc', status: 'done', finished_at: 1002, result: { warning: '人物与标注没抽出来' } }))
    const { render, refreshChapters, onChapterWritten } = setup()
    await render().followAnalysis(CHAPTER, 'jc')
    await flush()
    expect(api.events).not.toHaveBeenCalled()
    expect(toast.warning).toHaveBeenCalledWith('「启程」分析完成，但人物与标注没抽出来')
    expect(refreshChapters).toHaveBeenCalledTimes(1)
    expect(onChapterWritten).toHaveBeenCalledWith('c1')
  })
})
