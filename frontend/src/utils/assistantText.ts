/** 智能助笔的文本工具：修改候选的前后对比（按句子）、引用 / 快捷入口填入输入框、字段值显示。 */

/** 后端每轮带入的历史条数上限（与 assistant_agent_service.HISTORY_LIMIT 一致） */
export const HISTORY_LIMIT = 12

export interface DiffBlock {
  kind: 'same' | 'change'
  before: string
  after: string
}

const SENTENCE = /[^。！？!?；;\n]*[。！？!?；;\n]+|[^。！？!?；;\n]+$/g
const MAX_CELLS = 160_000

function sentences(text: string): string[] {
  return text.match(SENTENCE) ?? (text ? [text] : [])
}

function prefixSuffix(before: string, after: string): DiffBlock[] {
  let start = 0
  while (start < before.length && start < after.length && before[start] === after[start]) start += 1
  let end = 0
  while (end < before.length - start && end < after.length - start
    && before[before.length - 1 - end] === after[after.length - 1 - end]) end += 1
  const blocks: DiffBlock[] = []
  if (start) blocks.push({ kind: 'same', before: before.slice(0, start), after: after.slice(0, start) })
  blocks.push({ kind: 'change', before: before.slice(start, before.length - end), after: after.slice(start, after.length - end) })
  if (end) blocks.push({ kind: 'same', before: before.slice(before.length - end), after: after.slice(after.length - end) })
  return blocks
}

/** 按句子做最长公共子序列：只标出改动的句子，其余原样 */
export function diffBlocks(before: string, after: string): DiffBlock[] {
  if (before === after) return [{ kind: 'same', before, after }]
  const a = sentences(before)
  const b = sentences(after)
  if (a.length * b.length > MAX_CELLS) return prefixSuffix(before, after)
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const blocks: DiffBlock[] = []
  const push = (kind: DiffBlock['kind'], x: string, y: string) => {
    const last = blocks[blocks.length - 1]
    if (last && last.kind === kind) {
      last.before += x
      last.after += y
    } else {
      blocks.push({ kind, before: x, after: y })
    }
  }
  let i = 0
  let j = 0
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      push('same', a[i], b[j])
      i += 1
      j += 1
    } else if (j < b.length && (i >= a.length || dp[i][j + 1] >= dp[i + 1][j])) {
      push('change', '', b[j])
      j += 1
    } else {
      push('change', a[i], '')
      i += 1
    }
  }
  return blocks
}

/** 把一段文字以引用格式追加到输入框，已有草稿保留 */
export function appendQuote(draft: string, text: string): string {
  const quoted = `${text.split('\n').map((line) => `> ${line}`).join('\n')}\n\n`
  return draft.trim() ? `${draft.replace(/\s+$/, '')}\n\n${quoted}` : quoted
}

/** 快捷入口只填入要求：空输入直接填，已有草稿则追加，已经有了就不重复 */
export function appendRequest(draft: string, text: string): string {
  if (!draft.trim()) return text
  if (draft.includes(text)) return draft
  return `${draft.replace(/\s+$/, '')}\n${text}`
}

export function formatFieldValue(value: unknown): string {
  if (Array.isArray(value)) return value.join('\n')
  if (value === null || value === undefined) return ''
  return String(value)
}
