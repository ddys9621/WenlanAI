/**
 * 书架上的一本书（参考马良写作「我的小说」）：书封视图 = 书封 + 书名 / 简介 / 字数·类型 / 更新时间；
 * 列表视图 = 小书封 + 一行信息。右上角「⋯」：打开 / 导出项目 / 导出 TXT / 删除（书封视图悬停才出来，触屏常显）。
 */
import { useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react'
import { BookOpen, Clock, Download, FileText, MoreHorizontal, Trash2, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDismiss } from '@/hooks/useDismiss'
import type { Project } from '@/types'
import { BookCover, StateBadge } from './BookCover'
import { displayTitle, formatRelativeTime, genresOf, shelfStateOf, wordCount, type ShelfView } from './shelf'

export interface BookActions {
  onOpen: () => void
  onExport: () => void
  onExportTxt: () => void
  onDelete: () => void
}

function MenuItem({ icon: Icon, danger, onClick, children }: { icon: LucideIcon; danger?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={cn(
        'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px]',
        danger ? 'text-cinnabar hover:bg-cinnabar-wash' : 'text-content hover:bg-surface-hover',
      )}
    >
      <Icon className={cn('h-4 w-4', danger ? '' : 'text-content-secondary')} />
      {children}
    </button>
  )
}

function CardMenu({ open, onOpenChange, actions, className }: { open: boolean; onOpenChange: (v: boolean) => void; actions: BookActions; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  // 卡片靠近窗口底边时往上弹，免得菜单落到视野外
  const [up, setUp] = useState(false)
  useDismiss(ref, open, () => onOpenChange(false))

  const toggle = () => {
    if (!open && ref.current) setUp(window.innerHeight - ref.current.getBoundingClientRect().bottom < 220)
    onOpenChange(!open)
  }
  const run = (fn: () => void) => () => {
    onOpenChange(false)
    fn()
  }
  // 菜单里的点击、回车不能冒泡到卡片（卡片点了就进项目）
  const stop = (e: MouseEvent | KeyboardEvent) => e.stopPropagation()

  return (
    <div ref={ref} className={className} onClick={stop} onKeyDown={stop}>
      <button
        type="button"
        onClick={toggle}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="作品操作"
        title="更多操作"
        className="flex h-8 w-8 items-center justify-center rounded-full bg-white/85 text-content-secondary shadow-xs backdrop-blur-sm hover:bg-white hover:text-content"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {open && (
        <div
          role="menu"
          className={cn(
            'absolute right-0 z-30 w-40 rounded-xl border border-surface-border-light bg-white p-1 shadow-lg animate-scale-in',
            up ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
          )}
        >
          <MenuItem icon={BookOpen} onClick={run(actions.onOpen)}>打开</MenuItem>
          <MenuItem icon={Download} onClick={run(actions.onExport)}>导出项目</MenuItem>
          <MenuItem icon={FileText} onClick={run(actions.onExportTxt)}>导出 TXT</MenuItem>
          <div className="my-1 h-px bg-surface-border-light" role="separator" />
          <MenuItem icon={Trash2} danger onClick={run(actions.onDelete)}>删除</MenuItem>
        </div>
      )}
    </div>
  )
}

function Meta({ project, className }: { project: Project; className?: string }) {
  const genres = genresOf(project.genre)
  return (
    <p className={cn('flex min-w-0 items-center gap-1.5 tabular-nums', className)}>
      <span className="shrink-0">{wordCount(project.current_words || 0)}</span>
      {genres.length > 0 && (
        <>
          <i className="h-0.5 w-0.5 shrink-0 rounded-full bg-current opacity-50" aria-hidden />
          <span className="truncate">{genres.join(' · ')}</span>
        </>
      )}
    </p>
  )
}

export function BookCard({ project, view, ...actions }: { project: Project; view: ShelfView } & BookActions) {
  const [menuOpen, setMenuOpen] = useState(false)
  const title = displayTitle(project.title)
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.target !== e.currentTarget || (e.key !== 'Enter' && e.key !== ' ')) return
    e.preventDefault()
    actions.onOpen()
  }
  const card = {
    role: 'button',
    tabIndex: 0,
    onClick: actions.onOpen,
    onKeyDown,
    'aria-label': `打开《${title}》`,
  } as const
  const updated = formatRelativeTime(project.updated_at)

  if (view === 'list') {
    return (
      <article
        {...card}
        className={cn(
          'group relative flex cursor-pointer gap-4 rounded-2xl border border-surface-border-light bg-white/70 p-3 shadow-xs transition-colors hover:border-surface-border hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30',
          menuOpen && 'z-20',
        )}
      >
        <BookCover project={project} size="sm" className="w-[72px] shrink-0 sm:w-[84px]" />
        <div className="flex min-w-0 flex-1 flex-col justify-center gap-1.5 py-0.5 pr-10">
          <div className="flex min-w-0 items-center gap-2">
            <h3 className="truncate font-serif text-[17px] font-semibold text-content transition-colors group-hover:text-brand">{title}</h3>
            <StateBadge state={shelfStateOf(project)} className="bg-surface text-content-secondary" />
          </div>
          <p className="line-clamp-2 text-[13px] leading-[1.65] text-content-secondary">{project.description || '还没有简介'}</p>
          <div className="flex min-w-0 items-center gap-4 text-[12px] text-content-tertiary">
            <Meta project={project} />
            {updated && (
              <span className="inline-flex shrink-0 items-center gap-1">
                <Clock className="h-3 w-3" />
                {updated}
              </span>
            )}
          </div>
        </div>
        <CardMenu open={menuOpen} onOpenChange={setMenuOpen} actions={actions} className="absolute right-3 top-3" />
      </article>
    )
  }

  return (
    <article {...card} className={cn('group relative flex cursor-pointer flex-col focus-visible:outline-none', menuOpen && 'z-20')}>
      <div className="relative transition-transform duration-200 group-hover:-translate-y-1 group-focus-visible:-translate-y-1">
        <BookCover
          project={project}
          className="w-full transition-shadow duration-200 group-hover:shadow-md group-focus-visible:ring-2 group-focus-visible:ring-brand/40"
        />
        <CardMenu
          open={menuOpen}
          onOpenChange={setMenuOpen}
          actions={actions}
          className={cn(
            'absolute right-2 top-2 transition-opacity focus-within:opacity-100 group-hover:opacity-100 [@media(pointer:coarse)]:opacity-100',
            menuOpen ? 'opacity-100' : 'opacity-0',
          )}
        />
      </div>
      <div className="mt-3 min-w-0 px-0.5">
        <h3 className="line-clamp-1 font-serif text-[15px] font-semibold leading-snug text-content transition-colors group-hover:text-brand">{title}</h3>
        <p className="mt-1 line-clamp-2 text-[12px] leading-[1.6] text-content-tertiary">{project.description || '还没有简介'}</p>
        <Meta project={project} className="mt-1.5 text-[12px] text-content-secondary" />
        {updated && (
          <p className="mt-1 flex items-center gap-1 text-[11px] text-content-tertiary">
            <Clock className="h-3 w-3" />
            {updated}
          </p>
        )}
      </div>
    </article>
  )
}
