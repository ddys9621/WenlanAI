import { describe, expect, it } from 'vitest'
import { countParagraphs, countWords, findMatches, formatParagraphs, paragraphBreak } from './manuscript'

describe('countWords（与后端 count_words 实际结果一致）', () => {
  it('汉字各算 1 字，英文单词 / 连续数字各算 1 字，标点空白不计', () => {
    expect(countWords('你好世界')).toBe(4)
    expect(countWords('Hello World')).toBe(2)
    expect(countWords('你好Hello世界World')).toBe(6)
    expect(countWords('2024年1月1日')).toBe(6)
    expect(countWords('１２３个')).toBe(2) // 全角数字也算数字（Python \d 认 Unicode 数字）
    expect(countWords('，。！ \n　　')).toBe(0)
    expect(countWords('')).toBe(0)
  })
})

describe('countParagraphs', () => {
  it('非空行就是一段（单换行、空行分段都认）', () => {
    expect(countParagraphs('　　第一段。\n\n　　第二段。\n第三段。\n\n')).toBe(3)
    expect(countParagraphs('  \n\n')).toBe(0)
  })
})

describe('formatParagraphs（一键排版）', () => {
  const messy = '  第一段。\r\n\r\n\r\n\u3000第二段，  \n第三段。\n   '

  it('默认：首行两个全角空格、段间空一行，保留原有分段', () => {
    expect(formatParagraphs(messy)).toBe('\u3000\u3000第一段。\n\n\u3000\u3000第二段，\n\n\u3000\u3000第三段。')
  })

  it('可关掉首行缩进 / 段间空行', () => {
    expect(formatParagraphs(messy, { firstLineIndent: false, paragraphSpacing: false })).toBe('第一段。\n第二段，\n第三段。')
  })
})

describe('paragraphBreak（回车续段）', () => {
  it('按版式决定空行与缩进', () => {
    expect(paragraphBreak({ firstLineIndent: true, paragraphSpacing: true })).toBe('\n\n\u3000\u3000')
    expect(paragraphBreak({ firstLineIndent: false, paragraphSpacing: false })).toBe('\n')
  })
})

describe('findMatches（查找）', () => {
  it('返回所有不重叠的出现位置，空查询没有结果', () => {
    expect(findMatches('林尘看着林尘', '林尘')).toEqual([0, 4])
    expect(findMatches('哈哈哈', '哈哈')).toEqual([0])
    expect(findMatches('任意文字', '')).toEqual([])
  })
})
