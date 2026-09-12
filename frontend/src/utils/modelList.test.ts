import { describe, expect, it } from 'vitest'
import type { AIModelOption } from '@/types'
import { displayName, filterModels, groupModels } from './modelList'

const m = (value: string, label = value): AIModelOption => ({ value, label, description: '' })

describe('filterModels', () => {
  const models = [m('deepseek-ai/deepseek-v4-flash'), m('openai/gpt-4o', 'GPT-4o'), m('claude-sonnet-4-5')]

  it('空查询返回全部', () => {
    expect(filterModels(models, '   ')).toEqual(models)
  })

  it('大小写不敏感子串匹配 value 或 label', () => {
    expect(filterModels(models, 'FLASH').map((x) => x.value)).toEqual(['deepseek-ai/deepseek-v4-flash'])
    expect(filterModels(models, 'gpt-4O').map((x) => x.value)).toEqual(['openai/gpt-4o'])
    expect(filterModels(models, 'nope')).toEqual([])
  })
})

describe('groupModels', () => {
  it('少于 8 个不分组', () => {
    const models = [m('a/x'), m('a/y'), m('b/z')]
    expect(groupModels(models)).toEqual([{ group: null, items: models }])
  })

  it('过半带斜杠时按前缀分组，保持首次出现顺序，无斜杠的归入「其他」', () => {
    const models = [
      m('deepseek-ai/v4'), m('openai/gpt-4o'), m('deepseek-ai/v3'), m('openai/o3'),
      m('anthropic/claude'), m('local-model'), m('openai/gpt-5'), m('deepseek-ai/r1'), m('qwen/qwen3'),
    ]
    const groups = groupModels(models)
    expect(groups.map((g) => g.group)).toEqual(['deepseek-ai', 'openai', 'anthropic', '其他', 'qwen'])
    expect(groups[0].items.map((x) => x.value)).toEqual(['deepseek-ai/v4', 'deepseek-ai/v3', 'deepseek-ai/r1'])
    expect(groups[3].items.map((x) => x.value)).toEqual(['local-model'])
  })

  it('斜杠占少数时不分组', () => {
    const models = [m('a/x'), m('b'), m('c'), m('d'), m('e'), m('f'), m('g'), m('h')]
    expect(groupModels(models)).toHaveLength(1)
    expect(groupModels(models)[0].group).toBeNull()
  })
})

describe('displayName', () => {
  it('分组内去掉前缀，不分组显示 label（无 label 则 value）', () => {
    expect(displayName(m('deepseek-ai/deepseek-v4-flash'), 'deepseek-ai')).toBe('deepseek-v4-flash')
    expect(displayName(m('openai/gpt-4o', 'GPT-4o'), null)).toBe('GPT-4o')
    expect(displayName(m('local-model', ''), '其他')).toBe('local-model')
  })
})
