import type { ReaderLine } from '@/types'

type ReaderKey = keyof ReaderLine
export type ReaderForm = Record<ReaderKey, string>

/** 章纲读者线的三句话：顺序、叫法和后端 narrative_tasks 的 READER_KEYS / READER_LABELS 一致 */
export const READER_FIELDS: { key: ReaderKey; label: string; hint: string }[] = [
  { key: 'waiting', label: '读者在等', hint: '读者带着什么期待读这一章（他最想看到哪件事）' },
  { key: 'payoff', label: '本章兑现', hint: '这一章给读者的；蓄势章写把哪个期待推近了哪一步' },
  { key: 'gap', label: '信息差', hint: '读者知道而场内谁不知道什么；写明本章保持还是揭开' },
]

export function readerForm(reader?: ReaderLine | null): ReaderForm {
  return { waiting: reader?.waiting ?? '', payoff: reader?.payoff ?? '', gap: reader?.gap ?? '' }
}

/** 表单 → 请求体：三栏都带上，清空的那句后端会删掉 */
export function readerPayload(form: ReaderForm): Required<ReaderLine> {
  return { waiting: form.waiting.trim(), payoff: form.payoff.trim(), gap: form.gap.trim() }
}

export function readerRows(reader?: ReaderLine | null): { label: string; text: string }[] {
  return READER_FIELDS
    .map((f) => ({ label: f.label, text: (reader?.[f.key] ?? '').trim() }))
    .filter((row) => row.text)
}
