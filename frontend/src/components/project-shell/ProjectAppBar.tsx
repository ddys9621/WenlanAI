/**
 * 中栏顶部工具栏：左边 返回书架 · 写作 · 谋篇 · 全部页面 · 搜索 · 专注模式 · 全书字数，
 * 右边 后台任务 · 本项目模型 · 智能助笔开关。中栏够宽时按钮带文字（容器查询，见 globals.css 的 .ws-appbar）。
 */
import { useEffect, useRef, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { ArrowLeft, Bot, BookText, ChevronDown, LayoutGrid, Menu, Monitor, PanelLeftOpen, PenLine, Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import { AIJobTray } from '@/components/ai-job/AIJobTray'
import { ProjectModelPicker } from '@/components/ai-model/ProjectModelPicker'
import { NAV_TABS, formatCount } from './projectNav'

interface ProjectAppBarProps {
  projectId: string
  /** 宽屏侧栏收起着：显示「展开侧栏」 */
  sidebarCollapsed: boolean
  onShowSidebar: () => void
  onOpenMobileSidebar: () => void
  onSearch: () => void
  focusMode: boolean
  onToggleFocus: () => void
  words: number
  assistantOpen: boolean
  onToggleAssistant: () => void
}

export function ProjectAppBar({
  projectId, sidebarCollapsed, onShowSidebar, onOpenMobileSidebar, onSearch, focusMode, onToggleFocus, words, assistantOpen,
  onToggleAssistant,
}: ProjectAppBarProps) {
  const navigate = useNavigate()
  return (
    <header className="ws-appbar">
      <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-hidden">
        <button onClick={onOpenMobileSidebar} className="ws-icon-btn h-10 w-10 lg:hidden" aria-label="打开侧栏">
          <Menu className="h-4 w-4" />
        </button>
        {sidebarCollapsed && (
          <button onClick={onShowSidebar} className="ws-icon-btn hidden h-10 w-10 lg:inline-flex" title="展开侧栏">
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        )}
        <button onClick={() => navigate('/')} className="ws-icon-btn h-10 w-10 text-content" title="返回书架">
          <ArrowLeft className="h-[18px] w-[18px]" />
        </button>
        <NavLink to="chapter-analysis" className={({ isActive }) => cn('ws-tool', isActive && 'ws-tool--on')} title="章节写作">
          <PenLine className="h-4 w-4 shrink-0" /><span className="ws-tool-label">写作</span>
        </NavLink>
        <NavLink to="outline" className={({ isActive }) => cn('ws-tool', isActive && 'ws-tool--on')} title="谋篇：总纲 · 卷纲 · 章纲">
          <BookText className="h-4 w-4 shrink-0" /><span className="ws-tool-label">谋篇</span>
        </NavLink>
        <PagesMenu />
        <button onClick={onSearch} className="ws-tool" title="在左栏搜索">
          <Search className="h-4 w-4 shrink-0" /><span className="ws-tool-label">搜索</span>
        </button>
        <button onClick={onToggleFocus} aria-pressed={focusMode} className={cn('ws-tool', focusMode && 'ws-tool--on')} title={focusMode ? '退出专注：展开两侧栏' : '专注模式：收起左栏和智能助笔'}>
          <Monitor className="h-4 w-4 shrink-0" /><span className="ws-tool-label">{focusMode ? '退出专注' : '模式'}</span>
        </button>
        <span className="ws-counter" title="全书已保存字数">
          <PenLine className="h-3.5 w-3.5 shrink-0" />
          <span className="font-medium tabular-nums text-content">{formatCount(words)}</span>
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <AIJobTray />
        <ProjectModelPicker projectId={projectId} />
        <button
          onClick={onToggleAssistant}
          aria-pressed={assistantOpen}
          className={cn('ws-tool', assistantOpen && 'ws-tool--on')}
          title="智能助笔（Alt+A）"
        >
          <Bot className="h-4 w-4 shrink-0" /><span className="ws-tool-label">智能助笔</span>
        </button>
      </div>
    </header>
  )
}

/** 「全部页面」：侧栏收起时也能直接跳到任一页面 */
function PagesMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

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

  return (
    <div ref={ref} className="relative shrink-0">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className={cn('ws-tool', open && 'ws-tool--on')} title="全部页面">
        <LayoutGrid className="h-4 w-4 shrink-0" /><span className="ws-tool-label">页面</span>
        <ChevronDown className="ws-tool-label h-3.5 w-3.5 text-content-tertiary" />
      </button>
      {open && (
        <div className="hh-menu absolute left-0 top-full z-40 mt-1 w-[22rem] p-2">
          <div className="grid grid-cols-2 gap-x-2 gap-y-3">
            {NAV_TABS.map((tab) => (
              <div key={tab.key}>
                <p className="px-2 pb-1 text-[11px] text-content-tertiary">{tab.label}</p>
                {tab.entries.map((e) => (
                  <NavLink
                    key={e.path}
                    to={e.path}
                    end
                    onClick={() => setOpen(false)}
                    className={({ isActive }) => cn('flex items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] text-content hover:bg-surface-hover', isActive && 'bg-brand-100 text-brand-600')}
                  >
                    <e.icon className="h-4 w-4 shrink-0 text-content-tertiary" />
                    <span className="truncate">{e.label}</span>
                  </NavLink>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
