import { useEffect, useState, useMemo } from 'react'
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
  Rocket,
  ChevronRight,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { projectApi } from '@/services/api'
import { useCharacterSync, useOutlineSync, useChapterSync } from '@/store/hooks'
import { PageLoading } from '@/components/ui/PageLoading'
import { AIJobTray } from '@/components/ai-job/AIJobTray'
import { ProjectModelPicker } from '@/components/ai-model/ProjectModelPicker'
import { setActiveProjectId } from '@/utils/activeProject'

const NAV_ITEMS = [
  { label: '世界设定', icon: Globe, path: 'world-setting' },
  { label: '世界规则', icon: Shield, path: 'world-rules' },
  { label: '角色与组织', icon: Users, path: 'characters' },
  { label: '关系管理', icon: GitBranch, path: 'relationships' },
  { label: '故事大纲', icon: FileText, path: 'outline' },
  { label: '桥段规划', icon: Rocket, path: 'plot-bridges' },
  { label: '剧情分析', icon: BookOpen, path: 'chapter-analysis' },
  { label: '写作风格', icon: Palette, path: 'writing-styles' },
  { label: '仿写参考包', icon: Library, path: 'reference-packs' },
  { label: '记忆系统', icon: Brain, path: 'memories' },
] as const

const PROJECT_STATUS_META = {
  planning: { label: '规划中', className: 'bg-surface-hover text-content-secondary' },
  writing: { label: '创作中', className: 'bg-emerald-50 text-emerald-600' },
  revising: { label: '修改中', className: 'bg-amber-50 text-amber-600' },
  completed: { label: '已完成', className: 'bg-violet-50 text-violet-600' },
} as const

const SIDEBAR_ITEM_CLASS =
  'group relative flex items-center gap-3 px-3 py-2.5 text-sm text-content-secondary transition-all hover:bg-white/70 hover:text-content'

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

  const currentSection = useMemo(() => {
    return NAV_ITEMS.find((item) => location.pathname.includes(item.path))?.label ?? '创作总览'
  }, [location.pathname])

  const projectStatus = currentProject ? PROJECT_STATUS_META[currentProject.status] : PROJECT_STATUS_META.planning

  if (loading && !currentProject) return <PageLoading />

  const sidebarContent = (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-surface-border/80 p-2.5">
        <button
          onClick={() => navigate('/')}
          className={cn(SIDEBAR_ITEM_CLASS, 'py-2 text-xs', collapsed && 'justify-center px-0')}
          title="返回书架"
        >
          <ArrowLeft className="h-4 w-4 shrink-0" />
          {!collapsed && <span>返回书架</span>}
        </button>

        {currentProject && (
          <div className={cn('mt-1 flex items-center gap-3 px-3 py-2', collapsed && 'justify-center px-0')}>
            <span
              className="flex h-10 w-10 shrink-0 items-center justify-center bg-gradient-to-br from-[#007aff] to-[#63b3ff] text-base font-semibold text-white shadow-[0_12px_28px_-12px_rgba(0,122,255,0.6)]"
              title={collapsed ? currentProject.title : undefined}
            >
              {getCoverLetter(currentProject.title)}
            </span>
            {!collapsed && (
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold tracking-tight text-content">{currentProject.title}</p>
                <span className={cn('mt-1 inline-flex px-1.5 py-0.5 text-[11px] font-medium', projectStatus.className)}>
                  {projectStatus.label}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-2.5 py-4">
        {!collapsed && (
          <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.22em] text-content-tertiary">项目工作台</p>
        )}
        {NAV_ITEMS.map(({ label, icon: Icon, path }) => (
          <NavLink
            key={path}
            to={path}
            className={({ isActive }) =>
              cn(
                SIDEBAR_ITEM_CLASS,
                collapsed && 'justify-center px-0',
                isActive && 'bg-brand/10 font-medium text-brand hover:bg-brand/10 hover:text-brand',
              )
            }
            title={collapsed ? label : undefined}
          >
            {({ isActive }) => (
              <>
                {isActive && <span className="absolute inset-y-2 left-0 w-[3px] bg-brand" aria-hidden />}
                <Icon className="h-[18px] w-[18px] shrink-0" />
                {!collapsed && <span className="truncate">{label}</span>}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="shrink-0 border-t border-surface-border/80 p-2.5">
        <button
          onClick={() => setShowRepairPanel(true)}
          className={cn(SIDEBAR_ITEM_CLASS, collapsed && 'justify-center px-0')}
          title="数据修复"
        >
          <Wrench className="h-[18px] w-[18px] shrink-0" />
          {!collapsed && <span>数据修复</span>}
        </button>
        <button
          onClick={() => setCollapsed((v) => !v)}
          className={cn(SIDEBAR_ITEM_CLASS, 'hidden lg:flex', collapsed && 'justify-center px-0')}
          title={collapsed ? '展开侧栏' : '收起侧栏'}
        >
          {collapsed ? <PanelLeft className="h-[18px] w-[18px] shrink-0" /> : <PanelLeftClose className="h-[18px] w-[18px] shrink-0" />}
          {!collapsed && <span>收起侧栏</span>}
        </button>
      </div>
    </div>
  )

  return (
    <div className="relative flex h-screen overflow-hidden">
      <div className="hh-orb -left-40 -top-40 h-[520px] w-[520px] bg-brand/15 animate-float-soft" />
      <div className="hh-orb -bottom-48 right-[-120px] h-[560px] w-[560px] bg-brand-400/15" />

      <aside
        className={cn(
          'relative z-40 hidden shrink-0 flex-col overflow-hidden border-r border-white/80 bg-white/55 backdrop-blur-2xl backdrop-saturate-150 shadow-[0_0_0_1px_rgba(15,43,96,0.04),20px_0_60px_-44px_rgba(15,43,96,0.35)] transition-[width] duration-200 lg:flex',
          collapsed ? 'w-16' : 'w-60',
        )}
      >
        {sidebarContent}
      </aside>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-content/25 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={cn(
          'hh-glass fixed inset-y-0 left-0 z-50 w-60 transform border-r transition-transform duration-200 lg:hidden',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        {sidebarContent}
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col">
        <header className="relative z-20 flex h-16 shrink-0 items-center justify-between gap-4 border-b border-white/80 bg-white/45 px-4 backdrop-blur-xl md:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              className="hh-icon-btn lg:hidden"
              onClick={() => setMobileOpen((v) => !v)}
              aria-label="切换侧栏"
            >
              {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
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
              <span className={cn('px-2 py-1 text-[11px] font-medium', projectStatus.className)}>{projectStatus.label}</span>
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto px-4 pb-8 pt-6 md:px-8 md:pt-8">
          <div className="mx-auto w-full max-w-[1400px]">
            <Outlet />
          </div>
        </main>
      </div>

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
