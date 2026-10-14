/** 正文选区 → 正文里的精确位置（智能助笔改写 / 润色必须带上与正文逐字一致的选区）。 */

export interface TextSelection {
  start: number
  end: number
  text: string
}

/** DOM 位置与正文逐字对得上就用；对不上时按文字找，多处出现取离提示位置最近的一处；找不到返回 null。 */
export function resolveSelection(content: string, text: string, startHint: number): TextSelection | null {
  if (!text || !text.trim()) return null
  if (startHint >= 0 && content.slice(startHint, startHint + text.length) === text) {
    return { start: startHint, end: startHint + text.length, text }
  }
  let best = -1
  for (let i = content.indexOf(text); i >= 0; i = content.indexOf(text, i + 1)) {
    if (best < 0 || Math.abs(i - startHint) < Math.abs(best - startHint)) best = i
  }
  return best < 0 ? null : { start: best, end: best + text.length, text }
}

/** 读取浏览器当前选区在 container 文本里的起点（container 的文本内容须与正文一致）。 */
export function readDomSelection(container: HTMLElement | null): { text: string; startHint: number } | null {
  if (!container || typeof window === 'undefined') return null
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null
  const range = selection.getRangeAt(0)
  if (!container.contains(range.commonAncestorContainer)) return null
  const before = document.createRange()
  before.selectNodeContents(container)
  before.setEnd(range.startContainer, range.startOffset)
  return { text: range.toString(), startHint: before.toString().length }
}
