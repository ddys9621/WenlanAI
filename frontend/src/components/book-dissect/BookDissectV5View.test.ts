import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { describe, expect, it } from 'vitest'

import type { BookDissectChapterCard, BookDissectStoryArc } from '@/types'
import type { ReferencePackDetail } from '@/types/reference_pack'
import {
  ArcList,
  BookDissectV5View,
  BridgesSummary,
  ChapterCardDetail,
  CharacterFunctionsTab,
  SkeletonTab,
  StyleTab,
} from './BookDissectV5View'
import { LegacyPackNotice } from './LegacyPackNotice'
import { chapterRange, formatMetric, pct, renderValue } from './format'

/** 拆书 V5 视图：服务端渲染冒烟（无 jsdom，只验证不抛 + 关键内容在场） */

const pack = (over: Partial<ReferencePackDetail> = {}): ReferencePackDetail => ({
  id: 'pack-1',
  task_id: 'task-1',
  user_id: 'u1',
  source_book_title: '测试书',
  status: 'ready',
  generated_dimensions: ['synopsis', 'style'],
  pipeline_version: 5,
  error_message: null,
  attached_project_count: 0,
  created_at: '2026-09-14T00:00:00Z',
  updated_at: '2026-09-14T00:00:00Z',
  synopsis: null,
  bridges: null,
  style: null,
  character_archive: null,
  methodology: null,
  structure: null,
  ...over,
})

describe('format', () => {
  it('嵌套值扁平化，不出现 [object Object]', () => {
    expect(renderValue({ a: 1, b: ['x', { c: 'y' }] })).toBe('a: 1，b: x、c: y')
    expect(renderValue(null)).toBe('')
  })

  it('比例 / 区间 / 指标格式化', () => {
    expect(pct(0.374)).toBe('37%')
    expect(pct('x')).toBe('—')
    expect(chapterRange(3, 7)).toBe('第 3-7 章')
    expect(chapterRange(5, 5)).toBe('第 5 章')
    expect(formatMetric('dialogue_char_ratio', 0.42)).toBe('42%')
    expect(formatMetric('avg_sentence_len', 18.26)).toBe('18.3')
    expect(formatMetric('sample_chars', 12000)).toBe('12000')
  })
})

describe('SkeletonTab', () => {
  const skeleton = {
    genre_tag: '玄幻',
    one_line_premise: '废柴少年得神秘戒指逆袭',
    golden_finger: { what: '古戒', how_it_works: '吞噬灵气', evolution: ['一阶', '二阶'] },
    stages: [{ title: '崛起', core_conflict: '家族打压', chapter_start: 1, chapter_end: 30, arc_start: 1, arc_end: 6, origin: 'llm' }],
    top_payoffs: [{ stage: '崛起', arcs: '3', buildup: '被嘲笑', trigger: '比武', reward: '一拳打飞' }],
  }
  const methodology = { golden_finger_pattern: { type: '吞噬型', writing_tips: '每三章展示一次新用法' } }

  it('骨架 + 阶段 + 爽点在场，写法手册默认折叠', () => {
    const html = renderToStaticMarkup(h(SkeletonTab, { skeleton, methodology, structure: null }))
    expect(html).toContain('废柴少年得神秘戒指逆袭')
    expect(html).toContain('演化：一阶 → 二阶')
    expect(html).toContain('崛起')
    expect(html).toContain('第 1-30 章')
    expect(html).toContain('一拳打飞')
    expect(html).toContain('写法手册')
    expect(html).not.toContain('每三章展示一次新用法')
  })

  it('无骨架时提示缺失并展开写法手册', () => {
    const html = renderToStaticMarkup(h(SkeletonTab, { skeleton: null, methodology, structure: null }))
    expect(html).toContain('未生成「全书骨架」')
    expect(html).toContain('每三章展示一次新用法')
  })

  it('三者皆空给整体缺失提示', () => {
    expect(renderToStaticMarkup(h(SkeletonTab, { skeleton: null, methodology: null, structure: null }))).toContain('未生成「全书骨架」')
  })
})

describe('StyleTab', () => {
  it('prompt / 指标 / 例句', () => {
    const html = renderToStaticMarkup(
      h(StyleTab, {
        sourceBookTitle: '测试书',
        style: {
          name: '冷硬快',
          prompt_content: '短句为主，多用动作',
          traits: ['短句', '少形容词'],
          metrics: { avg_sentence_len: 14.2, dialogue_char_ratio: 0.31, sentence_len_dist: { '0-10': 0.4, '11-20': 0.6 } },
          examples: [{ kind: 'ending_hook', chapter: 12, text: '门外，传来了脚步声。' }],
        },
      }),
    )
    expect(html).toContain('冷硬快')
    expect(html).toContain('短句为主，多用动作')
    expect(html).toContain('平均句长（字）')
    expect(html).toContain('31%')
    expect(html).toContain('章末钩子')
    expect(html).toContain('第 12 章')
    expect(html).toContain('导入到项目写作风格库')
  })

  it('空 style 给缺失提示', () => {
    expect(renderToStaticMarkup(h(StyleTab, { style: null, sourceBookTitle: 'x' }))).toContain('未生成「文风指纹」')
  })
})

describe('CharacterFunctionsTab', () => {
  it('主角 / 盟友 / 对手 / 功能位', () => {
    const html = renderToStaticMarkup(
      h(CharacterFunctionsTab, {
        data: {
          protagonist: { name: '林七', persona: '隐忍', growth_track: [{ stage: '崛起', state: '炼气' }] },
          allies: [{ name: '小胖', function_role: '搞笑担当', technique: '每次紧张时插科打诨' }],
          antagonists: [{ name: '王家', tier: '阶段反派', outcome: '被灭' }],
          function_slots: [{ slot: '引路人', how_used: '第 5 章出现，点破金手指来历' }],
        },
      }),
    )
    for (const s of ['林七', '炼气', '搞笑担当', '阶段反派', '引路人']) expect(html).toContain(s)
  })
})

describe('BridgesSummary / ArcList', () => {
  const arcs: BookDissectStoryArc[] = [
    {
      arc_index: 1, start_chapter: 1, end_chapter: 4, title: '入门试炼', function: '立足', boundary_reason: '试炼结束',
      structure: '起承爽收', protagonist_chain: '报名→受辱→翻盘', emotion_curve: '压→爆', payoff: '一招制敌', payoff_type: '打脸',
      golden_finger_usage: '首次觉醒', character_changes: '', gains_costs: '', foreshadowing: '',
      chapter_roles: { '1': 'intro', '2': 'build', '3': 'payoff', '4': 'aftermath' }, tension_peak_chapter: 3, origin: 'llm',
    },
    {
      arc_index: 2, start_chapter: 5, end_chapter: 6, title: '善后', function: '过渡', boundary_reason: '', structure: '',
      protagonist_chain: '', emotion_curve: '', payoff: '', payoff_type: '无强爽点', golden_finger_usage: '无', character_changes: '',
      gains_costs: '', foreshadowing: '', chapter_roles: {}, tension_peak_chapter: null, origin: 'fallback',
    },
  ]

  it('聚合总览显示单元数与爽点类型分布', () => {
    const html = renderToStaticMarkup(
      h(BridgesSummary, { data: { arc_count: 2, avg_arc_length: 3, payoff_type_distribution: { 打脸: 1, 无强爽点: 1 }, payoff_density: '约每 3 章 1 个情节单元' } }),
    )
    expect(html).toContain('约每 3 章 1 个情节单元')
    expect(html).toContain('打脸')
    expect(html).toContain('平均长度（章）')
  })

  it('第一个单元默认展开：功能 / 章内分工 / 张力峰值章', () => {
    const html = renderToStaticMarkup(h(ArcList, { arcs }))
    expect(html).toContain('入门试炼')
    expect(html).toContain('第 1-4 章')
    expect(html).toContain('报名→受辱→翻盘')
    expect(html).toContain('3·爽')
    expect(html).toContain('规则切分')
    // 第二个单元折叠：其 function 文案不出现
    expect(html).not.toContain('过渡</span>')
  })
})

describe('ChapterCardDetail', () => {
  it('整卡字段', () => {
    const card: BookDissectChapterCard = {
      chapter_number: 7, title: '比武', outline: '林七登台，一招制敌。', function_tags: ['打脸', '爽点兑现'], pace: '快', tension: 5,
      emotion_tone: '热血', ending_hook_type: '危机', ending_hook_text: '看台上，一双眼睛盯住了他。', payoff_points: ['一招制敌'],
      highlights: ['先抑后扬'], characters: ['林七', '王虎'], protagonist_delta: '炼气三层→四层', new_settings: ['宗门大比规则'],
      word_count: 3200, truncated_input: false, extraction_status: 'success', extraction_error: null,
    }
    const html = renderToStaticMarkup(h(ChapterCardDetail, { card }))
    for (const s of ['第 7 章', '林七登台', '看台上', '一招制敌', '先抑后扬', '炼气三层→四层', '宗门大比规则', '3,200 字']) expect(html).toContain(s)
  })
})

describe('BookDissectV5View', () => {
  it('参考包缺失：tab 栏全在，维度 tab 标 (无)，骨架 tab 给占位', () => {
    const html = renderToStaticMarkup(h(BookDissectV5View, { taskId: 't1', pack: null }))
    for (const s of ['全书骨架', '桥段库', '逐章拆书表', '文风指纹', '人物功能谱']) expect(html).toContain(s)
    expect(html).toContain('(无)')
    expect(html).toContain('未生成「参考包」')
  })

  it('参考包加载中不标 (无)', () => {
    const html = renderToStaticMarkup(h(BookDissectV5View, { taskId: 't1', pack: null, packLoading: true }))
    expect(html).not.toContain('(无)')
    expect(html).toContain('正在加载参考包')
  })

  it('initialTab=cards 首屏渲染拆书表（SSR 无 effect，显示加载态）', () => {
    const html = renderToStaticMarkup(h(BookDissectV5View, { taskId: 't1', pack: pack(), initialTab: 'cards' }))
    expect(html).toContain('加载拆书卡')
  })
})

describe('LegacyPackNotice', () => {
  it('横幅 + synopsis 默认展开 + methodology 折叠只显字段数', () => {
    const html = renderToStaticMarkup(
      h(StaticRouter, { location: '/reference-packs/p1' }, h(LegacyPackNotice, {
        pack: pack({ pipeline_version: 2, synopsis: { genre: '都市', core_premise: '重生回到 2008' }, methodology: { golden_finger_pattern: { type: '先知' } } }),
      })),
    )
    expect(html).toContain('旧版流水线（V2）')
    expect(html).toContain('去重新抽取')
    expect(html).toContain('重生回到 2008')
    expect(html).toContain('1 个字段')
    expect(html).not.toContain('先知')
  })

  it('无任何维度时提示', () => {
    const html = renderToStaticMarkup(h(StaticRouter, { location: '/reference-packs/p1' }, h(LegacyPackNotice, { pack: pack({ pipeline_version: 2 }) })))
    expect(html).toContain('没有任何可展示的维度内容')
  })
})
