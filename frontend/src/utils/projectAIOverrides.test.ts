import { describe, expect, it } from 'vitest'
import { OVERRIDE_KEYS, countActiveOverrides, emptyOverrides, modelChipLabel, normalizeOverrides } from './projectAIOverrides'

describe('projectAIOverrides', () => {
  it('emptyOverrides 九个字段全部为 null，计数为 0', () => {
    const o = emptyOverrides()
    expect(Object.keys(o).sort()).toEqual([...OVERRIDE_KEYS].sort())
    expect(Object.values(o).every((v) => v === null)).toBe(true)
    expect(countActiveOverrides(o)).toBe(0)
    expect(countActiveOverrides(null)).toBe(0)
  })

  it('countActiveOverrides 只数非 null（false / 0 也算覆盖）', () => {
    expect(countActiveOverrides({ llm_model: 'm', reasoning_enabled: false, temperature: 0 })).toBe(3)
  })

  it('normalizeOverrides：模型名裁空白、空串 → null，缺失键补 null，NaN → null', () => {
    const n = normalizeOverrides({ llm_model: '  gpt-x ', temperature: Number.NaN, max_tokens: 8000 })
    expect(n.llm_model).toBe('gpt-x')
    expect(n.temperature).toBeNull()
    expect(n.max_tokens).toBe(8000)
    expect(n.top_p).toBeNull()
    expect(normalizeOverrides({ llm_model: '   ' }).llm_model).toBeNull()
  })

  it('normalizeOverrides：本项目关闭思考时清掉强度与预算；跟随全局时保留强度', () => {
    const off = normalizeOverrides({ reasoning_enabled: false, reasoning_effort: 'high', thinking_budget_tokens: 4096 })
    expect(off).toMatchObject({ reasoning_enabled: false, reasoning_effort: null, thinking_budget_tokens: null })
    const follow = normalizeOverrides({ reasoning_enabled: null, reasoning_effort: 'high' })
    expect(follow.reasoning_effort).toBe('high')
  })

  it('modelChipLabel：有模型显示模型名，否则提示未选择', () => {
    expect(modelChipLabel({ llm_model: 'claude-3' })).toBe('claude-3')
    expect(modelChipLabel({ llm_model: '' })).toBe('未选择模型')
    expect(modelChipLabel(null)).toBe('未选择模型')
  })
})
