import { describe, expect, it } from 'vitest'
import { ALL_EFFORTS, EFFORT_LEVELS, EFFORT_TO_BUDGET, autoBudget } from './aiParams'

describe('aiParams', () => {
  it('autoBudget 按档位换算，并夹到 max_tokens - 1', () => {
    expect(autoBudget('low', 100000)).toBe(4096)
    expect(autoBudget('medium', 4096)).toBe(4095)
  })

  it('autoBudget：max_tokens 太小无法满足 ≥1024 时返回 null', () => {
    expect(autoBudget('high', 1000)).toBeNull()
    expect(autoBudget('none', 1025)).toBe(1024)
  })

  it('简单档位是全部档位的子集，且每个档位都有 ≥1024 的预算映射', () => {
    const all = new Set(ALL_EFFORTS.map((e) => e.value))
    for (const l of EFFORT_LEVELS) expect(all.has(l.value)).toBe(true)
    for (const e of ALL_EFFORTS) expect(EFFORT_TO_BUDGET[e.value]).toBeGreaterThanOrEqual(1024)
  })
})
