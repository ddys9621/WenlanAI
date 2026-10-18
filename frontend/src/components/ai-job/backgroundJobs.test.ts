import { createElement as h, type ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { beforeEach, describe, expect, it } from 'vitest'
import { useAIJobsStore } from '@/store/aiJobsStore'
import { createJobState } from '@/utils/aiJobReducer'
import { VolumesView } from '@/components/outline/VolumesView'
import Characters from '@/pages/Characters'
import ChapterAnalysis from '@/pages/ChapterAnalysis'

const TITLES = {
  chapter: '生成第 1 章《封印裂开的那天》',
  volume: '细化第1卷《开端》',
  character: 'AI 生成角色「林舟」',
}

const running = (id: string, kind: string, title: string) => ({
  ...createJobState({ id, kind, title, projectId: 'p1' }),
  progress: { message: 'AI开始创作章节内容...', pct: 30 },
})

const noop = async () => undefined
const render = (el: ReactElement) => renderToStaticMarkup(h(StaticRouter, { location: '/project/p1' }, el))
const expectNoJobBanner = (html: string) => {
  for (const title of Object.values(TITLES)) expect(html).not.toContain(title)
}

/** 后台运行的 AI 任务只在顶栏「AI 任务」托盘里显示，页面里不再重复出一条任务横幅 */
describe('后台 AI 任务不在页面上出横幅', () => {
  beforeEach(() => {
    useAIJobsStore.setState({
      jobs: {
        j1: running('j1', 'chapter_generate', TITLES.chapter),
        j2: running('j2', 'volume_plan', TITLES.volume),
        j3: running('j3', 'character_generate', TITLES.character),
      },
      openJobId: null,
    })
  })

  it('章节写作', () => {
    const html = render(h(ChapterAnalysis))
    expect(html).toContain('还没有章节')
    expectNoJobBanner(html)
  })

  it('卷纲', () => {
    const html = render(h(VolumesView, {
      projectId: 'p1', chapterCount: 10, volumes: [], chapterOutlines: [],
      refreshVolumes: noop, refreshChapterOutlines: noop,
      saveVolume: () => Promise.reject(new Error('unused')), confirmVolume: () => Promise.reject(new Error('unused')),
      deleteVolume: noop, onOpenChapterOutlines: () => undefined,
    }))
    expect(html).toContain('还没有卷纲')
    expectNoJobBanner(html)
  })

  it('角色与组织', () => {
    const html = render(h(Characters))
    expect(html).toContain('角色与组织')
    expectNoJobBanner(html)
  })
})
