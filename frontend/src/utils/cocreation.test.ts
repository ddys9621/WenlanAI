import { describe, expect, it } from 'vitest'
import type { AssistantEntityCandidate, AssistantFieldCandidate, AssistantPlan, AssistantQuestion } from '@/types/assistant'
import {
  batchConfirmText, changeItems, changeSummary, liveCardOwner, memberTone, mentionMember, pendingChanges, pendingSummary,
  planConfirmTargets, planEntity, planKey, planLink, questionCardKey,
} from './cocreation'

const field = (id: string, status: AssistantFieldCandidate['status'], label = '作品设定·主题'): AssistantFieldCandidate => ({
  id, field_id: 'project.theme', target_id: 'p', entity: 'project', label, page: 'world-setting', before: '', after: '新主题',
  reason: '', status, run_id: 'r', created_at: null, decided_at: null,
})
const entity = (id: string, status: AssistantEntityCandidate['status'], payload: Record<string, string>, entityType = 'setting_entry'): AssistantEntityCandidate => ({
  id, entity_type: entityType, label: `新建「${payload.name ?? payload.title}」`, page: 'setting-entries', payload, reason: '',
  status, run_id: 'r', created_entity_id: null, created_at: null, decided_at: null,
})

describe('改动清单（对话里一行摘要 + 输入框上方的待确认栏）', () => {
  const fields = new Map([['f1', field('f1', 'candidate')], ['f2', field('f2', 'applied', '总纲·全书主线')]])
  const entities = new Map([
    ['e1', entity('e1', 'candidate', { title: '歪理成道·四律' })],
    ['e2', entity('e2', 'applied', { category: 'cultivation_realm', name: '炼气' }, 'world_rule')],
    ['e3', entity('e3', 'rejected', { name: '守墨人' }, 'organization')],
  ])
  const plan: AssistantPlan = {
    kind: 'volumes', title: '四卷分卷', volumes: [{ id: 'v1', volume_number: 1, title: '宗门篇', chapter_start: 1, chapter_end: 75, summary: '', unit_count: 0 }],
  }
  const cards = { candidates: ['f1', 'f2', 'gone'], entity_candidates: ['e1', 'e2', 'e3'], chapter_candidates: [], plans: [plan] }

  it('每张卡一行：类别、名称、状态；找不到的卡（已删除）不列', () => {
    const items = changeItems(cards, { fields, entities, confirmedPlans: new Set() })
    expect(items.map((i) => [i.tag, i.title, i.status])).toEqual([
      ['修改', '作品设定·主题', '待确认'],
      ['修改', '总纲·全书主线', '已应用'],
      ['新建设定条目', '歪理成道·四律', '待确认'],
      ['新建修炼境界', '炼气', '已建档'],
      ['新建组织', '守墨人', '没有采用'],
      ['分卷草案', '四卷分卷', '待确认'],
    ])
    expect(changeSummary(items)).toBe('改动 6 项 · 待确认 3 · 已采用 2 · 没采用 1')
  })

  it('草案在卡片上确认过（或服务端说已确认）就不再算待确认', () => {
    const confirmed = changeItems(cards, { fields, entities, confirmedPlans: new Set([planKey(plan)]) })
    expect(confirmed.at(-1)?.state).toBe('done')
    expect(changeItems({ ...cards, plans: [{ ...plan, confirmed: true }] }, { fields, entities, confirmedPlans: new Set() }).at(-1)?.status)
      .toBe('已确认')
  })

  it('待确认栏：整段对话里还没处理的卡，按出现顺序、同一张只列一次', () => {
    const later = { candidates: ['f1'], entity_candidates: [], chapter_candidates: [], plans: [plan] }
    const pending = pendingChanges([cards, later], { fields, entities, confirmedPlans: new Set() })
    expect(pending.map((i) => i.key)).toEqual(['field:f1', 'entity:e1', planKey(plan)])
    expect(pendingSummary(pending)).toBe('修改 1 · 新建设定条目 1 · 分卷草案 1')
  })

  it('没挂在任何发言下的待确认卡（比如刚推来的）也进待确认栏', () => {
    const orphan = new Map([...entities, ['e9', entity('e9', 'candidate', { name: '青云宗' }, 'organization')]])
    const pending = pendingChanges([cards], { fields, entities: orphan, confirmedPlans: new Set() })
    expect(pending.at(-1)?.key).toBe('entity:e9')
  })

  it('已建档、书里却没有了（被删了或当时没建成）：单独标出来，不算已采用，也不进待确认栏', () => {
    const gone = new Map([['e5', { ...entity('e5', 'applied', { name: '守墨人' }, 'organization'), entity_missing: true }]])
    const lookups = { fields: new Map(), entities: gone, confirmedPlans: new Set<string>() }
    const items = changeItems({ candidates: [], entity_candidates: ['e5'], chapter_candidates: [], plans: [] }, lookups)
    expect(items.map((i) => [i.state, i.status])).toEqual([['missing', '已不在书里']])
    expect(changeSummary(items)).toBe('改动 1 项 · 已不在书里 1')
    expect(pendingChanges([{ candidates: [], entity_candidates: ['e5'], chapter_candidates: [], plans: [] }], lookups)).toEqual([])
  })

  it('草案的卷纲 / 章纲已经不在了（被重新分卷替换、或在谋篇页删了）：标「已失效」，不算待确认、不进待确认栏', () => {
    const gone = { ...plan, gone: true }
    const only = { candidates: [], entity_candidates: [], chapter_candidates: [], plans: [gone] }
    const lookups = { fields: new Map(), entities: new Map(), confirmedPlans: new Set([planKey(gone)]) }
    const items = changeItems(only, lookups)
    expect(items.map((i) => [i.state, i.status])).toEqual([['gone', '已失效']])
    expect(changeSummary(items)).toBe('改动 1 项 · 已失效 1')
    expect(pendingChanges([only], lookups)).toEqual([])
  })

  it('全部采用 / 全部放弃前的确认语：放弃只针对候选，有草案时说明草案不受影响', () => {
    const pending = pendingChanges([cards], { fields, entities, confirmedPlans: new Set() })
    expect(batchConfirmText(pending, 'apply')).toBe('将新建 1 项、应用 1 处修改、确认 1 份草案')
    expect(batchConfirmText(pending, 'reject')).toBe('放弃 2 项候选（草案不受影响，可去谋篇页删除）')
    expect(batchConfirmText(pending.filter((i) => i.ref.kind !== 'plan'), 'reject')).toBe('放弃 2 项候选')
  })
})

describe('mentionMember', () => {
  it('在草稿开头加上 @成员，已有的提及换成新的', () => {
    expect(mentionMember('', '人物设计师')).toBe('@人物设计师 ')
    expect(mentionMember('女主再冷一点', '人物设计师')).toBe('@人物设计师 女主再冷一点')
    expect(mentionMember('@世界观设定师 设计门派', '人物设计师')).toBe('@人物设计师 设计门派')
  })

  it('选主编就去掉提及（主编默认发言）', () => {
    expect(mentionMember('@审校编辑 看看第三章', '主编')).toBe('看看第三章')
  })
})

describe('草案卡片', () => {
  const volumes: AssistantPlan = {
    kind: 'volumes', title: '分卷', volumes: [
      { id: 'v1', volume_number: 1, title: '雾起', chapter_start: 1, chapter_end: 20, summary: '', unit_count: 0 },
      { id: 'v2', volume_number: 2, title: '潮落', chapter_start: 21, chapter_end: 40, summary: '', unit_count: 0 },
    ],
  }
  const units: AssistantPlan = {
    kind: 'units', title: '单元', volume: {
      id: 'v1', volume_number: 1, title: '雾起', chapter_start: 1, chapter_end: 20, summary: '', unit_count: 2, units: [], threads: [],
    },
  }
  const outlines: AssistantPlan = {
    kind: 'outlines', title: '章纲', volume_id: 'v1', unit_index: 1,
    chapters: [{ id: 'c1', chapter_number: 1, title: '一', plot_points: '' }, { id: 'c2', chapter_number: 2, title: '二', plot_points: '' }],
  }

  it('确认的对象：卷纲草案确认卷，章纲草案确认章纲', () => {
    expect(planConfirmTargets(volumes)).toEqual({ volumeIds: ['v1', 'v2'], outlineIds: [] })
    expect(planConfirmTargets(units)).toEqual({ volumeIds: ['v1'], outlineIds: [] })
    expect(planConfirmTargets(outlines)).toEqual({ volumeIds: [], outlineIds: ['c1', 'c2'] })
  })

  it('刷新哪类页面数据、跳到谋篇的哪个页签', () => {
    expect(planEntity(volumes)).toBe('volume')
    expect(planEntity(outlines)).toBe('chapter_outline')
    expect(planLink(units)).toBe('outline/volumes')
    expect(planLink(outlines)).toBe('outline/chapters')
  })
})

describe('questionCardKey', () => {
  const ask = (...ids: string[]): AssistantQuestion[] =>
    ids.map((id) => ({ id, prompt: id, mode: 'single', options: [{ id: 'a', label: '甲' }, { id: 'b', label: '乙' }] }))

  it('同一轮运行先后两次提问（问题 id 不同）要换一张新卡：沿用旧卡读不到新问题的作答，整页白屏', () => {
    const first = questionCardKey({ id: 'run-1', question: { questions: ask('q1', 'q2', 'q3') } })
    const second = questionCardKey({ id: 'run-1', question: { questions: ask('world_style', 'origin_clarity', 'vortex_role') } })
    expect(second).not.toBe(first)
  })

  it('同一组问题保持同一张卡，作者已勾选的作答不丢', () => {
    const run = { id: 'run-1', question: { questions: ask('q1', 'q2') } }
    expect(questionCardKey({ ...run })).toBe(questionCardKey(run))
    expect(questionCardKey({ id: 'run-2', question: run.question })).not.toBe(questionCardKey(run))
  })
})

describe('liveCardOwner', () => {
  const world = { id: 'world' }
  const role = { id: 'character' }

  it('成员处理主编交代的事时提的卡挂到那条委托下（同一成员被交代了两次就挂到还没回复的那条）', () => {
    const delegations = [{ member: world, content: '建好了甲帮。' }, { member: role, content: '' }, { member: world, content: '' }]
    expect(liveCardOwner(delegations, 'world')).toBe(2)
    expect(liveCardOwner(delegations, 'character')).toBe(1)
  })

  it('没有在处理的委托、或是发言者自己提的，挂到本轮发言者下', () => {
    expect(liveCardOwner([{ member: world, content: '建好了甲帮。' }], 'world')).toBe(-1)
    expect(liveCardOwner([{ member: world, content: '' }], 'editor')).toBe(-1)
    expect(liveCardOwner([{ member: world, content: '' }], undefined)).toBe(-1)
  })
})

describe('memberTone', () => {
  it('已知颜色给对应的浅底深字，未知颜色回落中性色', () => {
    expect(memberTone('rose')).not.toBe(memberTone('unknown'))
    expect(memberTone('unknown')).toBe(memberTone('slate'))
  })
})
