import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { OptionalModelField } from './OptionalModelField'

/** 设置页的可选模型字段（分析 / 补全模型）：服务端渲染冒烟 */
const base = {
  label: '分析模型', followText: '跟随 LLM 模型（gpt-4o）', hint: '说明', onChange: () => undefined,
  models: [{ value: 'deepseek-chat', label: 'deepseek-chat', description: '' }], loading: false, onRefresh: () => undefined,
}

describe('OptionalModelField', () => {
  it('留空 = 跟随：勾选框勾上，不显示选择器', () => {
    const html = renderToStaticMarkup(h(OptionalModelField, { ...base, value: '' }))
    expect(html).toContain('跟随 LLM 模型（gpt-4o）')
    expect(html).toMatch(/type="checkbox"[^>]*checked=""/)
    expect(html).not.toContain('从已拉取的')
  })

  it('选了模型：显示选择器与当前值，可展开已拉取的列表', () => {
    const html = renderToStaticMarkup(h(OptionalModelField, { ...base, value: 'deepseek-chat' }))
    expect(html).not.toMatch(/type="checkbox"[^>]*checked=""/)
    expect(html).toContain('value="deepseek-chat"')
    expect(html).toContain('从已拉取的 1 个模型中选择')
  })
})
