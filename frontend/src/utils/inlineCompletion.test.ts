import { describe, expect, it } from 'vitest'
import { PREFIX_SEND_CHARS, SUFFIX_SEND_CHARS, completionContext, consumeTyped, nextChunk, restOfLineIsBlank } from './inlineCompletion'

describe('completionContext', () => {
  it('只取光标前后各一段发给后端', () => {
    const doc = '前'.repeat(PREFIX_SEND_CHARS + 10) + '|' + '后'.repeat(SUFFIX_SEND_CHARS + 10)
    const pos = doc.indexOf('|')
    const { prefix, suffix } = completionContext(doc, pos)
    expect(prefix).toBe('前'.repeat(PREFIX_SEND_CHARS))
    expect(suffix).toBe('|' + '后'.repeat(SUFFIX_SEND_CHARS - 1))
  })
})

describe('restOfLineIsBlank（只在段尾自动补全）', () => {
  it('光标后同一行没有正文才算段尾；输入法自动配对的后引号不算正文', () => {
    const doc = '他推开门\n下一段'
    expect(restOfLineIsBlank(doc, 4)).toBe(true)
    expect(restOfLineIsBlank(doc, 2)).toBe(false)
    expect(restOfLineIsBlank('他说：“”', 4)).toBe(true)
    expect(restOfLineIsBlank('末尾', 2)).toBe(true)
  })
})

describe('nextChunk（Ctrl+→ 只采用一小句）', () => {
  it('取到下一个标点（连同后引号）为止', () => {
    expect(nextChunk('屋里很暗，他摸出火折子。')).toBe('屋里很暗，')
    expect(nextChunk('“走吧。”她说')).toBe('“走吧。”')
    expect(nextChunk('没有标点的一句')).toBe('没有标点的一句')
  })

  it('段首的换行和缩进跟着第一小句一起采用', () => {
    expect(nextChunk('\n\n\u3000\u3000屋里很暗，他摸出')).toBe('\n\n\u3000\u3000屋里很暗，')
  })
})

describe('consumeTyped（顺着建议打字）', () => {
  it('打的字和建议开头一致就吃掉这几个字，否则作废', () => {
    expect(consumeTyped('屋里很暗。', '屋里')).toBe('很暗。')
    expect(consumeTyped('屋里很暗。', '屋里很暗。')).toBe('')
    expect(consumeTyped('屋里很暗。', '外面')).toBeNull()
  })
})
