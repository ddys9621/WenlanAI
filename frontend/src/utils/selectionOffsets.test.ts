import { describe, expect, it } from 'vitest'
import { resolveSelection } from './selectionOffsets'

const CONTENT = '林尘推开门。屋里黑漆漆的。林尘推开门，又关上。'

describe('resolveSelection', () => {
  it('DOM 给的位置与正文逐字对得上就直接用', () => {
    expect(resolveSelection(CONTENT, '屋里黑漆漆的', 6)).toEqual({ start: 6, end: 12, text: '屋里黑漆漆的' })
  })

  it('位置偏了但选中文字在正文里唯一时按文字定位', () => {
    expect(resolveSelection(CONTENT, '又关上', 0)).toEqual({ start: 19, end: 22, text: '又关上' })
  })

  it('选中文字在正文里出现多次且位置对不上 → 取离提示位置最近的一处', () => {
    expect(resolveSelection(CONTENT, '林尘推开门', 15)).toEqual({ start: 13, end: 18, text: '林尘推开门' })
  })

  it('空选区或正文里没有的文字返回 null', () => {
    expect(resolveSelection(CONTENT, '   ', 0)).toBeNull()
    expect(resolveSelection(CONTENT, '不存在的句子', 0)).toBeNull()
  })
})
