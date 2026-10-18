import { createElement as h, type ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { beforeEach, describe, expect, it } from 'vitest'
import { useAIJobsStore } from '@/store/aiJobsStore'
import { createJobState } from '@/utils/aiJobReducer'
import Characters from '@/pages/Characters'
import { OutlinesView } from '@/pages/Outline'

const render = (el: ReactElement) => renderToStaticMarkup(h(StaticRouter, { location: '/project/p1' }, el))

/** 按钮标签所在的 <button> 是否禁用（运行中的任务按 kind 从全局任务 store 派生，刷新后也对） */
const buttonDisabled = (html: string, label: string) => {
  const button = [...html.matchAll(/<button[^>]*>[\s\S]*?<\/button>/g)].map((m) => m[0]).find((b) => b.includes(label))
  expect(button, `找不到「${label}」按钮`).toBeDefined()
  return /^<button[^>]*\sdisabled=""/.test(button!)
}

const runJob = (kind: string) =>
  useAIJobsStore.setState({ jobs: { j1: createJobState({ id: 'j1', kind, title: 'x', projectId: 'p1' }) }, openJobId: null })

const noop = async () => undefined
const outlinesView = () => render(h(OutlinesView, {
  outlines: [], projectId: 'p1', project: null,
  createOutline: () => Promise.reject(new Error('unused')), updateOutline: () => Promise.reject(new Error('unused')),
  deleteOutline: noop, activateOutline: () => Promise.reject(new Error('unused')),
  refreshOutlines: async () => [], onPlanChanged: () => undefined,
}))

describe('角色与组织：AI 批量生成', () => {
  beforeEach(() => useAIJobsStore.setState({ jobs: {}, openJobId: null }))

  it('页头有「AI 批量生成」入口', () => {
    expect(buttonDisabled(render(h(Characters)), 'AI 批量生成')).toBe(false)
  })

  it('批量生成任务在跑时按钮禁用（单个生成角色不影响它）', () => {
    runJob('character_generate')
    expect(buttonDisabled(render(h(Characters)), 'AI 批量生成')).toBe(false)
    runJob('character_batch_generate')
    expect(buttonDisabled(render(h(Characters)), 'AI 批量生成')).toBe(true)
  })
})

describe('谋篇·总纲：AI 生成走后台任务', () => {
  beforeEach(() => useAIJobsStore.setState({ jobs: {}, openJobId: null }))

  it('没有任务时可以点', () => {
    expect(buttonDisabled(outlinesView(), 'AI 生成')).toBe(false)
  })

  it('本项目有总纲生成（或向导正在生成总纲）时禁用', () => {
    runJob('story_outline_generate')
    expect(buttonDisabled(outlinesView(), 'AI 生成')).toBe(true)
    runJob('wizard_outline')
    expect(buttonDisabled(outlinesView(), 'AI 生成')).toBe(true)
    runJob('volume_plan')
    expect(buttonDisabled(outlinesView(), 'AI 生成')).toBe(false)
  })
})
