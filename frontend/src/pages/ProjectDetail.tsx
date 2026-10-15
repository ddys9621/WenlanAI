import { useCallback, useEffect, useState, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useParams, useNavigate, useLocation, Outlet, NavLink, Link } from 'react-router-dom'
import {
  ArrowLeft,
  Globe,
  Shield,
  Users,
  GitBranch,
  FileText,
  BookOpen,
  Palette,
  Menu,
  X,
  PanelLeftClose,
  PanelLeft,
  Brain,
  Wrench,
  Loader2,
  Library,
  ChevronRight,
  Map as MapIcon,
  Sparkles,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { projectApi } from '@/services/api'
import { useCharacterSync, useOutlineSync, useChapterSync } from '@/store/hooks'
import { PageLoading } from '@/components/ui/PageLoading'
import { AIJobTray } from '@/components/ai-job/AIJobTray'
import { ProjectModelPicker } from '@/components/ai-model/ProjectModelPicker'
import { GlobalAssistantHost } from '@/components/assistant/GlobalAssistantHost'
import { useAssistantDataChange } from '@/hooks/useAssistantPage'
import { useAssistantStore, type AssistantDataChange } from '@/store/assistantStore'
import { setActiveProjectId } from '@/utils/activeProject'

interface NavItem {
  label: string
  icon: LucideIcon
  path: string
}

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: '设定',
    items: [
      { label: '世界设定', icon: Globe, path: 'world-setting' },
      { label: '世界规则', icon: Shield, path: 'world-rules' },
      { label: '世界地图', icon: MapIcon, path: 'world-map' },
      { label: '角色与组织', icon: Users, path: 'characters' },
      { label: '关系管理', icon: GitBranch, path: 'relationships' },
    ],
  },
  {
    label: '规划',
    items: [
      { label: '谋篇（总纲·卷纲·章纲）', icon: FileText, path: 'outline' },
    ],
  },
  {
    label: '写作',
    items: [
      { label: '章节写作', icon: BookOpen, path: 'chapter-analysis' },
      { label: '写作风格', icon: Palette, path: 'writing-styles' },
      { label: '仿写参考包', icon: Library, path: 'reference-packs' },
      { label: '记忆系统', icon: Brain, path: 'memories' },
    ],
  },
]

const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items)

const PROJECT_STATUS_META = {
  planning: { label: '规划中', className: 'lj-badge lj-badge--muted' },
  writing: { label: '创作中', className: 'lj-badge lj-badge--ok' },
  revising: { label: '修改中', className: 'lj-badge lj-badge--draft' },
  completed: { label: '已完成', className: 'lj-badge lj-badge--candidate' },
} as const

function getCoverLetter(title: string) {
  return Array.from(title.trim()).find((char) => /[A-Za-z0-9\u4e00-\u9fa5]/.test(char)) ?? '书'
}

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
  } = useStore()

  const { refreshCharacters } = useCharacterSync()
  const { refreshOutlines } = useOutlineSync()
  const { refreshChapters } = useChapterSync()

  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [showRepairPanel, setShowRepairPanel] = useState(false)
  const [repairLoading, setRepairLoading] = useState(false)
  const [repairReport, setRepairReport] = useState<Record<string, unknown> | null>(null)

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
  }, [location.pathname])

  const stats = useMemo(() => {
    const totalWords = chapters.reduce((sum, ch) => sum + (ch.word_count ?? 0), 0)
    return {
      outlines: outlines.length,
      characters: characters.length,
      chapters: chapters.length,
      words: totalWords,
    }
  }, [outlines, characters, chapters])

  const formatCount = (n: number) => (n >= 10000 ? `${(n / 10000).toFixed(1)}万` : String(n))

  const currentNav = useMemo(() => NAV_ITEMS.find((item) => location.pathname.includes(item.path)), [location.pathname])
  const currentSection = currentNav?.label ?? '创作总览'

  // 全局智能助笔：登记作者所在页面（具体页面再补充正在看的章节 / 选中的正文）、Alt+A 开关、应用修改后刷新共享数据
  const assistantOpen = useAssistantStore((s) => s.open)
  const toggleAssistant = useAssistantStore((s) => s.toggle)
  const setAssistantRoute = useAssistantStore((s) => s.setRoute)
  useEffect(() => {
    setAssistantRoute(currentNav?.path ?? '', currentSection)
  }, [currentNav, currentSection, setAssistantRoute])
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

  const projectStatus = currentProject ? PROJECT_STATUS_META[currentProject.status] : PROJECT_STATUS_META.planning

  if (loading && !currentProject) return <PageLoading />

  const sidebarContent = (
    <div className="lj-rail">
      <div className="shrink-0 border-b border-sidebar-border p-2">
        <button
          onClick={() => navigate('/')}
          className={cn('lj-rail-item min-h-[34px] text-xs', collapsed && 'justify-center px-0')}
          title="返回书架"
        >
          <ArrowLeft className="h-4 w-4 shrink-0" />
          {!collapsed && <span>返回书架</span>}
        </button>

        {currentProject && (
          <div className={cn('mt-1 flex items-center gap-2.5 px-2 py-2', collapsed && 'justify-center px-0')}>
            <span
              className="relative flex h-10 w-8 shrink-0 items-center justify-center overflow-hidden rounded-sm bg-brand-600 font-serif text-base font-semibold text-white"
              title={collapsed ? currentProject.title : undefined}
            >
              {getCoverLetter(currentProject.title)}
              <span className="absolute bottom-0 left-0 h-0.5 w-full bg-signal" />
            </span>
            {!collapsed && (
              <div className="min-w-0">
                <p className="truncate font-serif text-sm font-semibold text-sidebar-text-active">{currentProject.title}</p>
                <span className="mt-1 inline-flex text-[11px] text-sidebar-text/80">{projectStatus.label}</span>
              </div>
            )}
          </div>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-1">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="mb-1">
            {!collapsed && <p className="lj-rail-caption">{group.label}</p>}
            <div className="space-y-0.5">
              {group.items.map(({ label, icon: Icon, path }) => (
                <NavLink
                  key={path}
                  to={path}
                  className={({ isActive }) => cn('lj-rail-item', collapsed && 'justify-center px-0', isActive && 'lj-rail-item--active')}
                  title={collapsed ? label : undefined}
                >
                  <Icon className="h-[18px] w-[18px] shrink-0" />
                  {!collapsed && <span className="truncate">{label}</span>}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-sidebar-border p-2">
        <button
          onClick={() => setShowRepairPanel(true)}
          className={cn('lj-rail-item', collapsed && 'justify-center px-0')}
          title="数据修复"
        >
          <Wrench className="h-[18px] w-[18px] shrink-0" />
          {!collapsed && <span>数据修复</span>}
        </button>
        <button
          onClick={() => setCollapsed((v) => !v)}
          className={cn('lj-rail-item hidden lg:flex', collapsed && 'justify-center px-0')}
          title={collapsed ? '展开侧栏' : '收起侧栏'}
        >
          {collapsed ? <PanelLeft className="h-[18px] w-[18px] shrink-0" /> : <PanelLeftClose className="h-[18px] w-[18px] shrink-0" />}
          {!collapsed && <span>收起侧栏</span>}
        </button>
      </div>
    </div>
  )

  return (
    <div className="relative flex h-screen overflow-hidden bg-surface">
      <aside
        className={cn(
          'relative z-40 hidden shrink-0 overflow-hidden transition-[width] duration-200 lg:block',
          collapsed ? 'w-16' : 'w-56',
        )}
      >
        {sidebarContent}
      </aside>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-content/30 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-56 transform shadow-xl transition-transform duration-200 lg:hidden',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        {sidebarContent}
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col">
        <header className="lj-topbar">
          <div className="flex min-w-0 items-center gap-3">
            <button
              className="hh-icon-btn h-8 w-8 lg:hidden"
              onClick={() => setMobileOpen((v) => !v)}
              aria-label="切换侧栏"
            >
              {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
            </button>

            <nav className="flex min-w-0 items-center gap-1.5 text-sm" aria-label="面包屑">
              <Link to="/" className="hidden shrink-0 text-content-tertiary hover:text-content sm:inline">
                我的项目
              </Link>
              <ChevronRight className="hidden h-3.5 w-3.5 shrink-0 text-content-tertiary sm:inline" />
              <span className="hidden max-w-[220px] truncate text-content-tertiary md:inline">
                {currentProject?.title ?? '加载中…'}
              </span>
              <ChevronRight className="hidden h-3.5 w-3.5 shrink-0 text-content-tertiary md:inline" />
              <h1 className="truncate font-medium text-content">{currentSection}</h1>
            </nav>
          </div>

          <div className="flex shrink-0 items-center gap-3">
            <button
              onClick={toggleAssistant}
              aria-pressed={assistantOpen}
              title="智能助笔（Alt+A）"
              className={cn(
                'inline-flex h-8 items-center gap-1.5 rounded border px-2.5 text-xs font-medium transition-colors',
                assistantOpen ? 'border-brand bg-brand text-white' : 'border-surface-border bg-white text-content-secondary hover:border-brand/50 hover:text-brand',
              )}
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">智能助笔</span>
            </button>
            {projectId && <ProjectModelPicker projectId={projectId} />}
            <AIJobTray />
            <div className="hidden shrink-0 items-center gap-5 md:flex">
              <dl className="flex items-center gap-4 text-xs">
                {[
                  ['大纲', stats.outlines],
                  ['角色', stats.characters],
                  ['章节', stats.chapters],
                  ['字数', formatCount(stats.words)],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-baseline gap-1.5">
                    <dt className="text-content-tertiary">{label}</dt>
                    <dd className="text-sm font-semibold text-content tabular-nums">{value}</dd>
                  </div>
                ))}
              </dl>
              <span className={projectStatus.className}>{projectStatus.label}</span>
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto px-4 pb-8 pt-6 md:px-8 md:pt-7">
          <div className="mx-auto w-full max-w-[1400px]">
            <Outlet />
          </div>
        </main>
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
  )
}
