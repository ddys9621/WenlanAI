/** 稿纸「查找与替换」条（参考岚笺）：纯文本逐字匹配；全部替换是一次可撤销的修改。 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { findMatches } from '@/utils/manuscript'

interface Props {
  content: string
  onSelect: (from: number, to: number) => void
  onReplace: (starts: number[], length: number, replacement: string) => void
  onClose: () => void
}

export function ManuscriptFindBar({ content, onSelect, onReplace, onClose }: Props) {
  const [query, setQuery] = useState('')
  const [replacement, setReplacement] = useState('')
  const [index, setIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const matches = useMemo(() => findMatches(content, query), [content, query])
  const current = matches.length ? Math.min(index, matches.length - 1) : -1

  useEffect(() => { inputRef.current?.focus() }, [])

  const go = (next: number) => {
    if (!matches.length) return
    const i = (next + matches.length) % matches.length
    setIndex(i)
    onSelect(matches[i], matches[i] + query.length)
  }

  const field = 'h-7 w-32 rounded border border-surface-border bg-white px-2 text-xs text-content focus:border-brand focus:outline-none'

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); go(current + 1) }}
      onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClose() } }}
      className="flex flex-wrap items-center gap-x-2 gap-y-1.5 border-b border-surface-border bg-surface-paper px-3 py-2 text-xs text-content-secondary"
    >
      <label className="flex items-center gap-1.5">
        查找
        <input ref={inputRef} value={query} onChange={(e) => { setQuery(e.target.value); setIndex(0) }} className={field} aria-label="查找正文" autoComplete="off" />
      </label>
      <span className="w-16 tabular-nums text-content-tertiary" aria-live="polite">
        {query ? (matches.length ? `${current + 1} / ${matches.length}` : '没有匹配') : ''}
      </span>
      <button type="button" onClick={() => go(current - 1)} disabled={!matches.length} className="hh-btn-ghost hh-btn-sm">上一处</button>
      <button type="submit" disabled={!matches.length} className="hh-btn-ghost hh-btn-sm">下一处</button>
      <label className="ml-2 flex items-center gap-1.5">
        替换
        <input value={replacement} onChange={(e) => setReplacement(e.target.value)} className={field} aria-label="替换为" autoComplete="off" />
      </label>
      <button
        type="button"
        disabled={current < 0}
        onClick={() => onReplace([matches[current]], query.length, replacement)}
        className="hh-btn-ghost hh-btn-sm"
      >
        替换
      </button>
      <button type="button" disabled={!matches.length} onClick={() => onReplace(matches, query.length, replacement)} className="hh-btn-ghost hh-btn-sm">
        全部替换
      </button>
      <button type="button" onClick={onClose} className="hh-btn-ghost hh-btn-sm ml-auto">关闭</button>
    </form>
  )
}
