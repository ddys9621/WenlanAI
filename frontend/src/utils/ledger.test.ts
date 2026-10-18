import { describe, expect, it } from 'vitest'
import type { StateCorrectionCreate, TimelineItem } from '@/types/ledger'
import { correctionOption, describeSignal, formatChars, groupTimeline, lifeLabel, lockedSummary, validateCorrection } from './ledger'

const form = (over: Partial<StateCorrectionCreate>): StateCorrectionCreate => ({
  character_name: '林长老', chapter_number: 2, signal_type: 'life_state', signal_value: 'survived', ...over,
})

describe('作者修正表单校验', () => {
  it('生死只需选状态', () => {
    expect(validateCorrection(form({}))).toBeNull()
    expect(validateCorrection(form({ signal_value: '飞升' }))).toContain('生死')
  })

  it('境界 / 位置等必须写内容', () => {
    expect(validateCorrection(form({ signal_type: 'realm', signal_value: 'current' }))).toContain('境界')
    expect(validateCorrection(form({ signal_type: 'realm', signal_value: 'current', signal_key: '筑基初期' }))).toBeNull()
    expect(validateCorrection(form({ signal_type: 'location', signal_value: 'current', signal_key: '  ' }))).toContain('地点')
  })

  it('人物与章号', () => {
    expect(validateCorrection(form({ character_name: ' ' }))).toBe('请填写人物')
    expect(validateCorrection(form({ chapter_number: 0 }))).toBe('章号应是正整数')
    // 故事时间不针对人物
    expect(validateCorrection(form({ character_name: '', signal_type: 'story_time', signal_value: 'current', signal_key: '深秋' }))).toBeNull()
  })

  it('选项表里每种类型都有状态可选', () => {
    expect(correctionOption('item').values.map((v) => v.value)).toEqual(['gained', 'lost'])
    expect(correctionOption('story_time').needsCharacter).toBe(false)
  })
})

describe('标签与分组', () => {
  it('作者改过的字段', () => {
    expect(lockedSummary({ locked_fields: [] })).toBe('')
    expect(lockedSummary({ locked_fields: ['*'] })).toBe('作者登记')
    expect(lockedSummary({ locked_fields: ['title', 'priority'] })).toBe('作者改过：标题、优先级')
  })

  it('生死标签', () => {
    expect(lifeLabel('dead')).toBe('已死亡')
    expect(lifeLabel(null)).toBe('在世')
  })

  it('变化记录说中文', () => {
    expect(describeSignal({ label: '生死', signal_key: null, signal_value: 'survived' })).toBe('生死：生还')
    expect(describeSignal({ label: '境界', signal_key: '炼气五层', signal_value: 'current' })).toBe('境界：炼气五层')
    expect(describeSignal({ label: '物品', signal_key: '玄铁剑', signal_value: 'gained' })).toBe('物品：获得 玄铁剑')
  })

  it('时间线按章分组，同章事件在前', () => {
    const items = [
      { kind: 'causal', id: 'c1', chapter_number: 3, actors: [], targets: [] },
      { kind: 'event', id: 'e2', chapter_number: 5, actors: [], targets: [] },
      { kind: 'event', id: 'e1', chapter_number: 3, actors: [], targets: [] },
    ] as TimelineItem[]
    expect(groupTimeline(items).map((g) => [g.chapter, g.items.map((i) => i.id)])).toEqual([[3, ['e1', 'c1']], [5, ['e2']]])
  })

  it('字数显示', () => {
    expect(formatChars(800)).toBe('800 字')
    expect(formatChars(12500)).toBe('1.3 万字')
  })
})
