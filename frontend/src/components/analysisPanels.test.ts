import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { MemoryAnnotation } from '@/utils/annotationSegments'
import { normalizeAnalysisData } from '@/utils/chapterAnalysis'
import AnnotatedText from './AnnotatedText'
import MemorySidebar from './MemorySidebar'
import { NarrativeStatePanel } from './chapters/NarrativeStatePanel'

/** 去 antd 后的三块分析面板：服务端渲染冒烟（无 jsdom，只验证不抛错 + 关键内容在场） */

const CONTENT = '他推开门，屋里没人。桌上留着一封信，信封上是她的字。'
const ann = (over: Partial<MemoryAnnotation>): MemoryAnnotation => ({
  id: 'a1', type: 'hook', title: '一封信', content: '桌上的信是谁留下的', importance: 0.8, position: 10, length: 8,
  tags: ['悬念'], metadata: {}, ...over,
})

describe('MemorySidebar', () => {
  it('空标注给提示', () => {
    expect(renderToStaticMarkup(h(MemorySidebar, { annotations: [] }))).toContain('暂无分析数据')
  })

  it('按类型分组、概览计数、伏笔状态标签、选中态', () => {
    const html = renderToStaticMarkup(h(MemorySidebar, {
      annotations: [
        ann({}),
        ann({ id: 'a2', type: 'foreshadow', title: '字迹', metadata: { foreshadowType: 'planted', strength: 7 } }),
        ann({ id: 'a3', type: 'character_event', title: '她离开' }),
      ],
      activeAnnotationId: 'a2',
    }))
    expect(html).toContain('分析概览')
    expect(html).toContain('一封信')
    expect(html).toContain('已埋下')
    expect(html).toContain('强度: 7/10')
    expect(html).toContain('ring-brand/30') // 选中卡片
    // 角色事件分组默认收起，其它默认展开（原生 details）
    expect((html.match(/<details open=""/g) ?? []).length).toBe(2)
    expect((html.match(/<details class="group"/g) ?? []).length).toBe(1)
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
