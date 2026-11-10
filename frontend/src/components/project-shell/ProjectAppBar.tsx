/**
 * 中栏顶部工具栏：左边 返回书架 · 写作 · 谋篇 · 全部页面 · 搜索 · 专注模式 · 全书字数，
 * 右边 后台任务 · 本项目模型 · 智能助笔开关。中栏够宽时按钮带文字，窄时按次要程度收起（容器查询，见 globals.css 的 .ws-appbar）。
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
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
      {/* 横向可滚（不显示滚动条）：极窄时放不下的工具滑过去还点得到，不会被裁成半个；下拉菜单挂在 body 上，不受它裁剪 */}
      <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <button onClick={onOpenMobileSidebar} className="ws-icon-btn h-10 w-10 lg:hidden" aria-label="打开侧栏">
          <Menu className="h-4 w-4" />
        </button>
        {sidebarCollapsed && (
          <button onClick={onShowSidebar} className="ws-icon-btn hidden h-10 w-10 lg:inline-flex" title="展开侧栏">
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        )}
        <button onClick={() => navigate('/projects')} className="ws-icon-btn h-10 w-10 text-content" title="返回书架">
          <ArrowLeft className="h-[18px] w-[18px]" />
        </button>
        <NavLink to="chapter-analysis" className={({ isActive }) => cn('ws-tool', isActive && 'ws-tool--on')} title="章节写作">
          <PenLine className="h-4 w-4 shrink-0" /><span className="ws-tool-label">写作</span>
        </NavLink>
        <NavLink to="outline" className={({ isActive }) => cn('ws-tool', isActive && 'ws-tool--on')} title="谋篇：总纲 · 卷纲 · 章纲">
          <BookText className="h-4 w-4 shrink-0" /><span className="ws-tool-label">谋篇</span>
        </NavLink>
        <PagesMenu />
        <button onClick={onSearch} className="ws-tool ws-tool--search" title="在左栏搜索">
          <Search className="h-4 w-4 shrink-0" /><span className="ws-tool-label">搜索</span>
        </button>
        {/* 窄屏两侧栏本来就是抽屉，专注模式没有用处 */}
        <button onClick={onToggleFocus} aria-pressed={focusMode} className={cn('ws-tool max-lg:hidden', focusMode && 'ws-tool--on')} title={focusMode ? '退出专注：展开两侧栏' : '专注模式：收起左栏和智能助笔'}>
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

const PAGES_MENU_WIDTH = 352

/** 「全部页面」：侧栏收起时也能直接跳到任一页面。菜单挂在 body 上、按按钮位置摆：
 * 工具栏左边一组是横向滚动容器，挂在里面会被裁掉（以前就是这样，点了只有按钮变色、菜单看不见）；窄屏时夹在视口里。
 * 手机上铺满整宽、行高一些（手指好点），底下垫一层半透明遮罩：点遮罩只收起菜单，不会顺手点到下面的页面 */
function PagesMenu() {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<CSSProperties>({})
  const ref = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const maskRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      // 点在遮罩上交给遮罩的 onClick 收（这里先收的话遮罩没了，这一下的 click 会落到下面的页面上）
      if (maskRef.current?.contains(target)) return
      if (!ref.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const close = () => setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', close)
    }
  }, [open])

  const toggle = () => {
    if (!open && ref.current) {
      const rect = ref.current.getBoundingClientRect()
      const viewport = document.documentElement.clientWidth
      const width = viewport < 640 ? viewport - 16 : Math.min(PAGES_MENU_WIDTH, viewport - 16)
      setPos({ top: rect.bottom + 4, left: Math.max(8, Math.min(rect.left, viewport - width - 8)), width })
    }
    setOpen((v) => !v)
  }

  return (
    <>
      <button ref={ref} onClick={toggle} aria-expanded={open} className={cn('ws-tool ws-tool--pages', open && 'ws-tool--on')} title="全部页面">
        <LayoutGrid className="h-4 w-4 shrink-0" /><span className="ws-tool-label">页面</span>
        <ChevronDown className="ws-tool-label h-3.5 w-3.5 text-content-tertiary" />
      </button>
      {open && createPortal(
        <>
          <div ref={maskRef} className="fixed inset-0 z-40 bg-black/20 sm:hidden" onClick={() => setOpen(false)} aria-hidden />
          <div ref={menuRef} className="hh-menu fixed z-50 max-h-[calc(100dvh-5rem)] overflow-y-auto p-2 max-sm:p-3" style={pos}>
            <div className="grid grid-cols-2 gap-x-2 gap-y-3 max-sm:gap-y-4">
              {NAV_TABS.map((tab) => (
                <div key={tab.key}>
                  <p className="px-2 pb-1 text-[11px] text-content-tertiary max-sm:px-2.5 max-sm:pb-1.5 max-sm:text-[12px]">{tab.label}</p>
                  {tab.entries.map((e) => (
                    <NavLink
                      key={e.path}
                      to={e.path}
                      end
                      onClick={() => setOpen(false)}
                      className={({ isActive }) => cn(
                        'flex items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] text-content hover:bg-surface-hover max-sm:gap-2.5 max-sm:px-2.5 max-sm:py-2.5 max-sm:text-[15px]',
                        isActive && 'bg-brand-100 text-brand-600',
                      )}
                    >
                      <e.icon className="h-4 w-4 shrink-0 text-content-tertiary max-sm:h-[18px] max-sm:w-[18px]" />
                      <span className="truncate">{e.label}</span>
                    </NavLink>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </>,
        document.body,
      )}
    </>
  )
}
