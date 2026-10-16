/** 共创室上下文用量的显示：token 数缩写、用量档位、悬停说明、上限选项。 */
import type { AssistantContextSource, AssistantContextUsage } from '@/types/assistant'

const short = (x: number) => (x < 10 ? x.toFixed(1).replace(/\.0$/, '') : String(Math.round(x)))

/** 950 → 950；1500 → 1.5K；87400 → 87K；1000000 → 1M */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${short(n / 1_000_000)}M`
  if (n >= 1_000) return `${short(n / 1_000)}K`
  return String(Math.round(n))
}

export type UsageTone = 'ok' | 'warn' | 'full'

export function usageTone(percent: number): UsageTone {
  return percent >= 90 ? 'full' : percent >= 70 ? 'warn' : 'ok'
}

export function sourceText(source: AssistantContextSource, model: string, tokens: number): string {
  if (source === 'manual') return `你设的上限 ${formatTokens(tokens)}`
  if (source === 'auto') return `自动：按模型 ${model} 查到 ${formatTokens(tokens)}`
  return `自动：没认出模型「${model || '未设置'}」，按默认 ${formatTokens(tokens)}`
}

const PART_LABELS: [keyof AssistantContextUsage['parts'], string][] = [
  ['system', '规则与工具'], ['book', '本书与页面'], ['summary', '前情摘要'], ['history', '近期对话'],
  ['steps', '本轮处理记录'], ['goal', '本轮要求'],
]

/** 用量表的悬停说明：用量、上限来源、分项、历史带了多少 / 压了多少 / 截了多少 */
export function usageTitle(u: AssistantContextUsage): string {
  const { included, total, summarized } = u.history
  const dropped = total - included - summarized
  let history = `近期对话带入 ${included} 条`
  if (summarized) history += `，较早的 ${summarized} 条已压成前情摘要`
  if (dropped > 0) history += `，还有 ${dropped} 条这次没装下`
  const lines = [
    `上下文约 ${formatTokens(u.used)} / ${formatTokens(u.limit)} token（${u.percent}%，估算）`,
    sourceText(u.source, u.model, u.limit),
    PART_LABELS.filter(([key]) => u.parts[key] > 0).map(([key, label]) => `${label} ${formatTokens(u.parts[key])}`).join(' · '),
    `给回复预留 ${formatTokens(u.reserve)}`,
    history,
  ]
  if (u.compressed_steps) lines.push(`本轮有 ${u.compressed_steps} 步工具结果压成了一句`)
  if (u.will_compact) lines.push(`发送时会先把较早的 ${u.will_compact} 条对话压成前情摘要`)
  return lines.join('\n')
}

/** 上限下拉框的值：'' = 自动，预设值原样，其余算 'custom' */
export function windowChoice(setting: number | null, presets: number[]): string {
  if (!setting) return ''
  return presets.includes(setting) ? String(setting) : 'custom'
}

/** 自定义上限：按 K 填（100 = 100K），也认 K / M 后缀；格式不对或超出范围返回 null */
export function parseWindowInput(input: string, min: number, max: number): number | null {
  const match = input.trim().match(/^(\d+(?:\.\d+)?)\s*([kKmM]?)$/)
  if (!match) return null
  const value = Math.round(Number(match[1]) * (match[2].toLowerCase() === 'm' ? 1_000_000 : 1_000))
  return value >= min && value <= max ? value : null
}
