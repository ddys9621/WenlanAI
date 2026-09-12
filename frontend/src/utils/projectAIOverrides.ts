import type { EffectiveAIConfig, ProjectAIOverrides } from '@/types'

/** 可按项目覆盖的字段（与后端 OVERRIDE_FIELDS 一致，顺序即弹窗展示顺序） */
export const OVERRIDE_KEYS = [
  'llm_model', 'temperature', 'max_tokens', 'top_p', 'frequency_penalty',
  'presence_penalty', 'reasoning_enabled', 'reasoning_effort', 'thinking_budget_tokens',
] as const satisfies readonly (keyof ProjectAIOverrides)[]

const NUMERIC_KEYS = ['temperature', 'max_tokens', 'top_p', 'frequency_penalty', 'presence_penalty', 'thinking_budget_tokens'] as const

export function emptyOverrides(): ProjectAIOverrides {
  return {
    llm_model: null, temperature: null, max_tokens: null, top_p: null, frequency_penalty: null,
    presence_penalty: null, reasoning_enabled: null, reasoning_effort: null, thinking_budget_tokens: null,
  }
}

/** 非 null 的覆盖项个数（顶栏 chip 徽标） */
export function countActiveOverrides(o: Partial<ProjectAIOverrides> | null | undefined): number {
  if (!o) return 0
  return OVERRIDE_KEYS.filter((k) => o[k] !== null && o[k] !== undefined).length
}

/** 提交前整理：补齐缺失键为 null；模型名裁空白、空串 → null；非有限数 → null；本项目关闭思考时清掉强度 / 预算 */
export function normalizeOverrides(o: Partial<ProjectAIOverrides>): ProjectAIOverrides {
  const out = emptyOverrides()
  out.llm_model = (o.llm_model ?? '').trim() || null
  for (const k of NUMERIC_KEYS) {
    const v = o[k]
    out[k] = typeof v === 'number' && Number.isFinite(v) ? v : null
  }
  out.reasoning_enabled = typeof o.reasoning_enabled === 'boolean' ? o.reasoning_enabled : null
  const reasoningOff = out.reasoning_enabled === false
  out.reasoning_effort = reasoningOff ? null : (o.reasoning_effort ?? null)
  if (reasoningOff) out.thinking_budget_tokens = null
  return out
}

/** 顶栏 chip 文案：实际生效的模型名 */
export function modelChipLabel(effective: Pick<EffectiveAIConfig, 'llm_model'> | null | undefined): string {
  return effective?.llm_model?.trim() || '未选择模型'
}
