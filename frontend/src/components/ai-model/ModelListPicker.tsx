import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { Check, ChevronDown, ChevronUp, Loader2, RefreshCw, Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { AIModelOption } from '@/types'
import { displayName, filterModels, groupModels } from '@/utils/modelList'

/**
 * 模型选择：上方是自由输入的模型名（永远是真值），下方可展开一个内嵌面板——带搜索框、按 vendor 分组、
 * 键盘上下 / 回车选择。不用原生 datalist（它会按输入框现有文本过滤候选，预填全局模型后只剩同前缀几个），
 * 也不用浮层（弹窗 body 可滚动，浮层会被裁切）。
 */
export function ModelListPicker({
  value,
  onChange,
  models,
  loading,
  onRefresh,
}: {
  value: string
  onChange: (v: string) => void
  models: AIModelOption[]
  loading: boolean
  onRefresh: () => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [highlight, setHighlight] = useState(0)
  const searchRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const filtered = useMemo(() => filterModels(models, query), [models, query])
  const groups = useMemo(() => groupModels(filtered), [filtered])
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups])

  useEffect(() => {
    setHighlight(Math.max(0, flat.findIndex((m) => m.value === value)))
  }, [flat, value, open])

  useEffect(() => {
    if (open) searchRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    listRef.current?.querySelector<HTMLElement>(`[data-index="${highlight}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [highlight, open])

  const pick = (v: string) => {
    onChange(v)
    setOpen(false)
    setQuery('')
  }

  const onSearchKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight((h) => Math.min(h + 1, Math.max(flat.length - 1, 0)))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight((h) => Math.max(h - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const hit = flat[highlight]
      if (hit) pick(hit.value)
      else if (query.trim()) pick(query.trim())
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
      setQuery('')
    }
  }

  let index = -1

  return (
    <div>
      <div className="flex gap-2">
        <input
          className="hh-field flex-1 border border-surface-border bg-white font-mono text-[13px]"
          placeholder="输入模型名，如 gpt-4o / deepseek-chat / claude-sonnet-4-5"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <button type="button" className="hh-icon-btn h-11 w-11" onClick={onRefresh} disabled={loading} title="刷新模型列表">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
        </button>
      </div>

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={models.length === 0 && !loading}
        className={cn(
          'mt-2 flex w-full items-center justify-between border px-3 py-2 text-left text-xs transition-colors',
          open ? 'border-brand/50 bg-brand/[0.06] text-brand' : 'border-surface-border bg-white/60 text-content-secondary hover:border-brand/40 hover:text-content',
          'disabled:cursor-not-allowed disabled:opacity-60',
        )}
      >
        <span>
          {loading && models.length === 0
            ? '正在从已保存接口拉取模型列表…'
            : models.length === 0
              ? '接口未返回模型列表，请直接在上方输入模型名'
              : `从已拉取的 ${models.length} 个模型中选择`}
        </span>
        {open ? <ChevronUp className="h-3.5 w-3.5 shrink-0" /> : <ChevronDown className="h-3.5 w-3.5 shrink-0" />}
      </button>

      {open && (
        <div className="border border-t-0 border-brand/50 bg-white">
          <div className="relative border-b border-surface-border">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary" />
            <input
              ref={searchRef}
              className="h-10 w-full bg-transparent pl-9 pr-3 text-sm outline-none"
              placeholder={`搜索 ${models.length} 个模型… （↑↓ 选择，回车确认，Esc 关闭）`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onSearchKeyDown}
            />
          </div>

          <div ref={listRef} className="max-h-64 overflow-y-auto py-1" role="listbox">
            {flat.length === 0 && (
              <p className="px-3 py-4 text-center text-xs text-content-tertiary">
                没有匹配「{query.trim()}」的模型；回车可直接使用这个名字。
              </p>
            )}
            {groups.map((g) => (
              <div key={g.group ?? '__flat'}>
                {g.group && (
                  <p className="sticky top-0 z-[1] bg-white/95 px-3 pb-1 pt-2 font-mono text-[11px] font-semibold text-content-tertiary backdrop-blur-sm">
                    {g.group}
                    <span className="ml-1.5 font-sans font-normal">{g.items.length}</span>
                  </p>
                )}
                {g.items.map((m) => {
                  index += 1
                  const i = index
                  const selected = m.value === value
                  const active = i === highlight
                  return (
                    <button
                      key={m.value}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      data-index={i}
                      title={m.value}
                      onMouseEnter={() => setHighlight(i)}
                      onClick={() => pick(m.value)}
                      className={cn(
                        'flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] transition-colors',
                        active ? 'bg-brand/[0.08]' : '',
                        selected ? 'font-medium text-brand' : 'text-content',
                      )}
                    >
                      <Check className={cn('h-3.5 w-3.5 shrink-0', selected ? 'opacity-100' : 'opacity-0')} />
                      <span className="truncate font-mono">{displayName(m, g.group)}</span>
                    </button>
                  )
                })}
              </div>
            ))}
          </div>

          {query.trim() && flat.length > 0 && (
            <p className="border-t border-surface-border px-3 py-1.5 text-[11px] text-content-tertiary">
              显示 {flat.length} / {models.length} 个
            </p>
          )}
        </div>
      )}
    </div>
  )
}
