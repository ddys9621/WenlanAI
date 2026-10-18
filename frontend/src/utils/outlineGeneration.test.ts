import { describe, expect, it } from 'vitest'
import type { Project } from '@/types'
import { outlineGenerationDefaults, outlineGenerationPayload } from './outlineGeneration'

const project = (fields: Partial<Project>): Project => ({
  id: 'p1', title: '书', current_words: 0, status: 'planning', created_at: '', updated_at: '', ...fields,
})

describe('outlineGenerationDefaults', () => {
  it('视角 / 章数 / 字数默认取项目设置', () => {
    expect(outlineGenerationDefaults(project({ narrative_perspective: '第一人称', chapter_count: 300, target_words: 900000 })))
      .toEqual({ narrative_perspective: '第一人称', chapter_count: 300, target_words: 900000, requirements: '' })
  })

  it('项目没填的项用通用默认值', () => {
    expect(outlineGenerationDefaults(project({}))).toEqual({
      narrative_perspective: '第三人称', chapter_count: 30, target_words: 100000, requirements: '',
    })
    expect(outlineGenerationDefaults(null).chapter_count).toBe(30)
  })
})

describe('outlineGenerationPayload', () => {
  const mcp = { enable: true, selected: ['exa'] }

  it('章数 / 字数取正整数，额外要求去首尾空白', () => {
    expect(outlineGenerationPayload(
      { narrative_perspective: '第一人称', chapter_count: 120.6, target_words: 360000, requirements: ' 节奏快 ' }, mcp,
    )).toEqual({
      narrative_perspective: '第一人称', chapter_count: 120, target_words: 360000, requirements: '节奏快',
      enable_mcp: true, selected_plugins: ['exa'],
    })
  })

  it('清空 / 填 0 / 负数的章数字数留空，交给后端按项目设置补齐', () => {
    const payload = outlineGenerationPayload(
      { narrative_perspective: '第三人称', chapter_count: 0, target_words: -5, requirements: '  ' }, { enable: false, selected: [] },
    )
    expect(payload.chapter_count).toBeUndefined()
    expect(payload.target_words).toBeUndefined()
    expect(payload.requirements).toBeUndefined()
    expect(outlineGenerationPayload({ ...outlineGenerationDefaults(null), chapter_count: Number.NaN }, mcp).chapter_count).toBeUndefined()
  })
})
