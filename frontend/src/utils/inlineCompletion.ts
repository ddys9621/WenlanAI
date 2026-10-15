/** 行内补全的纯文本规则：发给后端的光标上下文、段尾判定、Ctrl+→ 的「一小句」、顺着建议打字。 */

/** 与后端 inline_completion_service.PREFIX_CHARS / SUFFIX_CHARS 一致：多传了后端也会截掉 */
export const PREFIX_SEND_CHARS = 1500
export const SUFFIX_SEND_CHARS = 300

const CHUNK_END = '，,。.！!？?；;：:、…—'
const CLOSERS = '”’」』）)》】"\''
const LEADING_BREAK = /^[\n\t \u3000]*/

export function completionContext(doc: string, pos: number): { prefix: string; suffix: string } {
  return {
    prefix: doc.slice(Math.max(0, pos - PREFIX_SEND_CHARS), pos),
    suffix: doc.slice(pos, pos + SUFFIX_SEND_CHARS),
  }
}

/** 光标后同一行没有正文（只有空白或输入法自动配对的后引号 / 括号）= 在段尾，才自动要补全 */
export function restOfLineIsBlank(doc: string, pos: number): boolean {
  const end = doc.indexOf('\n', pos)
  const rest = doc.slice(pos, end < 0 ? doc.length : end)
  return [...rest].every((ch) => !ch.trim() || CLOSERS.includes(ch))
}

/** 建议里的下一小句：到下一个标点（连同紧跟的后引号）为止；段首的换行与缩进一并带上 */
export function nextChunk(text: string): string {
  const start = text.match(LEADING_BREAK)?.[0].length ?? 0
  for (let i = start; i < text.length; i++) {
    if (!CHUNK_END.includes(text[i])) continue
    let j = i + 1
    while (j < text.length && (CHUNK_END.includes(text[j]) || CLOSERS.includes(text[j]))) j++
    return text.slice(0, j)
  }
  return text
}

/** 作者打的字正好是建议的开头：返回剩下的建议（可能是空串）；否则返回 null（建议作废） */
export function consumeTyped(suggestion: string, typed: string): string | null {
  return suggestion.startsWith(typed) ? suggestion.slice(typed.length) : null
}
