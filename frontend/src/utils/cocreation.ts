/**
 * 共创室（智能助笔）的纯函数：@成员 提及、成员头像配色、运行中卡片挂到谁名下、草案卡片的确认对象与跳转、
 * 改动清单（每条回复里的一行摘要 / 输入框上方的待确认栏）。
 */
import type {
  AssistantChapterCandidateRef, AssistantEntityCandidate, AssistantFieldCandidate, AssistantPlan, AssistantRunView,
} from '@/types/assistant'

/** 成员头像：浅底 + 同色深字（全站低饱和色板），一眼分得清是谁在说话 */
const TONES: Record<string, string> = {
  jade: 'bg-emerald-100 text-emerald-700',
  blue: 'bg-sky-100 text-sky-700',
  rose: 'bg-rose-100 text-rose-700',
  amber: 'bg-amber-100 text-amber-700',
  violet: 'bg-violet-100 text-violet-700',
  orange: 'bg-orange-100 text-orange-700',
  slate: 'bg-slate-100 text-slate-700',
}

export function memberTone(color: string | undefined): string {
  return TONES[color ?? ''] ?? TONES.slate
}

/** 开头的「@成员」（与后端 cocreation_team.parse_mention 的写法一致：@名称 + 空白或标点） */
const LEADING_MENTION = /^\s*@\S+?[\s，,:：]+/

/** 草稿开头放上「@成员」；已有提及就换掉；选主编则去掉提及（主编默认发言） */
export function mentionMember(draft: string, memberName: string): string {
  const rest = draft.replace(LEADING_MENTION, '')
  return memberName === '主编' ? rest : `@${memberName} ${rest}`
}

/**
 * 运行中推来的卡片挂到谁的发言下：提它的成员正在处理主编交代的事（委托还没回复）就挂到那条委托下，
 * 否则挂到本轮发言者下。返回委托下标，-1 = 本轮发言者。跑完后以服务端存的为准，位置一致。
 */
export function liveCardOwner(delegations: { member: { id: string }; content: string }[], memberId: string | undefined): number {
  if (!memberId) return -1
  for (let i = delegations.length - 1; i >= 0; i -= 1) {
    if (delegations[i].member.id === memberId && !delegations[i].content) return i
  }
  return -1
}

export function questionCardKey(run: Pick<AssistantRunView, 'id' | 'question'>): string {
  return `${run.id}:${(run.question?.questions ?? []).map((q) => q.id).join(',')}`
}

export function planConfirmTargets(plan: AssistantPlan): { volumeIds: string[]; outlineIds: string[] } {
  if (plan.kind === 'volumes') return { volumeIds: plan.volumes.map((v) => v.id), outlineIds: [] }
  if (plan.kind === 'units') return { volumeIds: [plan.volume.id], outlineIds: [] }
  return { volumeIds: [], outlineIds: plan.chapters.map((c) => c.id) }
}

/** 确认后通知哪类页面数据刷新（谋篇页监听 volume / chapter_outline） */
export function planEntity(plan: AssistantPlan): 'volume' | 'chapter_outline' {
  return plan.kind === 'outlines' ? 'chapter_outline' : 'volume'
}

/** 「去谋篇页看」跳到哪个页签（相对 /project/:id/） */
export function planLink(plan: AssistantPlan): string {
  return plan.kind === 'outlines' ? 'outline/chapters' : 'outline/volumes'
}

/** 草案的身份：按它要确认的卷 / 章纲（运行中推来的和跑完存下的是同一份，key 一致） */
export function planKey(plan: AssistantPlan): string {
  const { volumeIds, outlineIds } = planConfirmTargets(plan)
  return `plan:${plan.kind}:${[...volumeIds, ...outlineIds].join(',')}`
}

/** 一条发言带出的卡片（与消息里存的同一组字段） */
export interface ChangeCards {
  candidates: string[]
  entity_candidates: string[]
  chapter_candidates: AssistantChapterCandidateRef[]
  plans: AssistantPlan[]
}

export interface ChangeLookups {
  fields: Map<string, AssistantFieldCandidate>
  entities: Map<string, AssistantEntityCandidate>
  /** 本页确认过的草案（服务端的 confirmed 要刷新后才有） */
  confirmedPlans: Set<string>
}

/**
 * pending 待确认；done 已采用（应用 / 建档 / 确认）；dropped 没采用 / 已撤销；open 候选稿（去章节页审阅，状态在那边）；
 * missing 建过档、书里却没有了（被删了或当时没写进去），卡片上可以重新建档；
 * gone 草案里的卷纲 / 章纲已经不在了（被重新分卷替换、或删了），作废
 */
export type ChangeState = 'pending' | 'done' | 'dropped' | 'open' | 'missing' | 'gone'

export type ChangeRef =
  | { kind: 'field'; candidate: AssistantFieldCandidate }
  | { kind: 'entity'; candidate: AssistantEntityCandidate }
  | { kind: 'plan'; plan: AssistantPlan }
  | { kind: 'chapter'; item: AssistantChapterCandidateRef }

export interface ChangeItem {
  key: string
  ref: ChangeRef
  /** 类别：修改 / 新建设定条目 / 新建修炼境界 / 分卷草案 / 候选稿… */
  tag: string
  title: string
  state: ChangeState
  status: string
}

const ENTITY_KIND: Record<string, string> = { character: '角色', organization: '组织', setting_entry: '设定条目' }
const WORLD_RULE_KIND: Record<string, string> = {
  cultivation_realm: '修炼境界', equipment_template: '装备模板', map_location: '地图位置',
}
const PLAN_KIND: Record<AssistantPlan['kind'], string> = { volumes: '分卷草案', units: '剧情单元草案', outlines: '章纲草案' }
const FIELD_STATUS: Record<AssistantFieldCandidate['status'], [ChangeState, string]> = {
  candidate: ['pending', '待确认'], applied: ['done', '已应用'], undone: ['dropped', '已撤销'], rejected: ['dropped', '没有采用'],
}
const ENTITY_STATUS: Record<AssistantEntityCandidate['status'], [ChangeState, string]> = {
  candidate: ['pending', '待确认'], applied: ['done', '已建档'], rejected: ['dropped', '没有采用'],
}

export function entityKind(c: Pick<AssistantEntityCandidate, 'entity_type' | 'payload'>): string {
  if (c.entity_type === 'world_rule') return WORLD_RULE_KIND[c.payload.category] ?? '世界规则'
  return ENTITY_KIND[c.entity_type] ?? '对象'
}

function fieldChange(c: AssistantFieldCandidate): ChangeItem {
  const [state, status] = FIELD_STATUS[c.status]
  return { key: `field:${c.id}`, ref: { kind: 'field', candidate: c }, tag: '修改', title: c.label, state, status }
}

function entityChange(c: AssistantEntityCandidate): ChangeItem {
  const [state, status] = c.status === 'applied' && c.entity_missing ? ['missing', '已不在书里'] as const : ENTITY_STATUS[c.status]
  return {
    key: `entity:${c.id}`, ref: { kind: 'entity', candidate: c }, tag: `新建${entityKind(c)}`,
    title: c.payload.name || c.payload.title || c.label, state, status,
  }
}

function planChange(plan: AssistantPlan, confirmedPlans: Set<string>): ChangeItem {
  const key = planKey(plan)
  const done = Boolean(plan.confirmed) || confirmedPlans.has(key)
  const [state, status]: [ChangeState, string] = plan.gone ? ['gone', '已失效'] : done ? ['done', '已确认'] : ['pending', '待确认']
  return { key, ref: { kind: 'plan', plan }, tag: PLAN_KIND[plan.kind], title: plan.title, state, status }
}

/** 一条发言提出的改动，每张卡一行（顺序：修改、新建、候选稿、草案；已经找不到的卡不列） */
export function changeItems(cards: ChangeCards, lookups: ChangeLookups): ChangeItem[] {
  return [
    ...cards.candidates.flatMap((id) => {
      const c = lookups.fields.get(id)
      return c ? [fieldChange(c)] : []
    }),
    ...cards.entity_candidates.flatMap((id) => {
      const c = lookups.entities.get(id)
      return c ? [entityChange(c)] : []
    }),
    ...cards.chapter_candidates.map((item): ChangeItem => ({
      key: `chapter:${item.id}`, ref: { kind: 'chapter', item }, tag: '候选稿',
      title: `第 ${item.chapter_number} 章《${item.chapter_title}》`, state: 'open', status: '去审阅',
    })),
    ...cards.plans.map((plan) => planChange(plan, lookups.confirmedPlans)),
  ]
}

/** 回复里那一行：「改动 4 项 · 待确认 2 · 已采用 2」 */
export function changeSummary(items: ChangeItem[]): string {
  const count = (state: ChangeState) => items.filter((i) => i.state === state).length
  const parts: [string, number][] = [
    ['待确认', count('pending')], ['已采用', count('done')], ['已不在书里', count('missing')], ['没采用', count('dropped')],
    ['已失效', count('gone')], ['候选稿', count('open')],
  ]
  return [`改动 ${items.length} 项`, ...parts.filter(([, n]) => n > 0).map(([label, n]) => `${label} ${n}`)].join(' · ')
}

/**
 * 待确认栏：整段对话里还没处理的改动，按出现顺序、同一张卡只列一次；
 * 没挂在任何发言下的待确认卡（刚推来、还没落到消息里）也列上。候选稿要去章节页审阅，不在这里处理。
 */
export function pendingChanges(cardGroups: ChangeCards[], lookups: ChangeLookups): ChangeItem[] {
  const seen = new Set<string>()
  const out: ChangeItem[] = []
  const add = (item: ChangeItem) => {
    if (item.state !== 'pending' || seen.has(item.key)) return
    seen.add(item.key)
    out.push(item)
  }
  cardGroups.forEach((cards) => changeItems(cards, lookups).forEach(add))
  lookups.fields.forEach((c) => add(fieldChange(c)))
  lookups.entities.forEach((c) => add(entityChange(c)))
  return out
}

/** 待确认栏收起时的一行：「新建设定条目 2 · 修改 1」 */
export function pendingSummary(items: ChangeItem[]): string {
  const counts = new Map<string, number>()
  items.forEach((i) => counts.set(i.tag, (counts.get(i.tag) ?? 0) + 1))
  return [...counts].map(([tag, n]) => `${tag} ${n}`).join(' · ')
}

/** 「全部采用 / 全部放弃」前的确认语（items = 待确认栏里的全部）：放弃只针对候选，草案没有「不用」 */
export function batchConfirmText(items: ChangeItem[], action: 'apply' | 'reject'): string {
  const count = (kind: ChangeRef['kind']) => items.filter((i) => i.ref.kind === kind).length
  if (action === 'reject') {
    return `放弃 ${count('field') + count('entity')} 项候选${count('plan') ? '（草案不受影响，可去谋篇页删除）' : ''}`
  }
  const parts = [
    count('entity') && `新建 ${count('entity')} 项`, count('field') && `应用 ${count('field')} 处修改`,
    count('plan') && `确认 ${count('plan')} 份草案`,
  ].filter(Boolean)
  return `将${parts.join('、')}`
}
