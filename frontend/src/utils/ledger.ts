/** 故事账本页的纯函数：标签、作者修正表单校验、时间线分组 */
import type { PillTone } from '@/components/ui/Pill'
import type { CorrectionType, LedgerPromise, PromisePriority, PromiseStatus, PromiseType, StateCorrectionCreate, TimelineItem } from '@/types/ledger'

export const PROMISE_TYPE_LABELS: Record<PromiseType, string> = {
  foreshadow: '伏笔', promise: '承诺', mystery: '悬念', conflict: '冲突',
}
export const PRIORITY_LABELS: Record<PromisePriority, string> = { critical: '紧急', high: '高', medium: '中', low: '低' }
export const PRIORITY_TONE: Record<PromisePriority, PillTone> = { critical: 'red', high: 'orange', medium: 'default', low: 'default' }
export const STATUS_TONE: Record<PromiseStatus, PillTone> = {
  open: 'brand', progressing: 'orange', resolved: 'green', broken: 'red', abandoned: 'default',
}

export const FIELD_LABELS: Record<string, string> = {
  title: '标题', content: '内容', promise_type: '类型', priority: '优先级', deadline_chapter: '计划回收章',
  status: '状态', owner: '发起人', target: '对象',
}

/** 作者改过哪些字段（给「作者改过」提示用）；["*"] = 作者新建 */
export function lockedSummary(promise: Pick<LedgerPromise, 'locked_fields'>): string {
  const fields = promise.locked_fields ?? []
  if (fields.length === 0) return ''
  if (fields.includes('*')) return '作者登记'
  return `作者改过：${fields.map((f) => FIELD_LABELS[f] ?? f).join('、')}`
}

export interface CorrectionTypeOption {
  type: CorrectionType
  label: string
  /** 需要填内容（境界名 / 地点 / 物品…）；生死只选状态 */
  needsKey: boolean
  keyLabel: string
  values: { value: string; label: string }[]
  /** 故事时间不针对人物 */
  needsCharacter: boolean
}

export const CORRECTION_TYPES: CorrectionTypeOption[] = [
  { type: 'life_state', label: '生死', needsKey: false, keyLabel: '', needsCharacter: true, values: [
    { value: 'survived', label: '没死 / 生还' }, { value: 'dead', label: '死亡' }, { value: 'missing', label: '失踪' }, { value: 'revived', label: '复活' },
  ] },
  { type: 'location', label: '位置', needsKey: true, keyLabel: '地点', needsCharacter: true, values: [
    { value: 'current', label: '现在在' }, { value: 'arrived', label: '抵达' }, { value: 'left', label: '离开' },
  ] },
  { type: 'realm', label: '境界 / 身份', needsKey: true, keyLabel: '境界 / 等级 / 身份', needsCharacter: true, values: [{ value: 'current', label: '现在是' }] },
  { type: 'item', label: '物品', needsKey: true, keyLabel: '物品', needsCharacter: true, values: [
    { value: 'gained', label: '持有' }, { value: 'lost', label: '已失去' },
  ] },
  { type: 'injury', label: '伤势', needsKey: true, keyLabel: '伤势', needsCharacter: true, values: [
    { value: 'injured', label: '有伤' }, { value: 'recovered', label: '已痊愈' },
  ] },
  { type: 'goal', label: '目标', needsKey: true, keyLabel: '当前目标', needsCharacter: true, values: [{ value: 'current', label: '现在是' }] },
  { type: 'ability', label: '能力', needsKey: true, keyLabel: '能力', needsCharacter: true, values: [
    { value: 'learned', label: '会了' }, { value: 'mastered', label: '掌握' }, { value: 'lost', label: '失去' }, { value: 'forgotten', label: '遗忘' },
  ] },
  { type: 'story_time', label: '故事时间', needsKey: true, keyLabel: '故事时间（如“入宗第三年·深秋”）', needsCharacter: false, values: [
    { value: 'current', label: '此时是' },
  ] },
]

export function correctionOption(type: CorrectionType): CorrectionTypeOption {
  return CORRECTION_TYPES.find((o) => o.type === type) ?? CORRECTION_TYPES[0]
}

/** 前端先挡一道（后端同样校验）；返回错误文案或 null */
export function validateCorrection(form: StateCorrectionCreate): string | null {
  const option = correctionOption(form.signal_type)
  if (option.needsCharacter && !form.character_name.trim()) return '请填写人物'
  if (!Number.isInteger(form.chapter_number) || form.chapter_number < 1) return '章号应是正整数'
  if (!option.values.some((v) => v.value === form.signal_value)) return `请选择${option.label}的状态`
  if (option.needsKey && !(form.signal_key ?? '').trim()) return `请填写${option.keyLabel}`
  return null
}

const LIFE_LABELS: Record<string, string> = { dead: '已死亡', missing: '失踪', alive: '在世', revived: '复活', survived: '在世' }
export const lifeLabel = (value: string | null | undefined) => (value ? LIFE_LABELS[value] ?? value : '在世')

const SIGNAL_VALUE_LABELS: Record<string, string> = {
  dead: '死亡', missing: '失踪', revived: '复活', survived: '生还', alive: '在世', current: '现在',
  arrived: '抵达', left: '离开', gained: '获得', lost: '失去', used: '用掉', injured: '受伤', recovered: '痊愈',
  learned: '学会', mastered: '掌握', forgotten: '遗忘', present: '出场',
}

/** 变化记录的一行：「生死：死亡」「境界：炼气五层」「物品：获得 玄铁剑」 */
export function describeSignal(row: { label: string; signal_key: string | null; signal_value: string }): string {
  const value = SIGNAL_VALUE_LABELS[row.signal_value] ?? row.signal_value
  if (!row.signal_key) return `${row.label}：${value}`
  if (row.signal_value === 'current') return `${row.label}：${row.signal_key}`
  return `${row.label}：${value} ${row.signal_key}`
}

/** 时间线按章分组（章号升序，同章事件在前、因果在后） */
export function groupTimeline(items: TimelineItem[]): { chapter: number; items: TimelineItem[] }[] {
  const groups = new Map<number, TimelineItem[]>()
  for (const item of [...items].sort((a, b) => a.chapter_number - b.chapter_number || (a.kind === 'event' ? 0 : 1) - (b.kind === 'event' ? 0 : 1))) {
    const list = groups.get(item.chapter_number) ?? []
    list.push(item)
    groups.set(item.chapter_number, list)
  }
  return [...groups.entries()].map(([chapter, list]) => ({ chapter, items: list }))
}

/** 「已用 / 预算」之类的字数提示 */
export const formatChars = (n: number) => (n >= 10000 ? `${(n / 10000).toFixed(1)} 万字` : `${n} 字`)
