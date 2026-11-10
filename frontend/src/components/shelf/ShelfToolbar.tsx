/**
 * 书架顶部的工具带（参考马良写作「我的小说」）：衬线大标题 + 一行统计，右边 导入 / 灵感模式 / 新建小说；
 * 下面一行 搜索 + 筛选 / 排序 / 分组 + 书封·列表切换；下沿一条细线铺满中栏，左端一小段朱砂。
 */
import { useRef, useState, type ReactNode } from 'react'
import { ArrowDownWideNarrow, Check, ChevronDown, Layers, LayoutGrid, List, Plus, Search, SlidersHorizontal, Sparkles, Upload, X, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDismiss } from '@/hooks/useDismiss'
import {
  GROUP_OPTIONS, SHELF_STATES, SHELF_STATE_LABEL, SORT_OPTIONS, wordCount,
  type ShelfFilter, type ShelfPrefs, type ShelfState, type ShelfSummary,
} from './shelf'

function Picker<T extends string>({
  icon: Icon,
  label,
  heading,
  active,
  value,
  options,
  onChange,
}: {
  icon: LucideIcon
  label: string
  heading: string
  active?: boolean
  value: T
  options: Array<[T, string, number?]>
  onChange: (v: T) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useDismiss(ref, open, () => setOpen(false))

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cn('shelf-tool', (active || open) && 'shelf-tool--on')}
      >
        <Icon className="h-[15px] w-[15px]" />
        {label}
        <ChevronDown className={cn('hidden h-3.5 w-3.5 opacity-60 transition-transform sm:block', open && 'rotate-180')} />
      </button>
      {open && (
        <div role="menu" aria-label={heading} className="absolute left-0 top-full z-30 mt-1.5 w-44 rounded-xl border border-surface-border-light bg-white p-1 shadow-lg animate-scale-in">
          <p className="px-2.5 pb-1 pt-1.5 text-[11px] text-content-tertiary">{heading}</p>
          {options.map(([v, text, count]) => (
            <button
              key={v}
              type="button"
              role="menuitemradio"
              aria-checked={v === value}
              onClick={() => {
                onChange(v)
                setOpen(false)
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-content hover:bg-surface-hover"
            >
              <Check className={cn('h-3.5 w-3.5 shrink-0 text-brand', v !== value && 'invisible')} />
              <span className="flex-1">{text}</span>
              {count !== undefined && <span className="text-[12px] text-content-tertiary tabular-nums">{count}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Sep() {
  return <i className="h-3 w-px bg-surface-border" aria-hidden />
}

export function ShelfToolbar({
  summary,
  counts,
  matched,
  showCreate,
  showTools,
  query,
  onQuery,
  filter,
  onFilter,
  prefs,
  onPrefs,
  onImport,
  onInspiration,
  onCreate,
}: {
  summary: ShelfSummary
  counts: Record<ShelfState, number>
  /** 搜索 / 筛选时找到几部（没在找时为 null） */
  matched: number | null
  showCreate: boolean
  showTools: boolean
  query: string
  onQuery: (q: string) => void
  filter: ShelfFilter
  onFilter: (f: ShelfFilter) => void
  prefs: ShelfPrefs
  /** 只传改了的那一项（同一时刻连点两处也不会互相覆盖） */
  onPrefs: (patch: Partial<ShelfPrefs>) => void
  onImport: () => void
  onInspiration: () => void
  onCreate: () => void
}) {
  const stats: ReactNode[] = [<span key="total">{summary.total > 0 ? `共 ${summary.total} 部作品` : '还没有作品'}</span>]
  if (summary.writing > 0) stats.push(<span key="writing">创作中 {summary.writing}</span>)
  if (summary.completed > 0) stats.push(<span key="completed">已完成 {summary.completed}</span>)
  if (summary.words > 0) stats.push(<span key="words">累计 {wordCount(summary.words)}</span>)
  if (matched !== null) stats.push(<span key="matched" className="text-brand-600">找到 {matched} 部</span>)

  const sortLabel = SORT_OPTIONS.find(([v]) => v === prefs.sort)?.[1] ?? '排序'
  const groupLabel = prefs.group === 'none' ? '分组' : GROUP_OPTIONS.find(([v]) => v === prefs.group)?.[1] ?? '分组'

  return (
    <section className="relative pb-5" aria-label="书架工具">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[26px] font-semibold leading-tight tracking-[0.02em] text-content">我的书架</h1>
          <p className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px] text-content-tertiary tabular-nums">
            {stats.flatMap((s, i) => (i === 0 ? [s] : [<Sep key={`sep-${i}`} />, s]))}
          </p>
        </div>
        {/* 手机上按钮这一行铺满：两个文字按钮平分导入图标以外的宽度 */}
        <div className="flex shrink-0 items-center gap-2 max-sm:w-full">
          <button type="button" onClick={onImport} className="shelf-tool h-10 px-3" title="导入之前导出的项目文件（JSON）">
            <Upload className="h-4 w-4" />
            <span className="hidden sm:inline">导入</span>
          </button>
          {showCreate && (
            <>
              <button type="button" onClick={onInspiration} className="hh-btn-secondary rounded-lg max-sm:flex-1">
                <Sparkles className="h-4 w-4 text-brand" />
                灵感模式
              </button>
              <button type="button" onClick={onCreate} className="hh-btn-primary rounded-lg shadow-[0_8px_18px_-10px_rgba(40,91,77,0.8)] max-sm:flex-1">
                <Plus className="h-4 w-4" />
                新建小说
              </button>
            </>
          )}
        </div>
      </div>

      {showTools && (
        <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2.5">
          <label className="relative block min-w-0 flex-[1_1_240px] sm:max-w-[420px]">
            <span className="sr-only">搜索作品</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary" />
            <input
              value={query}
              onChange={(e) => onQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape') onQuery('') }}
              placeholder="搜索书名、简介或类型"
              enterKeyHint="search"
              className="h-10 w-full !rounded-lg !border-transparent !bg-white/75 pl-9 pr-9 text-[13px] shadow-xs focus:!border-brand/40 focus:!bg-white max-sm:text-sm"
            />
            {query && (
              <button
                type="button"
                onClick={() => onQuery('')}
                aria-label="清除搜索"
                className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-hover hover:text-content"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </label>

          <div className="flex flex-wrap items-center gap-1">
            <Picker
              icon={SlidersHorizontal}
              label={filter === 'all' ? '筛选' : SHELF_STATE_LABEL[filter]}
              heading="按状态筛选"
              active={filter !== 'all'}
              value={filter}
              options={[['all', '全部作品', summary.total], ...SHELF_STATES.map((s): [ShelfFilter, string, number] => [s, SHELF_STATE_LABEL[s], counts[s]])]}
              onChange={onFilter}
            />
            <Picker icon={ArrowDownWideNarrow} label={sortLabel} heading="排序" value={prefs.sort} options={SORT_OPTIONS} onChange={(sort) => onPrefs({ sort })} />
            <Picker
              icon={Layers}
              label={groupLabel}
              heading="分组"
              active={prefs.group !== 'none'}
              value={prefs.group}
              options={GROUP_OPTIONS}
              onChange={(group) => onPrefs({ group })}
            />
            <div className="ml-1 inline-flex items-center rounded-lg bg-surface-hover p-0.5" role="group" aria-label="显示方式">
              {([['grid', LayoutGrid, '书封'], ['list', List, '列表']] as const).map(([view, Icon, text]) => (
                <button
                  key={view}
                  type="button"
                  onClick={() => onPrefs({ view })}
                  aria-pressed={prefs.view === view}
                  title={`${text}视图`}
                  aria-label={`${text}视图`}
                  className={cn(
                    'flex h-8 w-8 items-center justify-center rounded-md transition-colors',
                    prefs.view === view ? 'bg-white text-content shadow-xs' : 'text-content-tertiary hover:text-content',
                  )}
                >
                  <Icon className="h-4 w-4" />
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="shelf-rule" aria-hidden />
    </section>
  )
}
