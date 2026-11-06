import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useParams, useNavigate, useLocation, Outlet } from 'react-router-dom'
import { Wrench, Loader2, X } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { projectApi } from '@/services/api'
import { useCharacterSync, useOutlineSync, useChapterSync } from '@/store/hooks'
import { PageLoading } from '@/components/ui/PageLoading'
import { GlobalAssistantHost } from '@/components/assistant/GlobalAssistantHost'
import { useAssistantDataChange } from '@/hooks/useAssistantPage'
import { useAssistantStore, type AssistantDataChange } from '@/store/assistantStore'
import { setActiveProjectId } from '@/utils/activeProject'
import { ProjectAppBar } from '@/components/project-shell/ProjectAppBar'
import { ProjectShellContext } from '@/components/project-shell/ProjectShellContext'
import { ProjectSidebar } from '@/components/project-shell/ProjectSidebar'
import { ProjectStatusBar } from '@/components/project-shell/ProjectStatusBar'
import { ResizeHandle } from '@/components/project-shell/ResizeHandle'
import { LEFT_PANE, LEFT_PANE_KEY } from '@/components/project-shell/paneSizes'
import { usePaneWidth } from '@/components/project-shell/usePaneWidth'
import {
  PROJECT_STATUS_META, entryOf, isFullBleed, sectionOf, tabOf, type NavTabKey, type ProjectStats,
} from '@/components/project-shell/projectNav'

const COLLAPSED_KEY = 'project-sidebar-collapsed'
const isWide = () => typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches

/**
 * 项目工作台外框（三栏编辑器版式）：左栏（作品名 / 四个页签 / 页面入口 / 章节目录）｜中栏（工具栏 / 页面 / 状态栏）｜
 * 右侧智能助笔。左右两栏可拖宽；<html> 上挂 wl-ws，项目内页面的卡片、表单、页头按工作台的排版走（globals.css）。
 */
export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const location = useLocation()

  const {
    currentProject,
    setCurrentProject,
    clearProjectData,
    loading,
    setLoading,
    outlines,
    characters,
    chapters,
    projects,
    volumes,
    chapterOutlines,
  } = useStore()

  const { refreshCharacters } = useCharacterSync()
  const { refreshOutlines } = useOutlineSync()
  const { refreshChapters } = useChapterSync()

  const [collapsed, setCollapsed] = useState(() => typeof localStorage !== 'undefined' && localStorage.getItem(COLLAPSED_KEY) === 'true')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [tab, setTab] = useState<NavTabKey>(() => tabOf(location.pathname))
  const leftPane = usePaneWidth(LEFT_PANE_KEY, LEFT_PANE)
  const [directorySlot, setDirectorySlot] = useState<HTMLDivElement | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const restoreAssistant = useRef(false)
  const [showRepairPanel, setShowRepairPanel] = useState(false)
  const [repairLoading, setRepairLoading] = useState(false)
  const [repairReport, setRepairReport] = useState<Record<string, unknown> | null>(null)

  // 项目内页面按工作台排版（globals.css 里 :where(.wl-ws) 开头的样式）；挂在 <html> 上，portal 出去的弹窗也算
  useLayoutEffect(() => {
    document.documentElement.classList.add('wl-ws')
    return () => document.documentElement.classList.remove('wl-ws')
  }, [])

  useEffect(() => {
    if (!projectId) return

    // 进入项目：之后本壳内所有请求带 X-Project-Id（AI 生成按本项目偏好选模型 / 参数）。
    // React 子组件 effect 先于父组件跑，子页面挂载时的列表请求可能不带头——它们不是 AI 生成，无影响；
    // AI 生成都是用户点击触发，届时头已就位。StrictMode 二次挂载会重跑本 effect，不能只在 render 里设。
    setActiveProjectId(projectId)

    let cancelled = false

    const load = async () => {
      try {
        setLoading(true)
        const project = await projectApi.getProject(projectId)
        if (cancelled) return
        setCurrentProject(project)

        await Promise.all([
          refreshOutlines(projectId),
          refreshCharacters(projectId),
          refreshChapters(projectId),
        ])
      } catch {
        if (!cancelled) {
          toast.error('加载项目失败')
          navigate('/')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()

    return () => {
      cancelled = true
      setActiveProjectId(null)
      clearProjectData()
      setCurrentProject(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  useEffect(() => {
    setMobileOpen(false)
    setTab(tabOf(location.pathname))
  }, [location.pathname])

  const stats = useMemo<ProjectStats>(() => {
    const organizations = characters.filter((c) => c.is_organization).length
    return {
      outlines: outlines.length,
      people: characters.length - organizations,
      organizations,
      chapters: chapters.length,
      words: chapters.reduce((sum, ch) => sum + (ch.word_count ?? 0), 0),
      volumes: volumes.length,
      chapterOutlines: chapterOutlines.length,
    }
  }, [outlines, characters, chapters, volumes, chapterOutlines])

  const section = useMemo(() => sectionOf(location.pathname), [location.pathname])
  const entry = entryOf(location.pathname)
  const fullBleed = isFullBleed(location.pathname)

  // 全局智能助笔：登记作者所在页面（具体页面再补充正在看的章节 / 选中的正文）、Alt+A 开关、应用修改后刷新共享数据
  const assistantOpen = useAssistantStore((s) => s.open)
  const toggleAssistant = useAssistantStore((s) => s.toggle)
  const setAssistantOpen = useAssistantStore((s) => s.setOpen)
  const setAssistantRoute = useAssistantStore((s) => s.setRoute)
  useEffect(() => {
    setAssistantRoute(section.page, section.label)
  }, [section.page, section.label, setAssistantRoute])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyA') {
        e.preventDefault()
        toggleAssistant()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggleAssistant])
  const onAssistantData = useCallback((change: AssistantDataChange) => {
    if (!projectId) return
    if (change.entity === 'project') void projectApi.getProject(projectId).then(setCurrentProject).catch(() => {})
    if (change.entity === 'character' || change.entity === 'organization') void refreshCharacters(projectId)
    if (change.entity === 'story_outline') void refreshOutlines(projectId)
  }, [projectId, refreshCharacters, refreshOutlines, setCurrentProject])
  useAssistantDataChange(onAssistantData)

  const setSidebarCollapsed = useCallback((next: boolean) => {
    setCollapsed(next)
    localStorage.setItem(COLLAPSED_KEY, String(next))
  }, [])

  const collapseSidebar = () => {
    setMobileOpen(false)
    if (isWide()) setSidebarCollapsed(true)
  }

  const showSidebar = () => {
    if (isWide()) setSidebarCollapsed(false)
    else setMobileOpen(true)
  }

  /** 工具栏「搜索」：展开左栏并聚焦搜索框（章节写作页的目录用它自己的搜索框） */
  const focusSearch = () => {
    showSidebar()
    requestAnimationFrame(() => {
      const input = searchRef.current ?? directorySlot?.querySelector<HTMLInputElement>('input')
      input?.focus()
      input?.select()
    })
  }

  // 专注模式 = 左栏收起 + 助笔关上；再点一次展开左栏，进专注前助笔开着的话也打开
  const focusMode = collapsed && !assistantOpen
  const toggleFocus = () => {
    if (focusMode) {
      setSidebarCollapsed(false)
      if (restoreAssistant.current) setAssistantOpen(true)
      return
    }
    restoreAssistant.current = assistantOpen
    setSidebarCollapsed(true)
    setAssistantOpen(false)
  }

  const shell = useMemo(() => ({ directorySlot }), [directorySlot])
  const projectStatus = currentProject ? PROJECT_STATUS_META[currentProject.status] ?? PROJECT_STATUS_META.planning : PROJECT_STATUS_META.planning

  if (loading && !currentProject) return <PageLoading />

  return (
    <ProjectShellContext.Provider value={shell}>
      <div className="ws-root relative flex h-screen overflow-hidden">
        {mobileOpen && (
          <div
            className="fixed inset-0 z-40 bg-content/30 lg:hidden"
            onClick={() => setMobileOpen(false)}
          />
        )}
        <aside
          style={{ '--ws-left': `${leftPane.width}px` } as CSSProperties}
          className={cn(
            'z-50 flex shrink-0 flex-col',
            'max-lg:fixed max-lg:inset-y-0 max-lg:left-0 max-lg:w-[min(320px,88vw)] max-lg:shadow-xl max-lg:transition-transform max-lg:duration-200',
            mobileOpen ? 'max-lg:translate-x-0' : 'max-lg:-translate-x-full',
            'lg:relative lg:z-auto lg:w-[var(--ws-left)]',
            collapsed && 'lg:hidden',
          )}
        >
          {projectId && (
            <ProjectSidebar
              projectId={projectId}
              project={currentProject}
              projects={projects}
              stats={stats}
              chapters={chapters}
              tab={tab}
              onTabChange={setTab}
              searchRef={searchRef}
              onDirectorySlot={setDirectorySlot}
              onCollapse={collapseSidebar}
              onOpenRepair={() => setShowRepairPanel(true)}
              onAskAssistant={() => useAssistantStore.getState().compose('')}
            />
          )}
        </aside>
        {!collapsed && (
          <ResizeHandle
            side="left"
            width={leftPane.width}
            limits={LEFT_PANE}
            label="左栏宽度"
            onResize={leftPane.setWidth}
            onCommit={leftPane.commit}
            className="hidden lg:block"
          />
        )}

        <div className="relative flex min-w-0 flex-1 flex-col">
          {projectId && (
            <ProjectAppBar
              projectId={projectId}
              sidebarCollapsed={collapsed}
              onShowSidebar={showSidebar}
              onOpenMobileSidebar={() => setMobileOpen(true)}
              onSearch={focusSearch}
              focusMode={focusMode}
              onToggleFocus={toggleFocus}
              words={stats.words}
              assistantOpen={assistantOpen}
              onToggleAssistant={toggleAssistant}
            />
          )}

          {fullBleed ? (
            <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
              <Outlet />
            </main>
          ) : (
            <>
              {/* 纵向内边距不放在 main 上：sticky 页头的 top 以滚动容器的 content-box 为基准 */}
              <main className="ws-main">
                <div className="ws-page">
                  <Outlet />
                </div>
              </main>
              <ProjectStatusBar status={projectStatus} section={entry?.label ?? section.label} icon={entry?.icon} stats={stats} />
            </>
          )}
        </div>

        {projectId && <GlobalAssistantHost projectId={projectId} />}

        {showRepairPanel && projectId && createPortal(
          <div className="hh-modal-mask" onClick={() => setShowRepairPanel(false)}>
            <div className="hh-modal max-w-[440px]" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
              <div className="hh-modal-head">
                <div>
                  <p className="hh-eyebrow">数据修复</p>
                  <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">数据一致性修复</h2>
                  <p className="mt-1 text-sm text-content-secondary">检查并修复项目数据中的不一致问题。</p>
                </div>
                <button onClick={() => setShowRepairPanel(false)} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="hh-modal-body space-y-2.5">
                <button
                  onClick={async () => {
                    setRepairLoading(true)
                    try {
                      const res = await projectApi.checkConsistency(projectId)
                      setRepairReport(res)
                      toast.success('一致性检查完成')
                    } catch {
                      toast.error('检查失败')
                    } finally {
                      setRepairLoading(false)
                    }
                  }}
                  disabled={repairLoading}
                  className="hh-btn-primary w-full"
                >
                  {repairLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4" />}
                  检查并自动修复
                </button>
                <button
                  onClick={async () => {
                    try {
                      const res = await projectApi.fixOrganizations(projectId)
                      toast.success(`组织修复: ${res.fixed_count}/${res.total_count}`)
                    } catch {
                      toast.error('修复失败')
                    }
                  }}
                  className="hh-btn-secondary w-full"
                >
                  修复组织记录
                </button>
                <button
                  onClick={async () => {
                    try {
                      const res = await projectApi.fixMemberCounts(projectId)
                      toast.success(`计数修复: ${res.fixed_count}/${res.total_count}`)
                    } catch {
                      toast.error('修复失败')
                    }
                  }}
                  className="hh-btn-secondary w-full"
                >
                  修复成员计数
                </button>
                {repairReport && (
                  <pre className="hh-subpanel max-h-44 overflow-y-auto whitespace-pre-wrap p-3 text-xs text-content-secondary">
                    {JSON.stringify(repairReport, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          </div>,
          document.body,
        )}
      </div>
    </ProjectShellContext.Provider>
  )
}
