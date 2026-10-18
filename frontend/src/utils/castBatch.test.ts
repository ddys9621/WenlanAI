import { describe, expect, it } from 'vitest'
import { CAST_BATCH_LIMITS, castBatchTitle, clampCastCount } from './castBatch'

describe('castBatchTitle', () => {
  it('和后端任务标题一致，数量为 0 的一项不写', () => {
    expect(castBatchTitle(4, 1)).toBe('AI 批量生成：4 个人物 · 1 个组织')
    expect(castBatchTitle(3, 0)).toBe('AI 批量生成：3 个人物')
    expect(castBatchTitle(0, 2)).toBe('AI 批量生成：2 个组织')
  })
})

describe('clampCastCount', () => {
  it('取整并夹在 0 和上限之间，非数字当 0', () => {
    expect(clampCastCount('3', CAST_BATCH_LIMITS.characters)).toBe(3)
    expect(clampCastCount('12', CAST_BATCH_LIMITS.characters)).toBe(10)
    expect(clampCastCount('9', CAST_BATCH_LIMITS.organizations)).toBe(5)
    expect(clampCastCount('-2', 10)).toBe(0)
    expect(clampCastCount('2.7', 10)).toBe(2)
    expect(clampCastCount('', 10)).toBe(0)
    expect(clampCastCount('abc', 10)).toBe(0)
  })
})
