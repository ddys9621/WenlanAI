import { describe, expect, it } from 'vitest'
import { appendQuote, appendRequest, diffBlocks, formatFieldValue } from './assistantText'

describe('diffBlocks', () => {
  it('内容相同只有一个不变块', () => {
    expect(diffBlocks('林尘沉默寡言。', '林尘沉默寡言。')).toEqual([{ kind: 'same', before: '林尘沉默寡言。', after: '林尘沉默寡言。' }])
  })

  it('只标出改动的句子，前后相同的部分保持原样', () => {
    const blocks = diffBlocks('他出身孤儿。性格沉默寡言。擅长剑法。', '他出身孤儿。外冷内热，护短。擅长剑法。')
    expect(blocks.map((b) => b.kind)).toEqual(['same', 'change', 'same'])
    expect(blocks[1]).toEqual({ kind: 'change', before: '性格沉默寡言。', after: '外冷内热，护短。' })
  })

  it('新增与删除', () => {
    expect(diffBlocks('', '新写的设定。')).toEqual([{ kind: 'change', before: '', after: '新写的设定。' }])
    const blocks = diffBlocks('甲。乙。', '甲。乙。丙。')
    expect(blocks[blocks.length - 1]).toEqual({ kind: 'change', before: '', after: '丙。' })
  })
})

describe('appendQuote / appendRequest', () => {
  it('引用追加到输入框末尾，已有草稿保留', () => {
    expect(appendQuote('', '旧画在墙上')).toBe('> 旧画在墙上\n\n')
    expect(appendQuote('我想问', '第一行\n第二行')).toBe('我想问\n\n> 第一行\n> 第二行\n\n')
  })

  it('快捷入口只填入要求：空输入直接填，已有草稿则追加；重复的不再追加', () => {
    expect(appendRequest('', '帮我完善人物：')).toBe('帮我完善人物：')
    expect(appendRequest('我的想法是', '帮我完善人物：')).toBe('我的想法是\n帮我完善人物：')
    expect(appendRequest('帮我完善人物：', '帮我完善人物：')).toBe('帮我完善人物：')
  })
})

describe('formatFieldValue', () => {
  it('列表按行显示，空值显示空白', () => {
    expect(formatFieldValue(['甲', '乙'])).toBe('甲\n乙')
    expect(formatFieldValue('')).toBe('')
  })
})
