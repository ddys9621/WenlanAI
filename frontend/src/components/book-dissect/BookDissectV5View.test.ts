import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { BookDissectChapterCard, BookDissectStoryArc } from '@/types'
import type { MethodologyData, ReferencePackDetail, SkeletonData } from '@/types/reference_pack'
import {
  ArcList,
  BookDissectV5View,
  ChapterCardDetail,
  CharacterFunctionsTab,
  SkeletonTab,
  StyleTab,
  UnitsSummary,
} from './BookDissectV5View'
import { CHAPTER_ROLE_LABEL, chapterRange, formatMetric, pct, renderValue } from './format'

/** 拆书视图：服务端渲染冒烟（无 jsdom，只验证不抛 + 关键内容在场） */

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

  it('章在单元里的位置用 开启 / 推进 / 转折 / 收束', () => {
    expect(Object.values(CHAPTER_ROLE_LABEL)).toEqual(['开启', '推进', '转折', '收束', '过渡'])
  })
})

describe('SkeletonTab', () => {
  const skeleton: SkeletonData = {
    genre_tag: '玄幻',
    premise: '杂役少年一步步看清宗门',
    main_plot: '林七为了给妹妹治病去争内门名额……',
    golden_finger: { what: '过目不忘', how_it_works: '看一遍就会', limits: '记多了头疼', evolution: ['一阶', '二阶'] },
    selling_points: ['小人物靠脑子翻身'],
    volumes: [{ title: '入门', summary: '从外门到内门', goal: '进内门', climax: '#3 比武', chapter_start: 1, chapter_end: 30,
                arc_start: 1, arc_end: 6, threads: ['师徒线：从戒备到信任'], origin: 'llm' }],
    high_points: [{ volume: '入门', arcs: '#3', setup: '被嘲笑', trigger: '比武', result: '破格进内门' }],
  }
  const methodology: MethodologyData = { unit_design: { pattern: '一件事 3-5 章', writing_tips: '起因落在主角的选择上' } }

  it('骨架 + 分卷 + 高光在场，写法手册默认折叠', () => {
    const html = renderToStaticMarkup(h(SkeletonTab, { skeleton, methodology, structure: null }))
    for (const s of ['杂役少年一步步看清宗门', '全书主线', '限制：记多了头疼', '演进：一阶 → 二阶', '小人物靠脑子翻身',
      '分卷', '入门', '第 1-30 章', '剧情单元 #1-#6', '师徒线：从戒备到信任', '破格进内门', '写法手册']) {
      expect(html).toContain(s)
    }
    expect(html).not.toContain('起因落在主角的选择上')
    expect(html).not.toContain('金手指')
  })

  it('主角没有特殊能力时不显示这一栏', () => {
    const html = renderToStaticMarkup(h(SkeletonTab, { skeleton: { ...skeleton, golden_finger: '无' }, methodology: null, structure: null }))
    expect(html).not.toContain('主角特殊能力')
  })

  it('无骨架时提示缺失并展开写法手册', () => {
    const html = renderToStaticMarkup(h(SkeletonTab, { skeleton: null, methodology, structure: null }))
    expect(html).toContain('未生成「全书骨架」')
    expect(html).toContain('剧情单元设计')
    expect(html).toContain('起因落在主角的选择上')
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
    for (const s of ['冷硬快', '短句为主，多用动作', '平均句长（字）', '31%', '章末钩子', '第 12 章', '导入到项目写作风格库']) {
      expect(html).toContain(s)
    }
  })

  it('空 style 给缺失提示', () => {
    expect(renderToStaticMarkup(h(StyleTab, { style: null, sourceBookTitle: 'x' }))).toContain('未生成「文风指纹」')
  })
})

describe('CharacterFunctionsTab', () => {
  it('主角（核心优势 / 分卷成长）/ 盟友 / 对手 / 功能位', () => {
    const html = renderToStaticMarkup(
      h(CharacterFunctionsTab, {
        data: {
          protagonist: { name: '林七', persona: '隐忍', advantage: '过目不忘', growth_track: [{ volume: '入门', state: '外门杂役' }] },
          allies: [{ name: '小胖', function_role: '搞笑担当', technique: '每次紧张时插科打诨' }],
          antagonists: [{ name: '王家', tier: '卷反派', outcome: '被灭' }],
          function_slots: [{ slot: '引路人', how_used: '第 5 章出现，点破身世' }],
        },
      }),
    )
    for (const s of ['林七', '核心优势', '过目不忘', '入门', '外门杂役', '搞笑担当', '卷反派', '引路人']) expect(html).toContain(s)
  })
})

describe('UnitsSummary / ArcList', () => {
  const arcs: BookDissectStoryArc[] = [
    {
      arc_index: 1, start_chapter: 1, end_chapter: 4, title: '入门试炼', function: '立足', boundary_reason: '试炼结束',
      story: '报名受辱，看穿规矩漏洞翻盘', structure: '起因(1) -> 推进(2) -> 转折(3) -> 收束(4)', approach: '靠观察规矩',
      turn: '进了内门，也结了仇', emotion_curve: '压→放', payoff: '当众拆穿刁难', payoff_type: '智斗破局',
      character_changes: '', gains_costs: '', foreshadowing: '',
      chapter_roles: { '1': 'open', '2': 'advance', '3': 'turn', '4': 'close' }, tension_peak_chapter: 3, origin: 'llm',
    },
    {
      arc_index: 2, start_chapter: 5, end_chapter: 6, title: '师门日常', function: '缓和', boundary_reason: '', story: '', structure: '',
      approach: '', turn: '', emotion_curve: '', payoff: '', payoff_type: '缓和过渡', character_changes: '',
      gains_costs: '', foreshadowing: '', chapter_roles: {}, tension_peak_chapter: null, origin: 'fallback',
    },
  ]

  it('聚合总览显示单元数 / 强弱交替 / 兑现方式分布', () => {
    const html = renderToStaticMarkup(
      h(UnitsSummary, { data: { arc_count: 2, avg_arc_length: 3, payoff_type_distribution: { 智斗破局: 1, 缓和过渡: 1 },
        payoff_density: '约每 3.0 章一件事', unit_rhythm: '强弱', relief_after_strong: 1 } }),
    )
    for (const s of ['剧情单元总览', '约每 3.0 章一件事', '智斗破局', '平均长度（章）', '单元强弱', '100%']) expect(html).toContain(s)
  })

  it('第一个单元默认展开：经过 / 主角靠 / 结束时 / 章内位置', () => {
    const html = renderToStaticMarkup(h(ArcList, { arcs }))
    for (const s of ['剧情单元', '入门试炼', '第 1-4 章', '报名受辱', '靠观察规矩', '进了内门，也结了仇', '3·转折', '规则切分']) {
      expect(html).toContain(s)
    }
    expect(html).not.toContain('缓和</span>')    // 第二个单元折叠：其作用文案不出现
  })
})

describe('ChapterCardDetail', () => {
  it('整卡字段', () => {
    const card: BookDissectChapterCard = {
      chapter_number: 7, title: '比武', outline: '林七登台，一招制敌。', function_tags: ['战斗', '爽点兑现'], pace: '快', tension: 5,
      emotion_tone: '热血', ending_hook_type: '危机', ending_hook_text: '看台上，一双眼睛盯住了他。', payoff_points: ['一招制敌'],
      highlights: ['先抑后扬'], characters: ['林七', '王虎'], protagonist_delta: '炼气三层→四层', new_settings: ['宗门大比规则'],
      word_count: 3200, truncated_input: false, extraction_status: 'success', extraction_error: null,
    }
    const html = renderToStaticMarkup(h(ChapterCardDetail, { card }))
    for (const s of ['第 7 章', '林七登台', '看台上', '高点 / 兑现', '一招制敌', '先抑后扬', '炼气三层→四层', '宗门大比规则', '3,200 字']) {
      expect(html).toContain(s)
    }
  })
})

describe('BookDissectV5View', () => {
  it('参考包缺失：tab 栏全在，维度 tab 标 (无)，骨架 tab 给占位', () => {
    const html = renderToStaticMarkup(h(BookDissectV5View, { taskId: 't1', pack: null }))
    for (const s of ['全书骨架', '剧情单元', '逐章拆书表', '文风指纹', '人物功能谱']) expect(html).toContain(s)
    expect(html).not.toContain('桥段')
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
