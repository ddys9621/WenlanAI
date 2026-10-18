import { describe, expect, it } from 'vitest'
import { mergeUntouched } from './draftMerge'

describe('mergeUntouched', () => {
  it('作者没改过的字段换成新值，正在改的字段保留作者输入', () => {
    const base = { rules: '灵气复苏', theme: '复仇' }
    const draft = { rules: '灵气复苏', theme: '作者正在改的主题' }
    const next = { rules: '灵气复苏，修士分九境', theme: '复仇与救赎' }
    expect(mergeUntouched(draft, base, next)).toEqual({ rules: '灵气复苏，修士分九境', theme: '作者正在改的主题' })
  })

  it('没有任何改动时就是新值', () => {
    const base = { a: '1', b: 2 }
    expect(mergeUntouched({ ...base }, base, { a: '3', b: 4 })).toEqual({ a: '3', b: 4 })
  })
})
