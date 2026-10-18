import { describe, expect, it } from 'vitest'
import type { AdherenceReport } from '@/types/writing'
import { adherenceVerdict, candidateApplyPreview, loadAutoAnalyze, saveAutoAnalyze, versionReasonLabel } from './writingFlow'

const report = (over: Partial<AdherenceReport>): AdherenceReport => ({ status: 'ok', passed: true, issues: [], unverified: [], ...over })

describe('adherenceVerdict', () => {
  it('通过 / 未通过 / 审校失败 / 未审校', () => {
    expect(adherenceVerdict(report({}))).toMatchObject({ tone: 'ok', label: '照章纲写了' })
    expect(adherenceVerdict(report({ passed: false, issues: ['漏写关键事件：下山', '没写到章末落点'] })))
      .toMatchObject({ tone: 'stale', label: '有 2 处偏离章纲' })
    expect(adherenceVerdict(report({ status: 'error', passed: null, message: '超时' })))
      .toMatchObject({ tone: 'muted', label: '审校没跑成' })
    expect(adherenceVerdict(null)).toMatchObject({ tone: 'muted', label: '未审校' })
  })
})

describe('versionReasonLabel', () => {
  it('翻译版本来源', () => {
    expect(versionReasonLabel('manual_edit')).toBe('手动修改前')
    expect(versionReasonLabel('adopt_candidate')).toBe('采用候选稿前')
    expect(versionReasonLabel('restore')).toBe('恢复旧版前')
    expect(versionReasonLabel('其他')).toBe('其他')
  })
})

describe('candidateApplyPreview', () => {
  const content = '第一段。\n\n第二段。'
  it('整章替换 / 接在末尾 / 替换选段 的采用后效果', () => {
    expect(candidateApplyPreview(content, { mode: 'replace_all', range_start: null, range_end: null, original_text: null }, '新稿')).toBe('新稿')
    expect(candidateApplyPreview(content, { mode: 'append', range_start: null, range_end: null, original_text: null }, '第三段。'))
      .toBe('第一段。\n\n第二段。\n\n第三段。')
    expect(candidateApplyPreview(content, { mode: 'replace_range', range_start: 6, range_end: 10, original_text: '第二段。' }, '改过的第二段。'))
      .toBe('第一段。\n\n改过的第二段。')
  })

  it('选段已对不上时返回 null（采用会被服务端拒绝）', () => {
    expect(candidateApplyPreview(content, { mode: 'replace_range', range_start: 0, range_end: 3, original_text: '不存在' }, 'x')).toBeNull()
  })
})

describe('「采用后自动分析本章」记住上次的勾选', () => {
  it('没存过默认不勾；存了按存的来；本机存储读写失败不抛错', () => {
    const saved = new Map<string, string>()
    const storage = { getItem: (k: string) => saved.get(k) ?? null, setItem: (k: string, v: string) => { saved.set(k, v) } }
    expect(loadAutoAnalyze(storage)).toBe(false)
    saveAutoAnalyze(true, storage)
    expect(loadAutoAnalyze(storage)).toBe(true)
    saveAutoAnalyze(false, storage)
    expect(loadAutoAnalyze(storage)).toBe(false)
    const denied = { getItem: (): string | null => { throw new Error('denied') }, setItem: () => { throw new Error('denied') } }
    expect(loadAutoAnalyze(denied)).toBe(false)
    expect(() => saveAutoAnalyze(true, denied)).not.toThrow()
    expect(loadAutoAnalyze(null)).toBe(false)
  })
})
