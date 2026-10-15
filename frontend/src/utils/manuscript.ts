/** 稿纸正文的纯文本工具：字数（与后端 count_words 一致）、段数、一键排版、回车续段、查找。 */

const CJK = /[\u4e00-\u9fff]/g
const LEADING_SPACE = /^[\t \u3000]+/

export interface ParagraphFormat {
  firstLineIndent: boolean
  paragraphSpacing: boolean
}

/** 汉字各算 1 字，连续英文字母 / 连续数字各算 1 字，标点与空白不计（对齐 backend/app/utils/text_utils.count_words） */
export function countWords(text: string): number {
  if (!text) return 0
  const chinese = text.match(CJK)?.length ?? 0
  const rest = text.replace(CJK, ' ')
  return chinese + (rest.match(/[a-zA-Z]+/g)?.length ?? 0) + (rest.match(/\p{Nd}+/gu)?.length ?? 0)
}

/** 非空行就是一段（与后端局部重写的分段一致：单换行、空行分段都认） */
export function countParagraphs(text: string): number {
  return text.split('\n').filter((line) => line.trim()).length
}

/** 一键排版：逐行去首尾空白（含全角空格），按版式统一首行缩进与段间空行；不猜相邻行是否同一段 */
export function formatParagraphs(text: string, format: ParagraphFormat = { firstLineIndent: true, paragraphSpacing: true }): string {
  const indent = format.firstLineIndent ? '\u3000\u3000' : ''
  return text
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((line) => line.trim().replace(LEADING_SPACE, ''))
    .filter(Boolean)
    .map((line) => indent + line)
    .join(format.paragraphSpacing ? '\n\n' : '\n')
}

/** 回车续段：按版式插入的分段符（段间空行 + 首行缩进） */
export function paragraphBreak(format: ParagraphFormat): string {
  return (format.paragraphSpacing ? '\n\n' : '\n') + (format.firstLineIndent ? '\u3000\u3000' : '')
}

/** 查找：所有不重叠的出现位置 */
export function findMatches(text: string, query: string): number[] {
  if (!query) return []
  const hits: number[] = []
  for (let i = text.indexOf(query); i >= 0; i = text.indexOf(query, i + query.length)) hits.push(i)
  return hits
}
