/**
 * 项目工作台左栏：
 * 头部 = 作品名（点开看作品概况、回书架、切换作品）+ 数据修复 + 收起；下面「设定 / 大纲 / 目录 / 资料」四个页签；
 * 页签里是搜索 + 共创室按钮、计数行、页面入口卡片。目录页签：章节写作页把自己的章节目录挂进 directorySlot
 * （状态和按钮都还在页面里），在别的页面这里列出章节、点了跳到章节写作；底栏 = 当前用户 + 运行日志（桌面版）+ 回书架。
 */
import { useEffect, useRef, useState, type ReactNode, type Ref } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  BookText, ChevronDown, LayoutGrid, Library, PanelLeftClose, Rows3, ScrollText, Search, Settings, Sparkles, UserRound,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Chapter, Project } from '@/types'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { useDesktopApi } from '@/hooks/useDesktopApi'
import {
  NAV_TABS, PROJECT_STATUS_META, entryOf, filterChapters, filterEntries, formatCount, isFullBleed, type NavEntry, type NavTabKey,
  type ProjectStats,
} from './projectNav'

const SEARCH_HINT: Record<NavTabKey, string> = {
  setting: '搜索设定…',
  outline: '搜索大纲…',
  directory: '搜索章节…',
  library: '搜索资料…',
}

const DENSE_KEY = 'project-nav-dense'

/** 入口卡片上的计数（没加载过的卷纲 / 章纲不写 0，免得像是真没有） */
function entryTags(path: string, stats: ProjectStats): string[] {
  switch (path) {
    case 'characters':
      return [`人物 ${stats.people}`, `组织 ${stats.organizations}`]
    case 'outline':
      return stats.outlines ? [`${stats.outlines} 个版本`] : []
    case 'outline/volumes':
      return stats.volumes ? [`${stats.volumes} 卷`] : []
    case 'outline/chapters':
      return stats.chapterOutlines ? [`${stats.chapterOutlines} 章`] : []
    case 'chapter-analysis':
      return [`${stats.chapters} 章`, `${formatCount(stats.words)} 字`]
    default:
      return []
  }
}

function tabCounts(tab: NavTabKey, stats: ProjectStats): string[] {
  if (tab === 'setting') return [`角色 ${stats.people}`, `组织 ${stats.organizations}`]
  if (tab === 'outline') {
    return [`总纲 ${stats.outlines}`, ...(stats.volumes ? [`卷纲 ${stats.volumes}`] : []), ...(stats.chapterOutlines ? [`章纲 ${stats.chapterOutlines}`] : [])]
  }
  if (tab === 'directory') return [`${stats.chapters} 章`, `${formatCount(stats.words)} 字`]
  return []
}

interface ProjectSidebarProps {
  projectId: string
  project: Project | null
  projects: Project[]
  stats: ProjectStats
  chapters: Chapter[]
  tab: NavTabKey
  onTabChange: (tab: NavTabKey) => void
  searchRef: Ref<HTMLInputElement>
  onDirectorySlot: (el: HTMLDivElement | null) => void
  onCollapse: () => void
  onOpenRepair: () => void
  onAskAssistant: () => void
}

export function ProjectSidebar({
  projectId, project, projects, stats, chapters, tab, onTabChange, searchRef, onDirectorySlot, onCollapse, onOpenRepair,
  onAskAssistant,
}: ProjectSidebarProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const user = useCurrentUser()
  const desktop = useDesktopApi()
  const [search, setSearch] = useState('')
  const [dense, setDense] = useState(() => typeof localStorage !== 'undefined' && localStorage.getItem(DENSE_KEY) === 'true')
  const chapterPage = isFullBleed(location.pathname)
  const current = entryOf(location.pathname)
  const activeTab = NAV_TABS.find((t) => t.key === tab) ?? NAV_TABS[0]
  const counts = tabCounts(tab, stats)
  const showSearch = !(tab === 'directory' && chapterPage)

  useEffect(() => { setSearch('') }, [tab])

  const toggleDense = (next: boolean) => {
    setDense(next)
    localStorage.setItem(DENSE_KEY, String(next))
  }

  return (
    <div className="ws-sidebar">
      <header className="flex h-14 shrink-0 items-center gap-1 border-b border-surface-border px-3">
        <ProjectMenu projectId={projectId} project={project} projects={projects} stats={stats} />
        <button onClick={onOpenRepair} className="ws-icon-btn" title="数据修复：检查并修复项目数据里的不一致">
          <Settings className="h-4 w-4" />
        </button>
        <button onClick={onCollapse} className="ws-icon-btn" title="收起侧栏">
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </header>

      <nav className="ws-tabs" aria-label="项目内容">
        {NAV_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => onTabChange(t.key)}
            aria-pressed={tab === t.key}
            className={cn('ws-tab', tab === t.key && 'ws-tab--on')}
          >
            <t.icon className="h-3.5 w-3.5 shrink-0" />
            {t.label}
          </button>
        ))}
      </nav>

      {showSearch && (
        <div className="shrink-0 space-y-1.5 px-3 pb-2 pt-1.5">
          <div className="flex items-center gap-2">
            <label className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary" />
              <input
                ref={searchRef}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Escape') setSearch('') }}
                placeholder={SEARCH_HINT[tab]}
                aria-label={SEARCH_HINT[tab]}
                className="ws-search"
              />
            </label>
            <button onClick={onAskAssistant} className="ws-add" title="让共创室帮你写（Alt+A）" aria-label="让共创室帮你写">
              <Sparkles className="h-4 w-4" />
            </button>
          </div>
          <div className="flex min-h-[28px] items-center justify-between gap-2">
            <div className="flex min-w-0 flex-wrap gap-1">
              {counts.map((c) => <span key={c} className="ws-count">{c}</span>)}
            </div>
            {tab !== 'directory' && (
              <div className="flex shrink-0 items-center">
                <button onClick={() => toggleDense(true)} aria-pressed={dense} className={cn('ws-icon-btn h-7 w-7', dense && 'ws-icon-btn--on')} title="紧凑列表">
                  <Rows3 className="h-3.5 w-3.5" />
                </button>
                <button onClick={() => toggleDense(false)} aria-pressed={!dense} className={cn('ws-icon-btn h-7 w-7', !dense && 'ws-icon-btn--on')} title="卡片">
                  <LayoutGrid className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="relative flex min-h-0 flex-1 flex-col">
        {tab !== 'directory' && (
          <EntryList entries={filterEntries(activeTab.entries, search)} current={current} stats={stats} dense={dense} keyword={search} />
        )}
        {tab === 'directory' && !chapterPage && (
          <ChapterDirectory
            chapters={filterChapters(chapters, search)}
            total={chapters.length}
            onOpen={(id) => navigate(`/project/${projectId}/chapter-analysis${id ? `?chapter=${id}` : ''}`)}
          />
        )}
        <div ref={onDirectorySlot} className={cn('flex min-h-0 flex-1 flex-col', !(tab === 'directory' && chapterPage) && 'hidden')} />
      </div>

      <footer className="flex h-[49px] shrink-0 items-center gap-0.5 border-t border-surface-border px-2">
        <NavLink to="/settings" className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1 py-1 hover:bg-surface-hover" title="设置">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-muted text-content-secondary">
            <UserRound className="h-4 w-4" />
          </span>
          <span className="truncate text-[12px] text-content-secondary">{user?.display_name || user?.username || '本地用户'}</span>
        </NavLink>
        {desktop && (
          <button onClick={() => void desktop.open_logs()} className="ws-icon-btn" title="运行日志">
            <ScrollText className="h-4 w-4" />
          </button>
        )}
        <button onClick={() => navigate('/')} className="ws-icon-btn" title="返回书架">
          <Library className="h-4 w-4" />
        </button>
      </footer>
    </div>
  )
}

function EntryList({ entries, current, stats, dense, keyword }: {
  entries: NavEntry[]
  current: NavEntry | undefined
  stats: ProjectStats
  dense: boolean
  keyword: string
}) {
  if (!entries.length) {
    return <p className="px-4 py-8 text-center text-[12px] text-content-tertiary">没有和「{keyword.trim()}」相关的页面</p>
  }
  return (
    <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
      {entries.map((entry) => {
        const on = current?.path === entry.path
        const tags = entryTags(entry.path, stats)
        return (
          <NavLink key={entry.path} to={entry.path} className={cn('ws-card', dense && 'ws-card--dense', on && 'ws-card--on')} aria-current={on ? 'page' : undefined}>
            <span className={cn('ws-card-icon', on && 'text-brand')}>
              <entry.icon className={dense ? 'h-4 w-4' : 'h-[22px] w-[22px]'} strokeWidth={dense ? 2 : 1.5} />
            </span>
            <span className="min-w-0 flex-1">
              <span className={cn('ws-card-title', on && 'text-brand-600')}>{entry.label}</span>
              {!dense && <span className="ws-card-desc">{entry.desc}</span>}
              {!dense && tags.length > 0 && (
                <span className="mt-1.5 flex flex-wrap gap-1">
                  {tags.map((t, i) => <span key={t} className={i === 0 ? 'ws-tag ws-tag--main' : 'ws-tag'}>{t}</span>)}
                </span>
              )}
            </span>
            {dense && tags[0] && <span className="shrink-0 text-[11px] tabular-nums text-content-tertiary">{tags[0]}</span>}
          </NavLink>
        )
      })}
    </div>
  )
}

/** 不在章节写作页时的目录：列出章节，点了跳过去（章节写作页按 ?chapter= 选中） */
function ChapterDirectory({ chapters, total, onOpen }: { chapters: Chapter[]; total: number; onOpen: (id?: string) => void }) {
  const sorted = [...chapters].sort((a, b) => a.chapter_number - b.chapter_number)
  if (!total) {
    return (
      <div className="flex flex-col items-center px-6 py-10 text-center">
        <p className="text-[13px] font-medium text-content">还没有章节</p>
        <p className="mt-1.5 text-[12px] leading-5 text-content-tertiary">在章节写作里从章纲同步，或直接新建一章开写。</p>
        <button onClick={() => onOpen()} className="hh-btn-secondary hh-btn-sm mt-4">去章节写作</button>
      </div>
    )
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
      {sorted.map((c) => (
        <button key={c.id} onClick={() => onOpen(c.id)} className="ws-chapter-row">
          <span className="w-6 shrink-0 text-right text-[11px] tabular-nums text-content-tertiary">{c.chapter_number}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] text-content">{c.title}</span>
            <span className="block text-[11px] tabular-nums text-content-tertiary">{c.word_count > 0 ? `${c.word_count.toLocaleString()} 字` : '空'}</span>
          </span>
        </button>
      ))}
      {!sorted.length && <p className="px-3 py-6 text-center text-[12px] text-content-tertiary">没有匹配的章节</p>}
    </div>
  )
}

/** 作品名按钮：点开看作品概况，回书架或切换到别的作品 */
function ProjectMenu({ projectId, project, projects, stats }: {
  projectId: string
  project: Project | null
  projects: Project[]
  stats: ProjectStats
}) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const status = project ? PROJECT_STATUS_META[project.status] ?? PROJECT_STATUS_META.planning : PROJECT_STATUS_META.planning
  const others = projects.filter((p) => p.id !== projectId).slice(0, 8)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const go = (path: string) => {
    setOpen(false)
    navigate(path)
  }

  return (
    <div ref={ref} className="relative min-w-0 flex-1">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex h-10 w-full min-w-0 items-center gap-2 rounded-lg px-2 text-left hover:bg-surface-hover"
        title={project?.title}
      >
        <BookText className="h-4 w-4 shrink-0 text-content" />
        <span className="min-w-0 flex-1 truncate font-serif text-[14px] font-semibold text-content">{project?.title ?? '加载中…'}</span>
        <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 text-content-tertiary transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="hh-menu absolute left-0 top-full z-40 mt-1 w-[17rem]">
          <div className="px-3 pb-2.5 pt-2">
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate font-serif text-[15px] font-semibold text-content">{project?.title}</span>
              <span className={status.className}>{status.label}</span>
            </div>
            {project?.genre && <p className="mt-0.5 truncate text-[12px] text-content-tertiary">{project.genre}</p>}
            <dl className="mt-2.5 grid grid-cols-4 gap-1 text-center">
              {([
                ['大纲', stats.outlines],
                ['角色', stats.people + stats.organizations],
                ['章节', stats.chapters],
                ['字数', formatCount(stats.words)],
              ] as const).map(([label, value]) => (
                <div key={label} className="rounded-lg bg-surface-paper py-1.5">
                  <dd className="text-[14px] font-semibold tabular-nums text-content">{value}</dd>
                  <dt className="text-[11px] text-content-tertiary">{label}</dt>
                </div>
              ))}
            </dl>
          </div>
          <div className="my-1 h-px bg-surface-border-light" />
          <MenuItem onClick={() => go('/')}>
            <Library className="h-4 w-4 text-content-tertiary" />返回书架
          </MenuItem>
          {others.length > 0 && (
            <>
              <p className="px-3 pb-1 pt-2 text-[11px] text-content-tertiary">切换作品</p>
              {others.map((p) => (
                <MenuItem key={p.id} onClick={() => go(`/project/${p.id}`)}>
                  <BookText className="h-4 w-4 text-content-tertiary" />
                  <span className="min-w-0 flex-1 truncate">{p.title}</span>
                </MenuItem>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function MenuItem({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} className="hh-menu-item">
      {children}
    </button>
  )
}
