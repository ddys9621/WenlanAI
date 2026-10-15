/** 共创室（智能助笔）的纯函数：@成员 提及、成员配色、草案卡片的确认对象与跳转。 */
import type { AssistantPlan, AssistantRunView } from '@/types/assistant'

/** 开头的「@成员」（与后端 cocreation_team.parse_mention 的写法一致：@名称 + 空白或标点） */
const LEADING_MENTION = /^\s*@\S+?[\s，,:：]+/

/** 草稿开头放上「@成员」；已有提及就换掉；选主编则去掉提及（主编默认发言） */
export function mentionMember(draft: string, memberName: string): string {
  const rest = draft.replace(LEADING_MENTION, '')
  return memberName === '主编' ? rest : `@${memberName} ${rest}`
}

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
