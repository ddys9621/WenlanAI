import { describe, expect, it } from 'vitest'
import type { AssistantPlan, AssistantQuestion } from '@/types/assistant'
import { mentionMember, memberTone, planConfirmTargets, planEntity, planLink, questionCardKey } from './cocreation'

describe('mentionMember', () => {
  it('在草稿开头加上 @成员，已有的提及换成新的', () => {
    expect(mentionMember('', '人物设计师')).toBe('@人物设计师 ')
    expect(mentionMember('女主再冷一点', '人物设计师')).toBe('@人物设计师 女主再冷一点')
    expect(mentionMember('@世界观设定师 设计门派', '人物设计师')).toBe('@人物设计师 设计门派')
  })

  it('选主编就去掉提及（主编默认发言）', () => {
    expect(mentionMember('@审校编辑 看看第三章', '主编')).toBe('看看第三章')
  })
})

describe('草案卡片', () => {
  const volumes: AssistantPlan = {
    kind: 'volumes', title: '分卷', volumes: [
      { id: 'v1', volume_number: 1, title: '雾起', chapter_start: 1, chapter_end: 20, summary: '', unit_count: 0 },
      { id: 'v2', volume_number: 2, title: '潮落', chapter_start: 21, chapter_end: 40, summary: '', unit_count: 0 },
    ],
  }
  const units: AssistantPlan = {
    kind: 'units', title: '单元', volume: {
      id: 'v1', volume_number: 1, title: '雾起', chapter_start: 1, chapter_end: 20, summary: '', unit_count: 2, units: [], threads: [],
    },
  }
  const outlines: AssistantPlan = {
    kind: 'outlines', title: '章纲', volume_id: 'v1', unit_index: 1,
    chapters: [{ id: 'c1', chapter_number: 1, title: '一', plot_points: '' }, { id: 'c2', chapter_number: 2, title: '二', plot_points: '' }],
  }

  it('确认的对象：卷纲草案确认卷，章纲草案确认章纲', () => {
    expect(planConfirmTargets(volumes)).toEqual({ volumeIds: ['v1', 'v2'], outlineIds: [] })
    expect(planConfirmTargets(units)).toEqual({ volumeIds: ['v1'], outlineIds: [] })
    expect(planConfirmTargets(outlines)).toEqual({ volumeIds: [], outlineIds: ['c1', 'c2'] })
  })

  it('刷新哪类页面数据、跳到谋篇的哪个页签', () => {
    expect(planEntity(volumes)).toBe('volume')
    expect(planEntity(outlines)).toBe('chapter_outline')
    expect(planLink(units)).toBe('outline/volumes')
    expect(planLink(outlines)).toBe('outline/chapters')
  })
})

describe('questionCardKey', () => {
  const ask = (...ids: string[]): AssistantQuestion[] =>
    ids.map((id) => ({ id, prompt: id, mode: 'single', options: [{ id: 'a', label: '甲' }, { id: 'b', label: '乙' }] }))

  it('同一轮运行先后两次提问（问题 id 不同）要换一张新卡：沿用旧卡读不到新问题的作答，整页白屏', () => {
    const first = questionCardKey({ id: 'run-1', question: { questions: ask('q1', 'q2', 'q3') } })
    const second = questionCardKey({ id: 'run-1', question: { questions: ask('world_style', 'origin_clarity', 'vortex_role') } })
    expect(second).not.toBe(first)
  })

  it('同一组问题保持同一张卡，作者已勾选的作答不丢', () => {
    const run = { id: 'run-1', question: { questions: ask('q1', 'q2') } }
    expect(questionCardKey({ ...run })).toBe(questionCardKey(run))
    expect(questionCardKey({ id: 'run-2', question: run.question })).not.toBe(questionCardKey(run))
  })
})

describe('memberTone', () => {
  it('已知颜色给对应样式，未知颜色回落中性色', () => {
    expect(memberTone('rose')).not.toBe(memberTone('unknown'))
    expect(memberTone('unknown')).toBe(memberTone('slate'))
  })
})
