/**
 * 拆书 V5 视图：JSON 值 → 展示文本 的纯函数（无 React 依赖，便于单测）
 */

/** 任意 JSON 值安全转字符串（嵌套 dict / array 扁平化，避免 "[object Object]"） */
export function renderValue(v: unknown): string {
  if (v == null || v === '') return ''
  if (Array.isArray(v)) return v.map((x) => (typeof x === 'object' && x !== null ? renderValue(x) : String(x))).join('、')
  if (typeof v === 'object') {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, val]) => `${k}: ${renderValue(val)}`)
      .join('，')
  }
  return String(v)
}

export function asString(v: unknown): string {
  return typeof v === 'string' ? v : v == null ? '' : renderValue(v)
}

export function asStringList(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  return v.map((x) => asString(x)).filter(Boolean)
}

export function asRecordList<T extends Record<string, unknown>>(v: unknown): T[] {
  if (!Array.isArray(v)) return []
  return v.filter((x): x is T => typeof x === 'object' && x !== null && !Array.isArray(x))
}

export function asNumberRecord(v: unknown): Record<string, number> {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) return {}
  const out: Record<string, number> = {}
  for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
    if (typeof val === 'number' && Number.isFinite(val)) out[k] = val
  }
  return out
}

/** 0-1 比例 → "37%"；非数字 → "—" */
export function pct(v: unknown): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${Math.round(v * 100)}%` : '—'
}

/** 章号区间文案："第 3-7 章" / "第 5 章" */
export function chapterRange(start: number | undefined, end: number | undefined): string {
  if (start == null && end == null) return ''
  if (start == null || end == null || start === end) return `第 ${start ?? end} 章`
  return `第 ${start}-${end} 章`
}

const HOOK_TONE: Record<string, string> = {
  悬念: 'bg-violet-500/10 text-violet-700',
  危机: 'bg-rose-500/10 text-rose-700',
  反转: 'bg-amber-500/10 text-amber-700',
  新谜团: 'bg-sky-500/10 text-sky-700',
  信息揭露: 'bg-emerald-500/10 text-emerald-700',
  期待: 'bg-brand/10 text-brand',
  无: 'bg-surface text-content-tertiary',
}

export function hookToneClass(type: string | undefined): string {
  return HOOK_TONE[type ?? ''] ?? 'bg-surface text-content-secondary'
}

const PACE_TONE: Record<string, string> = {
  快: 'text-rose-600',
  中: 'text-content',
  慢: 'text-sky-700',
}

export function paceToneClass(pace: string | undefined): string {
  return PACE_TONE[pace ?? ''] ?? 'text-content'
}

export const CHAPTER_ROLE_LABEL: Record<string, string> = {
  intro: '起',
  build: '承',
  payoff: '爽',
  aftermath: '收',
  transition: '转',
}

export const EXCERPT_KIND_LABEL: Record<string, string> = {
  opening: '开篇',
  dialogue: '对白',
  action: '动作',
  payoff: '爽点',
  ending_hook: '章末钩子',
  description: '描写',
}

export const STYLE_METRIC_LABEL: Record<string, string> = {
  sample_chars: '采样字数',
  avg_sentence_len: '平均句长（字）',
  sentence_len_dist: '句长分布',
  avg_paragraph_len: '平均段长（字）',
  short_paragraph_pct: '短段落占比（≤30 字）',
  single_sentence_paragraph_pct: '单句成段占比',
  dialogue_char_ratio: '对白字数占比',
  dialogue_paragraph_pct: '对白段落占比',
  question_ratio: '问句比例',
  exclamation_ratio: '感叹句比例',
  terminators_per_paragraph: '每段句数',
}

/** 指标值格式化：比例键按百分比，其余原样 */
export function formatMetric(key: string, v: unknown): string {
  if (typeof v !== 'number') return renderValue(v) || '—'
  if (key.endsWith('_pct') || key.endsWith('_ratio')) return pct(v)
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}
