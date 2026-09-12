import type { ReasoningEffort } from '@/types'

// 统一强度档位（简单模式）
export const EFFORT_LEVELS: { value: ReasoningEffort; label: string; hint: string }[] = [
  { value: 'low', label: '低', hint: '更快 · 省 token' },
  { value: 'medium', label: '中', hint: '质量与速度平衡' },
  { value: 'high', label: '高', hint: '更深入 · 更慢' },
]

// OpenAI reasoning_effort 全部合法取值（高级模式）
export const ALL_EFFORTS: { value: ReasoningEffort; label: string }[] = [
  { value: 'none', label: 'none · 几乎不推理' },
  { value: 'minimal', label: 'minimal · 极简' },
  { value: 'low', label: 'low · 低' },
  { value: 'medium', label: 'medium · 中' },
  { value: 'high', label: 'high · 高' },
  { value: 'xhigh', label: 'xhigh · 超高' },
  { value: 'max', label: 'max · 最大' },
]

// 与后端 _REASONING_EFFORT_TO_BUDGET 一致：档位 → Anthropic budget_tokens
export const EFFORT_TO_BUDGET: Record<ReasoningEffort, number> = {
  none: 1024,
  minimal: 1024,
  low: 4096,
  medium: 8192,
  high: 16384,
  xhigh: 24576,
  max: 32000,
}

/** 预览 Anthropic 自动换算后的 budget（与后端 _resolve_thinking_budget 逻辑一致） */
export function autoBudget(effort: ReasoningEffort, maxTokens: number): number | null {
  let b = EFFORT_TO_BUDGET[effort] ?? 8192
  if (b < 1024) b = 1024
  if (maxTokens && b >= maxTokens) b = maxTokens - 1
  return b < 1024 ? null : b
}
