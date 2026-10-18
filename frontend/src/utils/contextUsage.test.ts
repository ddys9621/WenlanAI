import { describe, expect, it } from 'vitest'
import type { AssistantContextUsage } from '@/types/assistant'
import { formatTokens, parseWindowInput, usageTitle, usageTone, windowChoice } from './contextUsage'

const usage = (over: Partial<AssistantContextUsage> = {}): AssistantContextUsage => ({
  used: 87_400, limit: 128_000, reserve: 10_400, percent: 68, source: 'auto', model: 'deepseek-chat',
  parts: { system: 3_500, book: 400, summary: 1_200, goal: 300, history: 62_000, steps: 20_000 },
  history: { included: 45, total: 75, summarized: 30 }, compressed_steps: 0, will_compact: 0, ...over,
})

describe('formatTokens', () => {
  it('按 K / M 缩写', () => {
    expect(formatTokens(950)).toBe('950')
    expect(formatTokens(1_500)).toBe('1.5K')
    expect(formatTokens(87_400)).toBe('87K')
    expect(formatTokens(676_000)).toBe('676K')
    expect(formatTokens(1_000_000)).toBe('1M')
    expect(formatTokens(1_250_000)).toBe('1.3M')
  })
})

describe('usageTone', () => {
  it('七成起提醒，九成起告急', () => {
    expect(usageTone(68)).toBe('ok')
    expect(usageTone(70)).toBe('warn')
    expect(usageTone(90)).toBe('full')
  })
})

describe('usageTitle', () => {
  it('列出用量、上限来源、分项与历史压缩情况', () => {
    const text = usageTitle(usage())
    expect(text).toContain('约 87K / 128K token')
    expect(text).toContain('按模型 deepseek-chat')
    expect(text).toContain('近期对话 62K')
    expect(text).toContain('带入 45 条')
    expect(text).toContain('30 条已压成前情摘要')
    expect(text).not.toContain('没装下')
  })

  it('手动上限、没认出的模型、截掉的历史、压缩提示', () => {
    expect(usageTitle(usage({ source: 'manual' }))).toContain('你设的上限 128K')
    expect(usageTitle(usage({ source: 'fallback', model: 'm' }))).toContain('没认出模型「m」')
    expect(usageTitle(usage({ history: { included: 5, total: 12, summarized: 0 } }))).toContain('还有 7 条这次没装下')
    expect(usageTitle(usage({ will_compact: 8 }))).toContain('发送时会先把较早的 8 条对话压成前情摘要')
    expect(usageTitle(usage({ compressed_steps: 2 }))).toContain('2 步工具结果')
  })
})

describe('windowChoice / parseWindowInput', () => {
  it('空 = 自动，预设值直接选中，其他值算自定义', () => {
    expect(windowChoice(null, [32_000, 128_000])).toBe('')
    expect(windowChoice(128_000, [32_000, 128_000])).toBe('128000')
    expect(windowChoice(100_000, [32_000, 128_000])).toBe('custom')
  })

  it('自定义按 K 填，也认 K / M 后缀；格式不对或超出范围不收', () => {
    expect(parseWindowInput('100', 16_000, 2_000_000)).toBe(100_000)
    expect(parseWindowInput('256k', 16_000, 2_000_000)).toBe(256_000)
    expect(parseWindowInput('1.5M', 16_000, 2_000_000)).toBe(1_500_000)
    expect(parseWindowInput('8', 16_000, 2_000_000)).toBeNull()
    expect(parseWindowInput('abc', 16_000, 2_000_000)).toBeNull()
  })
})
