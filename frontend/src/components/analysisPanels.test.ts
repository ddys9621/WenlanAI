import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { MemoryAnnotation } from '@/utils/annotationSegments'
import { describeStateChange, normalizeAnalysisData } from '@/utils/chapterAnalysis'
import AnnotatedText from './AnnotatedText'
import MemorySidebar from './MemorySidebar'
import { ChapterArchivePanel } from './chapters/ChapterArchivePanel'
import { AnalysisStatusDot } from './chapters/AnalysisStatusDot'
import { NarrativeStatePanel } from './chapters/NarrativeStatePanel'

/** 章节分析面板：服务端渲染冒烟（无 jsdom，只验证不抛错 + 关键内容在场） */

const CONTENT = '他推开门，屋里没人。桌上留着一封信，信封上是她的字。'
const ann = (over: Partial<MemoryAnnotation>): MemoryAnnotation => ({
  id: 'a1', type: 'hook', title: '一封信', content: '桌上的信是谁留下的', importance: 0.8, position: 10, length: 8,
  tags: ['悬念'], metadata: { quote: '桌上留着一封信' }, ...over,
})

describe('MemorySidebar', () => {
  it('空标注给提示', () => {
    expect(renderToStaticMarkup(h(MemorySidebar, { annotations: [] }))).toContain('暂无标注')
  })

  it('按类型分组、概览计数、引句、找不到的标注提示、选中态', () => {
    const html = renderToStaticMarkup(h(MemorySidebar, {
      annotations: [
        ann({}),
        ann({ id: 'a2', type: 'foreshadow', title: '字迹', metadata: { quote: '信封上是她的字' } }),
        ann({ id: 'a3', type: 'plot_point', title: '改过的段落', position: -1, length: 0 }),
      ],
      activeAnnotationId: 'a2',
    }))
    expect(html).toContain('标注概览')
    expect(html).toContain('一封信')
    expect(html).toContain('「信封上是她的字」')
    expect(html).toContain('原文已改')
    expect(html).toContain('关键转折')
    expect(html).toContain('ring-brand/30') // 选中卡片
    expect((html.match(/<details open=""/g) ?? []).length).toBe(3)
    expect(html).not.toContain('角色事件')
  })
})

describe('AnnotatedText', () => {
  it('把标注切成带下划线的片段并保留全文', () => {
    const html = renderToStaticMarkup(h(AnnotatedText, {
      content: CONTENT,
      annotations: [ann({ position: CONTENT.indexOf('桌上留着一封信'), length: 7 })],
      activeAnnotationId: 'a1',
    }))
    expect(html).toContain('data-annotation-id="a1"')
    expect(html).toContain('annotated-text active')
    // 类型图标挂在标注片段末尾（绝对定位浮在片段上方），去掉标签后全文仍完整连续
    expect(html.replace(/<[^>]+>/g, '')).toBe('他推开门，屋里没人。桌上留着一封信🎣，信封上是她的字。')
    expect(html).not.toContain('role="tooltip"') // 未悬停时无浮层
  })

  it('引句找不到（position=-1）的标注不画进正文', () => {
    const html = renderToStaticMarkup(h(AnnotatedText, { content: CONTENT, annotations: [ann({ position: -1, length: 0 })] }))
    expect(html).not.toContain('data-annotation-id')
    expect(html.replace(/<[^>]+>/g, '')).toBe(CONTENT)
  })
})

describe('NarrativeStatePanel', () => {
  it('加载中 / 无数据 / 空数据三态', () => {
    expect(renderToStaticMarkup(h(NarrativeStatePanel, { data: null, loading: true }))).toContain('animate-spin')
    expect(renderToStaticMarkup(h(NarrativeStatePanel, { data: null, loading: false }))).toContain('暂无叙事状态数据')
    expect(renderToStaticMarkup(h(NarrativeStatePanel, { data: normalizeAnalysisData({}), loading: false }))).toContain('本章暂无叙事状态数据')
  })

  it('五个分组各自渲染并带计数', () => {
    const data = normalizeAnalysisData({
      narrative_state: {
        promises: [{ id: 'p1', title: '会回来', status: 'open', promise_type: 'promise', priority: 'high', owner_character_name: '她', source_chapter_number: 3 }],
        timeline_events: [{ id: 'e1', title: '离家', event_type: '出发', location: '小镇', actor_names: ['他'] }],
        relationship_graph: { nodes: [], edges: [{ source: '他', target: '她', delta: -2, reason: '不辞而别' }] },
        causal_links: [{ cause: '信', event: '离开', effect: '寻找', importance: 4, reversible: true }],
      },
      consistency_audit: {
        summary: { total: 1, critical: 1, high: 0, medium: 0, low: 0 },
        issues: [{ severity: 'critical', issue_type: '时间线', title: '同一天出现两次', character_name: '她', reference_chapter_number: 2 }],
      },
    })
    const html = renderToStaticMarkup(h(NarrativeStatePanel, { data, loading: false }))
    for (const label of ['承诺 / 伏笔', '时间轴事件', '关系变化', '因果链', '一致性审计']) expect(html).toContain(label)
    expect(html).toContain('会回来')
    expect(html).toContain('高优')
    expect(html).toContain('第3章埋设')
    expect(html).toContain('-2')
    expect(html).toContain('可逆')
    expect(html).toContain('严重 1')
    expect(html).toContain('同一天出现两次')
    expect((html.match(/<details open=""/g) ?? []).length).toBe(5)
  })
})

const PAYLOAD = {
  chapter_id: 'c1', analyzed: true, is_stale: false,
  analysis: { id: 'x', chapter_id: 'c1', annotations: [], character_states: [{ character_name: '林尘', state_after: '决意下山' }], locations: ['青峰山'] },
  digest: { chapter_id: 'c1', summary: '林尘拿到玉佩', end_state: '林尘在山脚', source: 'author', suggestion: { summary: 'AI 的新摘要', end_state: '' }, stale: false },
  state_changes: [
    { signal_type: 'life_state', label: '生死', character_name: '林长老', signal_value: 'dead', evidence: '气绝' },
    { signal_type: 'realm', label: '境界', character_name: '林尘', signal_key: '炼气五层', signal_value: 'current' },
  ],
  task: { status: 'completed', message: null },
}

describe('ChapterArchivePanel', () => {
  const base = { chapterId: 'c1', loading: false, hasContent: true, analyzing: false, onAnalyze: () => undefined, onChanged: () => undefined }

  it('没分析过：提示并给分析按钮', () => {
    const html = renderToStaticMarkup(h(ChapterArchivePanel, { ...base, data: null }))
    expect(html).toContain('本章还没分析')
    expect(html).toContain('分析本章')
  })

  it('档案 / 作者版本 / AI 建议 / 状态变化 / 出场人物', () => {
    const html = renderToStaticMarkup(h(ChapterArchivePanel, { ...base, data: normalizeAnalysisData(PAYLOAD) }))
    expect(html).toContain('林尘拿到玉佩')
    expect(html).toContain('林尘在山脚')
    expect(html).toContain('作者版本')
    expect(html).toContain('AI 重新分析的结果')
    expect(html).toContain('林长老 · 生死：死亡')
    expect(html).toContain('林尘 · 境界：炼气五层')
    expect(html).toContain('决意下山')
    expect(html).toContain('青峰山')
  })

  it('失败 / 过期给醒目提示和重新分析', () => {
    const failed = renderToStaticMarkup(h(ChapterArchivePanel, {
      ...base, data: normalizeAnalysisData({ ...PAYLOAD, task: { status: 'failed', message: '输出被 Max Tokens 截断' } }),
    }))
    expect(failed).toContain('最近一次分析失败')
    expect(failed).toContain('输出被 Max Tokens 截断')
    expect(failed).toContain('之前的分析结果仍在用')
    expect(failed).toContain('重新分析')
    const stale = renderToStaticMarkup(h(ChapterArchivePanel, { ...base, data: normalizeAnalysisData({ ...PAYLOAD, is_stale: true }) }))
    expect(stale).toContain('正文在分析之后改过')
  })
})

describe('分析状态点', () => {
  it('各状态有说明文字', () => {
    expect(renderToStaticMarkup(h(AnalysisStatusDot, { status: 'ok' }))).toContain('已分析')
    expect(renderToStaticMarkup(h(AnalysisStatusDot, { status: 'failed', message: '截断' }))).toContain('最近一次分析失败：截断')
    expect(renderToStaticMarkup(h(AnalysisStatusDot, { status: 'missing' }))).toContain('还没分析')
    expect(renderToStaticMarkup(h(AnalysisStatusDot, { status: 'running' }))).toContain('animate-spin')
  })

  it('状态变化的说明', () => {
    expect(describeStateChange({ signal_type: 'item', label: '物品', character_name: '林尘', signal_key: '玄铁剑', signal_value: 'gained' }))
      .toBe('林尘 · 物品：获得 玄铁剑')
    expect(describeStateChange({ signal_type: 'story_time', label: '故事时间', signal_key: '深秋', signal_value: 'current' }))
      .toBe('故事时间：深秋')
  })
})
