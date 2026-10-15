import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Plus,
  FileText,
  MoreHorizontal,
  Download,
  Upload,
  Trash2,
  Clock,
  Sparkles,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  X,
  Minimize2,
  Maximize2,
  StopCircle,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  Wand2,
  type LucideIcon,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { useProjectSync } from '@/store/hooks'
import { projectApi, referencePackApi, wizardStreamApi } from '@/services/api'
import InspirationModal from '@/components/inspiration/InspirationModal'
import { MCPSelector } from '@/components/MCPSelector'
import {
  ReferencePackSelector,
  DEFAULT_SELECTOR_VALUE as DEFAULT_REF_PACK_VALUE,
  type ReferencePackSelectorValue,
} from '@/components/ReferencePackSelector'
import { BrandLogo } from '@/components/ui/BrandLogo'
import { parseServerTime } from '@/utils/serverTime'
import type { PlatformPreset, Project } from '@/types'

/* ─── 常量 ─── */

const STATUS_MAP: Record<Project['status'], { label: string; color: string }> = {
  planning: { label: '规划中', color: 'bg-surface-hover text-content-secondary' },
  writing: { label: '创作中', color: 'bg-emerald-50 text-emerald-600' },
  revising: { label: '修改中', color: 'bg-amber-50 text-amber-600' },
  completed: { label: '已完成', color: 'bg-violet-50 text-violet-600' },
}

const COVER_STYLES = [
  'from-[#204a3e] to-[#4f8a76]',
  'from-[#8f483e] to-[#c06a57]',
  'from-[#4d657b] to-[#7d93a8]',
  'from-[#80601e] to-[#b8913f]',
] as const

/* ─── 工具函数 ─── */

function formatWords(n: number) {
  if (n >= 10000) return `${(n / 10000).toFixed(1)} 万`
  return `${n}`
}

function formatDate(iso: string) {
  const d = parseServerTime(iso) ?? new Date(iso)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return d.toLocaleDateString('zh-CN')
}

function getCoverStyle(seed: string) {
  const value = [...seed].reduce((sum, char) => sum + char.charCodeAt(0), 0)
  return COVER_STYLES[value % COVER_STYLES.length]
}

const TITLE_WRAPPERS: Record<string, string> = {
  '《': '》',
  '「': '」',
  '『': '』',
  '【': '】',
  '（': '）',
  '(': ')',
  '[': ']',
  '{': '}',
  '“': '”',
  '‘': '’',
  '"': '"',
  "'": "'",
}

function getDisplayTitle(title: string) {
  let value = title.trim()

  while (value.length > 1) {
    const chars = Array.from(value)
    const first = chars[0]
    const last = chars[chars.length - 1]

    if (TITLE_WRAPPERS[first] !== last) break
    value = chars.slice(1, -1).join('').trim()
  }

  return value || title.trim() || '未命名项目'
}

function getCoverLetter(title: string) {
  const displayTitle = getDisplayTitle(title).replace(/^[《》「」『』【】〈〉（）()[\]{}“”‘’"'`\s]+/, '')
  const chars = Array.from(displayTitle)

  return (
    chars.find((char) => /[A-Za-z0-9\u4e00-\u9fa5]/.test(char)) ??
    chars.find((char) => !/[\s《》「」『』【】〈〉（）()[\]{}“”‘’"'`~!@#$%^&*+=|\\/:;,.!?，。！？；：、-]/.test(char)) ??
    '书'
  )
}

/* ─── 骨架屏 ─── */

function SkeletonCards() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="hh-panel p-5">
          <div className="flex items-start justify-between">
            <div className="h-12 w-12 animate-pulse bg-brand/10" />
            <div className="h-5 w-14 animate-pulse bg-brand/5" />
          </div>
          <div className="mt-4 h-5 w-3/4 animate-pulse bg-brand/10" />
          <div className="mt-3 space-y-2">
            <div className="h-3.5 animate-pulse bg-brand/5" />
            <div className="h-3.5 w-2/3 animate-pulse bg-brand/5" />
          </div>
          <div className="mt-5 flex justify-between border-t border-surface-border/80 pt-3.5">
            <div className="h-3 w-16 animate-pulse bg-brand/5" />
            <div className="h-3 w-20 animate-pulse bg-brand/5" />
          </div>
        </div>
      ))}
    </div>
  )
}

/* ─── 空状态：两种创建方式各出现一次 ─── */

function ModeCard({
  icon: Icon,
  title,
  description,
  primary,
  onClick,
}: {
  icon: LucideIcon
  title: string
  description: string
  primary?: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="hh-subpanel group flex items-start gap-4 p-5 text-left transition-all hover:-translate-y-0.5 hover:border-brand/40 hover:bg-white hover:shadow-card"
    >
      <span
        className={cn(
          'flex h-11 w-11 shrink-0 items-center justify-center transition-colors',
          primary ? 'bg-brand text-white' : 'bg-brand/10 text-brand',
        )}
      >
        <Icon className="h-5 w-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2 text-[15px] font-semibold text-content">
          {title}
          <ArrowRight className="h-4 w-4 text-content-tertiary transition-all group-hover:translate-x-0.5 group-hover:text-brand" />
        </span>
        <span className="mt-1 block text-[13px] leading-6 text-content-secondary">{description}</span>
      </span>
    </button>
  )
}

function EmptyState({ onCreate, onInspiration }: { onCreate: () => void; onInspiration: () => void }) {
  return (
    <section className="hh-panel flex flex-col items-center px-6 py-14 text-center md:py-16">
      <BrandLogo size="lg" />
      <h2 className="mt-6 text-2xl font-semibold tracking-tight text-content">创建第一个小说项目</h2>
      <p className="mt-2 max-w-[440px] text-sm leading-6 text-content-secondary">
        选择一种方式开始，AI 都会为你生成世界观、角色与故事大纲。
      </p>
      <div className="mt-8 grid w-full max-w-[720px] gap-4 md:grid-cols-2">
        <ModeCard
          icon={Plus}
          title="快速开始"
          description="已经有书名和故事想法？填好基本信息，一次生成完整设定。"
          primary
          onClick={onCreate}
        />
        <ModeCard
          icon={Sparkles}
          title="灵感模式"
          description="只有一句灵感？AI 逐步引导你确定书名、简介、主题与类型。"
          onClick={onInspiration}
        />
      </div>
      <p className="mt-6 text-xs text-content-tertiary">已有导出的项目文件？可从右上角「更多」导入。</p>
    </section>
  )
}

/* ─── 项目卡片 ─── */

function ProjectCard({
  project,
  onClick,
  onDelete,
}: {
  project: Project
  onClick: () => void
  onDelete: () => void
}) {
  const status = STATUS_MAP[project.status] ?? STATUS_MAP.planning
  const cover = getCoverStyle(project.title)
  const tags = project.genre?.split(/[,，、/]/).filter(Boolean).slice(0, 3) ?? []
  const displayTitle = getDisplayTitle(project.title)
  const coverLetter = getCoverLetter(project.title)

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      className="hh-panel group flex cursor-pointer flex-col p-5 transition-all hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand/20"
    >
      <div className="pb-5">
        <div className="flex items-start justify-between gap-3">
          <div
            className={`flex h-12 w-12 shrink-0 items-center justify-center bg-gradient-to-br ${cover} text-lg font-semibold text-white`}
          >
            {coverLetter}
          </div>
          <div className="flex items-center gap-1">
            <span className={`px-2 py-1 text-[11px] font-medium ${status.color}`}>{status.label}</span>
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
              className="hh-icon-btn-plain h-8 w-8 opacity-0 transition-opacity hover:text-red-500 focus-visible:opacity-100 group-hover:opacity-100"
              title="删除项目"
              aria-label="删除项目"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        <h3 className="mt-4 line-clamp-1 text-[17px] font-semibold tracking-tight text-content">{displayTitle}</h3>
        <p className="mt-1.5 line-clamp-2 min-h-[2.75rem] text-[13px] leading-[1.375rem] text-content-secondary">
          {project.description || '还没有添加简介，进入项目后可以继续补充世界观、剧情与角色设定。'}
        </p>

        {tags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {tags.map((g) => (
              <span key={g} className="hh-tag">
                {g.trim()}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="mt-auto flex items-center justify-between border-t border-surface-border/80 pt-3.5 text-xs text-content-tertiary">
        <span className="inline-flex items-center gap-1.5">
          <FileText className="h-3.5 w-3.5" />
          {formatWords(project.current_words)} 字
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5" />
          {formatDate(project.updated_at)}
        </span>
      </div>
    </article>
  )
}

/* ─── 统计 ─── */

function StatItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="px-5 py-4 md:px-6">
      <p className="text-xs text-content-tertiary">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-content tabular-nums">{value}</p>
    </div>
  )
}

/* ─── 更多菜单 ─── */

function MoreMenu({
  onImport,
  onExport,
  onExportTxt,
}: {
  onImport: () => void
  onExport: () => void
  onExportTxt: () => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const run = (fn: () => void) => () => {
    fn()
    setOpen(false)
  }

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} className="hh-icon-btn h-11 w-11" title="更多操作" aria-label="更多操作">
        <MoreHorizontal className="h-5 w-5" />
      </button>
      {open && (
        <div className="hh-menu absolute right-0 mt-2 w-44">
          <button onClick={run(onImport)} className="hh-menu-item">
            <Upload className="h-4 w-4 text-content-secondary" />
            导入项目
          </button>
          <button onClick={run(onExport)} className="hh-menu-item">
            <Download className="h-4 w-4 text-content-secondary" />
            导出项目
          </button>
          <button onClick={run(onExportTxt)} className="hh-menu-item">
            <FileText className="h-4 w-4 text-content-secondary" />
            导出 TXT
          </button>
        </div>
      )}
    </div>
  )
}

/* ─── 删除确认弹窗 ─── */

function DeleteDialog({
  project,
  onConfirm,
  onCancel,
}: {
  project: Project
  onConfirm: () => void
  onCancel: () => void
}) {
  return createPortal(
    <div className="hh-modal-mask" onClick={onCancel}>
      <div className="hh-modal max-w-[420px]" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div>
            <p className="hh-eyebrow text-red-500">危险操作</p>
            <h3 className="mt-2 text-xl font-semibold tracking-tight text-content">删除项目</h3>
          </div>
          <button onClick={onCancel} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="hh-modal-body">
          <p className="text-sm leading-7 text-content-secondary">
            确定要删除「<span className="font-medium text-content">{getDisplayTitle(project.title)}</span>」吗？
            项目下的世界观、角色、大纲与章节都会被永久删除，此操作不可撤销。
          </p>
        </div>
        <div className="hh-modal-foot">
          <button onClick={onCancel} className="hh-btn-ghost">
            取消
          </button>
          <button onClick={onConfirm} className="hh-btn-danger">
            <Trash2 className="h-4 w-4" />
            确认删除
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/* ─── 导入验证弹窗 ─── */

const IMPORT_STAT_LABELS: Record<string, string> = {
  characters: '角色',
  chapters: '章节',
  outlines: '总纲',
  volumes: '卷纲',
  chapter_outlines: '章纲',
  writing_styles: '写作风格',
  world_rules: '世界规则',
}

function ImportDialog({
  onClose,
  onSuccess,
}: {
  onClose: () => void
  onSuccess: (projectId?: string) => void
}) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [validating, setValidating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [validation, setValidation] = useState<{
    valid: boolean
    version: string
    project_name?: string
    statistics: Record<string, number>
    errors: string[]
    warnings: string[]
  } | null>(null)

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0]
    if (!selected) return
    setFile(selected)
    setValidation(null)
    setValidating(true)
    try {
      const result = await projectApi.validateImportFile(selected)
      setValidation(result)
    } catch {
      setValidation({
        valid: false,
        version: '',
        statistics: {},
        errors: ['文件验证失败，请检查文件格式'],
        warnings: [],
      })
    } finally {
      setValidating(false)
    }
  }

  const handleImport = async () => {
    if (!file || !validation?.valid) return
    setImporting(true)
    try {
      const result = await projectApi.importProject(file)
      if (result.success) {
        toast.success(result.message || '导入成功')
        onSuccess(result.project_id)
      }
    } catch {
      // api 拦截器已 toast
    } finally {
      setImporting(false)
    }
  }

  return createPortal(
    <div className="hh-modal-mask" onClick={onClose}>
      <div className="hh-modal max-w-[480px]" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div>
            <p className="hh-eyebrow">导入</p>
            <h3 className="mt-2 text-xl font-semibold tracking-tight text-content">导入项目</h3>
            <p className="mt-1 text-sm text-content-secondary">选择之前导出的 JSON 文件，验证通过后即可导入。</p>
          </div>
          <button onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="hh-modal-body space-y-4">
          <input ref={fileInputRef} type="file" accept=".json" className="hidden" onChange={handleFileSelect} />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex w-full flex-col items-center gap-2 border border-dashed border-brand/30 bg-white/50 px-6 py-8 text-center transition-colors hover:border-brand hover:bg-brand/5"
          >
            <span className="flex h-11 w-11 items-center justify-center bg-brand/10 text-brand">
              <Upload className="h-5 w-5" />
            </span>
            <span className="text-sm font-medium text-content">{file ? file.name : '点击选择 JSON 文件'}</span>
            <span className="text-xs text-content-tertiary">
              {file ? `${(file.size / 1024).toFixed(1)} KB` : '支持由本系统导出的项目文件'}
            </span>
          </button>

          {validating && (
            <div className="flex items-center gap-2 text-sm text-content-secondary">
              <Loader2 className="h-4 w-4 animate-spin text-brand" />
              正在验证文件...
            </div>
          )}

          {validation && !validating && (
            <div className="space-y-3">
              <div
                className={cn(
                  'flex items-center gap-2 text-sm font-medium',
                  validation.valid ? 'text-emerald-600' : 'text-red-600',
                )}
              >
                {validation.valid ? (
                  <>
                    <CheckCircle2 className="h-4 w-4" />
                    验证通过
                  </>
                ) : (
                  <>
                    <AlertTriangle className="h-4 w-4" />
                    验证失败
                  </>
                )}
              </div>

              {validation.project_name && (
                <div className="hh-subpanel px-4 py-3">
                  <p className="text-sm font-medium text-content">{validation.project_name}</p>
                  {validation.version && <p className="mt-0.5 text-xs text-content-tertiary">版本 {validation.version}</p>}
                </div>
              )}

              {Object.keys(validation.statistics).length > 0 && (
                <div className="hh-subpanel px-4 py-3">
                  <p className="mb-2 text-xs text-content-tertiary">数据统计</p>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
                    {Object.entries(validation.statistics).map(([key, value]) => (
                      <div key={key} className="flex justify-between text-xs">
                        <span className="text-content-secondary">{IMPORT_STAT_LABELS[key] || key}</span>
                        <span className="font-medium text-content tabular-nums">{value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {validation.errors.length > 0 && (
                <div className="space-y-1 border border-red-200 bg-red-50/80 px-4 py-3">
                  {validation.errors.map((err, i) => (
                    <p key={i} className="text-xs text-red-600">
                      • {err}
                    </p>
                  ))}
                </div>
              )}

              {validation.warnings.length > 0 && (
                <div className="space-y-1 border border-amber-200 bg-amber-50/80 px-4 py-3">
                  {validation.warnings.map((warn, i) => (
                    <p key={i} className="text-xs text-amber-700">
                      • {warn}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="hh-modal-foot">
          <button onClick={onClose} className="hh-btn-ghost">
            取消
          </button>
          <button onClick={handleImport} disabled={!validation?.valid || importing} className="hh-btn-primary">
            {importing && <Loader2 className="h-4 w-4 animate-spin" />}
            导入
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/* ─── 主页面 ─── */

export default function ProjectList() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { projects, loading, projectsInitialized } = useStore()
  const { refreshProjects, deleteProject } = useProjectSync()

  const [deletingProject, setDeletingProject] = useState<Project | null>(null)
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [showWizard, setShowWizard] = useState(false)
  // V3.2-A：拆书页跳转过来预选本书参考包。仅首次 mount 读取 + 状态保留，避免反复触发
  const [pendingPackTaskId, setPendingPackTaskId] = useState<string | null>(null)
  const inspirationOpen = searchParams.get('panel') === 'inspiration'

  const openInspiration = () => {
    const next = new URLSearchParams(searchParams)
    next.set('panel', 'inspiration')
    setSearchParams(next)
  }

  const closeInspiration = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('panel')
    setSearchParams(next, { replace: true })
  }

  // 初始化加载
  useEffect(() => {
    if (!projectsInitialized) {
      refreshProjects()
    }
  }, [projectsInitialized, refreshProjects])

  // V3.2-A：响应拆书页「以本书作参考创建项目」跳转（?wizard=1&pack_task_id=xxx）
  // 仅读一次，读后从 URL 移除参数避免刷新重复弹出
  useEffect(() => {
    if (searchParams.get('wizard') !== '1') return
    const taskId = searchParams.get('pack_task_id')
    setPendingPackTaskId(taskId)
    setShowWizard(true)
    const next = new URLSearchParams(searchParams)
    next.delete('wizard')
    next.delete('pack_task_id')
    setSearchParams(next, { replace: true })
    // 只需首次 mount 或 URL 变化时检查
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 统计数据
  const stats = useMemo(() => {
    const total = projects.length
    const writing = projects.filter((p) => p.status === 'writing').length
    const totalWords = projects.reduce((sum, p) => sum + (p.current_words || 0), 0)
    const completed = projects.filter((p) => p.status === 'completed').length
    return { total, writing, totalWords, completed }
  }, [projects])

  // 新建项目 — 打开向导弹窗
  const handleCreate = () => {
    setShowWizard(true)
  }

  // 向导创建完成（F5：支持 next_wizard_route 决定跳转目标）
  const handleWizardSuccess = async (
    projectId: string,
    options?: { nextRoute?: 'volume_planning' | 'chapter_outlines' }
  ) => {
    setShowWizard(false)
    await refreshProjects()
    if (options?.nextRoute === 'volume_planning') {
      navigate(`/project/${projectId}/outline/volumes`)
    } else {
      navigate(`/project/${projectId}`)
    }
  }

  const handleInspirationProjectCreated = async () => {
    await refreshProjects()
  }

  // F5：灵感模式完成跳转，同样支持 next_wizard_route
  const handleEnterInspiredProject = (
    projectId: string,
    options?: { nextRoute?: 'volume_planning' | 'chapter_outlines' }
  ) => {
    closeInspiration()
    if (options?.nextRoute === 'volume_planning') {
      navigate(`/project/${projectId}/outline/volumes`)
    } else {
      navigate(`/project/${projectId}`)
    }
  }

  // 删除项目
  const handleDelete = async () => {
    if (!deletingProject) return
    try {
      await deleteProject(deletingProject.id)
      toast.success('项目已删除')
    } catch {
      // api 拦截器已 toast
    } finally {
      setDeletingProject(null)
    }
  }

  // 导入项目
  const handleImport = () => {
    setShowImportDialog(true)
  }

  const handleImportSuccess = async (projectId?: string) => {
    setShowImportDialog(false)
    await refreshProjects()
    if (projectId) {
      navigate(`/project/${projectId}`)
    }
  }

  // 导出 — 如果只有一个项目直接导出，否则提示
  const handleExport = () => {
    if (projects.length === 0) {
      toast.info('暂无可导出的项目')
      return
    }
    if (projects.length === 1) {
      projectApi.exportProjectData(projects[0].id, {})
      return
    }
    toast.info('请进入具体项目后导出')
  }

  // TXT 导出
  const handleExportTxt = () => {
    if (projects.length === 0) {
      toast.info('暂无可导出的项目')
      return
    }
    if (projects.length === 1) {
      projectApi.exportTxt(projects[0].id)
      return
    }
    toast.info('请进入具体项目后导出 TXT')
  }

  // 加载中
  const showSkeleton = loading && !projectsInitialized
  const hasProjects = projects.length > 0
  // 空状态里已有两张「创建方式」卡片，避免顶部再出现一组相同按钮
  const showHeaderCreateActions = showSkeleton || hasProjects

  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">我的项目</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            在这里管理全部小说项目，随时回到最近推进的作品。
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2.5">
          {showHeaderCreateActions && (
            <>
              <button onClick={openInspiration} className="hh-btn-secondary">
                <Sparkles className="h-4 w-4 text-brand" />
                灵感模式
              </button>
              <button onClick={handleCreate} className="hh-btn-primary">
                <Plus className="h-4 w-4" />
                快速开始
              </button>
            </>
          )}
          <MoreMenu onImport={handleImport} onExport={handleExport} onExportTxt={handleExportTxt} />
        </div>
      </section>

      {hasProjects && (
        <section className="hh-panel grid grid-cols-2 divide-surface-border/80 md:grid-cols-4 md:divide-x">
          <StatItem label="项目总数" value={stats.total} />
          <StatItem label="创作中" value={stats.writing} />
          <StatItem label="已完成" value={stats.completed} />
          <StatItem label="累计字数" value={formatWords(stats.totalWords)} />
        </section>
      )}

      {showSkeleton ? (
        <SkeletonCards />
      ) : !hasProjects ? (
        <EmptyState onCreate={handleCreate} onInspiration={openInspiration} />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onClick={() => navigate(`/project/${project.id}`)}
              onDelete={() => setDeletingProject(project)}
            />
          ))}
        </div>
      )}

      <InspirationModal
        open={inspirationOpen}
        onClose={closeInspiration}
        onEnterProject={handleEnterInspiredProject}
        onProjectCreated={handleInspirationProjectCreated}
      />

      {/* 导入验证弹窗 */}
      {showImportDialog && (
        <ImportDialog
          onClose={() => setShowImportDialog(false)}
          onSuccess={handleImportSuccess}
        />
      )}

      {/* 删除确认弹窗 */}
      {deletingProject && (
        <DeleteDialog
          project={deletingProject}
          onConfirm={handleDelete}
          onCancel={() => setDeletingProject(null)}
        />
      )}

      {/* 向导创建弹窗 */}
      {showWizard && (
        <WizardModal
          onClose={() => {
            setShowWizard(false)
            setPendingPackTaskId(null)
          }}
          onSuccess={handleWizardSuccess}
          initialPackTaskId={pendingPackTaskId}
        />
      )}
    </div>
  )
}

/* ─── 快速开始向导弹窗 ─── */

type WizardPhase = 'form' | 'generating' | 'done'
type GenStep = 'pending' | 'processing' | 'completed' | 'error'

interface WizardForm {
  title: string
  description: string
  theme: string
  genre: string
  narrative_perspective: string
  target_words: number
  chapter_count: number
  character_count: number
  requirements: string
  /** 目标平台（空 = 通用） */
  platform_preset: PlatformPreset | ''
}

const DEFAULT_WIZARD_FORM: WizardForm = {
  title: '',
  description: '',
  theme: '',
  genre: '',
  narrative_perspective: '第三人称',
  target_words: 100000,
  chapter_count: 30,
  character_count: 5,
  requirements: '',
  platform_preset: '',
}

const PLATFORM_CHOICES: { value: PlatformPreset | ''; label: string }[] = [
  { value: '', label: '通用' },
  { value: 'qidian', label: '起点（付费）' },
  { value: 'fanqie', label: '番茄（免费）' },
  { value: 'jinjiang', label: '晋江（女频）' },
  { value: 'qimao', label: '七猫（免费）' },
]

const GENRE_OPTIONS = ['玄幻', '奇幻', '武侠', '仙侠', '都市', '现实', '历史', '军事', '游戏', '体育', '科幻', '悬疑', '灵异', '二次元', '言情', '现言', '古言']
const PERSPECTIVE_OPTIONS = ['第一人称', '第三人称', '全知视角']

function ToggleRow({
  checked,
  onChange,
  title,
  description,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  title: string
  description: ReactNode
}) {
  return (
    <label className="hh-subpanel flex cursor-pointer items-start gap-3 px-4 py-3">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-1 h-4 w-4" />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-content">{title}</span>
        <span className="mt-0.5 block text-xs leading-5 text-content-secondary">{description}</span>
      </span>
    </label>
  )
}

function StepRow({ status, title, description }: { status: GenStep; title: string; description: string }) {
  const icon =
    status === 'completed' ? (
      <CheckCircle2 className="h-5 w-5 text-emerald-500" />
    ) : status === 'processing' ? (
      <Loader2 className="h-5 w-5 animate-spin text-brand" />
    ) : status === 'error' ? (
      <AlertTriangle className="h-5 w-5 text-red-500" />
    ) : (
      <span className="block h-5 w-5 border-2 border-surface-border" />
    )

  return (
    <li className={cn('flex items-center gap-3.5 px-4 py-3.5', status === 'pending' && 'opacity-60')}>
      {icon}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-content">{title}</p>
        <p className="text-xs text-content-tertiary">{description}</p>
      </div>
      <span className="text-xs text-content-tertiary">
        {status === 'completed' ? '已完成' : status === 'processing' ? '生成中' : status === 'error' ? '失败' : '等待中'}
      </span>
    </li>
  )
}

function WizardModal({
  onClose,
  onSuccess,
  initialPackTaskId,
}: {
  onClose: () => void;
  onSuccess: (
    projectId: string,
    options?: { nextRoute?: 'volume_planning' | 'chapter_outlines' }
  ) => void;
  /** V3.2-A：拆书页跳转过来时传入，在 mount 后拉取该任务对应的参考包预填 */
  initialPackTaskId?: string | null;
}) {
  const [form, setForm] = useState<WizardForm>(DEFAULT_WIZARD_FORM)
  const [phase, setPhase] = useState<WizardPhase>('form')
  const [progress, setProgress] = useState(0)
  const [progressMsg, setProgressMsg] = useState('')
  const [steps, setSteps] = useState<{ world: GenStep; chars: GenStep; outline: GenStep; lines: GenStep }>({ world: 'pending', chars: 'pending', outline: 'pending', lines: 'pending' })
  const [projectId, setProjectId] = useState('')
  const [error, setError] = useState('')
  const [minimized, setMinimized] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [selectedPlugins, setSelectedPlugins] = useState<string[]>([])
  const [enableMcp, setEnableMcp] = useState(false)
  // V3.2-B：拆书参考包选择状态（项目创建后后端会自动挂载）
  const [refPack, setRefPack] = useState<ReferencePackSelectorValue>(DEFAULT_REF_PACK_VALUE)

  // 分步确认：每阶段生成完暂停，用户确认后再继续（贴合人类"逐层沉淀再展开"的创作节奏）
  const [stepConfirm, setStepConfirm] = useState(true)
  const [awaitingStep, setAwaitingStep] = useState<null | 'chars' | 'outline' | 'lines'>(null)
  const [worldPreview, setWorldPreview] = useState<{ time_period?: string; location?: string; atmosphere?: string; rules?: string } | null>(null)
  const [charsPreview, setCharsPreview] = useState<string[]>([])
  const [linesPreview, setLinesPreview] = useState('')
  const continueGateRef = useRef<(() => void) | null>(null)

  /** 暂停生成流水线，等待用户点击「继续」 */
  const waitForConfirm = (step: 'chars' | 'outline' | 'lines', progressVal: number, msg: string) =>
    new Promise<void>((resolve) => {
      setAwaitingStep(step)
      setProgress(progressVal)
      setProgressMsg(msg)
      continueGateRef.current = () => {
        setAwaitingStep(null)
        continueGateRef.current = null
        resolve()
      }
    })

  // V3.2-A：从拆书页跳转过来时，根据 task_id 拉取对应的参考包并预填 refPack
  useEffect(() => {
    if (!initialPackTaskId) return
    let cancelled = false
    referencePackApi
      .list()
      .then((packs) => {
        if (cancelled) return
        const matched = (packs ?? []).find((p) => p.task_id === initialPackTaskId)
        if (!matched) {
          toast.warning('该拆书任务未生成参考包，请手动选择')
          return
        }
        if (matched.status !== 'ready' && matched.status !== 'partial') {
          toast.warning(`该参考包状态为 ${matched.status}，未就绪，请稍后重试`)
          return
        }
        setRefPack({
          enabled: true,
          packIds: [matched.id],
          dimensions: [],
          strength: 'medium',
        })
        setAdvancedOpen(true)
        toast.success(`已预选拆书参考包：${matched.source_book_title}`)
      })
      .catch(() => {
        // api 拦截器已 toast
      })
    return () => {
      cancelled = true
    }
  }, [initialPackTaskId])
  // 把 refPack 转为 R8 API payload。未启用返空对象。
  const r8Payload = (): { pack_ids?: string[]; dimensions?: string[]; strength?: 'light' | 'medium' | 'deep' } =>
    !refPack.enabled
      ? {}
      : {
          pack_ids: refPack.packIds.length > 0 ? refPack.packIds : undefined,
          dimensions: refPack.dimensions.length > 0 ? refPack.dimensions : undefined,
          strength: refPack.strength,
        }
  const abortRef = useRef<AbortController | null>(null)

  const updateField = <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => {
    setForm(prev => ({ ...prev, [key]: value }))
  }

  /** 类型多选切换：用顿号拼接维护，已选则取消、未选则追加（与后端 _resolve_genre_guide 约定一致） */
  const toggleGenre = (g: string) => {
    setForm(prev => {
      const current = (prev.genre || '').split('、').map(s => s.trim()).filter(Boolean)
      const next = current.includes(g) ? current.filter(x => x !== g) : [...current, g]
      return { ...prev, genre: next.join('、') }
    })
  }

  /** 判断某类型是否被选中 */
  const isGenreSelected = (g: string): boolean => {
    if (!form.genre) return false
    return form.genre.split('、').map(s => s.trim()).includes(g)
  }

  const canSubmit = form.title.trim() && form.description.trim()

  const handleStart = async () => {
    if (!canSubmit) return
    setPhase('generating')
    setError('')

    try {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      // Step 1: 世界观
      setSteps(s => ({ ...s, world: 'processing' }))
      setProgressMsg('正在生成世界观...')
      setProgress(5)

      const worldResult = await wizardStreamApi.generateWorldBuildingStream(
        {
          title: form.title.trim(),
          description: form.description.trim(),
          theme: form.theme.trim() || form.title.trim(),
          genre: form.genre || '玄幻',
          narrative_perspective: form.narrative_perspective,
          target_words: form.target_words,
          chapter_count: form.chapter_count,
          character_count: form.character_count,
          enable_mcp: enableMcp,
          selected_plugins: selectedPlugins,
          // V3.2-B：透传拆书参考包；项目创建成功后后端会自动挂载
          ...r8Payload(),
          // 长篇设置：平台预设（单章字数与写法提示）
          ...(form.platform_preset ? { platform_preset: form.platform_preset } : {}),
        },
        {
          signal: controller.signal,
          onProgress: (msg, prog) => {
            setProgressMsg(msg)
            setProgress(Math.floor(prog / 4))
          },
          onResult: (result) => {
            setProjectId(result.project_id)
            const r = result as { time_period?: string; location?: string; atmosphere?: string; rules?: string }
            setWorldPreview({ time_period: r.time_period, location: r.location, atmosphere: r.atmosphere, rules: r.rules })
            setSteps(s => ({ ...s, world: 'completed' }))
          },
          onError: (err) => {
            setSteps(s => ({ ...s, world: 'error' }))
            throw new Error(err)
          },
        }
      )

      if (controller.signal.aborted) return
      if (!worldResult?.project_id) throw new Error('项目创建失败')
      const pid = worldResult.project_id

      // 分步确认：世界观完成后暂停，可先去项目里查看/修改再继续
      if (stepConfirm) {
        await waitForConfirm('chars', 25, '世界观已生成，请确认后继续')
      }
      if (controller.signal.aborted) return

      // Step 2: 角色
      setSteps(s => ({ ...s, chars: 'processing' }))
      setProgressMsg('正在生成角色...')
      setProgress(25)

      await wizardStreamApi.generateCharactersStream(
        {
          project_id: pid,
          count: form.character_count,
          theme: form.theme.trim() || undefined,
          genre: form.genre || undefined,
          requirements: form.requirements.trim() || undefined,
          enable_mcp: enableMcp,
          selected_plugins: selectedPlugins,
          // V3.2-B：后端读项目挂载列表，此处继续透传以便后端有显式选择优先级
          ...r8Payload(),
        },
        {
          signal: controller.signal,
          onProgress: (msg, prog) => {
            setProgressMsg(msg)
            setProgress(25 + Math.floor(prog / 4))
          },
          onResult: (result) => {
            const chars = (result as { characters?: Array<{ name?: string }> }).characters || []
            setCharsPreview(chars.slice(0, 6).map(c => String(c.name || '')).filter(Boolean))
            setSteps(s => ({ ...s, chars: 'completed' }))
          },
          onError: (err) => {
            setSteps(s => ({ ...s, chars: 'error' }))
            throw new Error(err)
          },
        }
      )

      if (controller.signal.aborted) return

      // 分步确认：角色完成后暂停
      if (stepConfirm) {
        await waitForConfirm('outline', 50, '角色已生成，请确认后继续')
      }
      if (controller.signal.aborted) return

      // Step 3: 大纲
      setSteps(s => ({ ...s, outline: 'processing' }))
      setProgressMsg('正在生成故事大纲...')
      setProgress(50)

      await wizardStreamApi.generateCompleteOutlineStream(
        {
          project_id: pid,
          chapter_count: form.chapter_count,
          narrative_perspective: form.narrative_perspective,
          target_words: form.target_words,
          requirements: form.requirements.trim() || undefined,
          enable_mcp: enableMcp,
          selected_plugins: selectedPlugins,
          // V3.2-B：透传拆书参考包选择
          ...r8Payload(),
        },
        {
          signal: controller.signal,
          onProgress: (msg, prog) => {
            setProgressMsg(msg)
            setProgress(50 + Math.floor(prog / 4))
          },
          onResult: () => {
            setSteps(s => ({ ...s, outline: 'completed' }))
          },
          onError: (err) => {
            setSteps(s => ({ ...s, outline: 'error' }))
            throw new Error(err)
          },
        }
      )

      if (controller.signal.aborted) return
      if (stepConfirm) {
        await waitForConfirm('lines', 75, '故事大纲已生成，请确认后继续生成卷纲')
      }
      if (controller.signal.aborted) return

      // Step 4: 卷纲（按总纲分卷，并把第 1 卷细化为剧情单元；全书章数 = 项目章节数）
      setSteps(s => ({ ...s, lines: 'processing' }))
      setProgressMsg('正在生成卷纲...')
      setProgress(75)

      await wizardStreamApi.generateVolumesStream(
        {
          project_id: pid,
          chapter_count: form.chapter_count,
        },
        {
          signal: controller.signal,
          onProgress: (msg, prog) => {
            setProgressMsg(msg)
            setProgress(75 + Math.floor(prog / 4))
          },
          onResult: (result) => {
            setLinesPreview(
              `共 ${result.volumes.length} 卷 / ${result.chapter_count} 章：` +
              result.volumes.slice(0, 4).map(v => `《${v.title}》`).join('、') +
              (result.volumes.length > 4 ? ' …' : '')
            )
            setSteps(s => ({ ...s, lines: 'completed' }))
          },
          onError: (err) => {
            setSteps(s => ({ ...s, lines: 'error' }))
            throw new Error(err)
          },
        }
      )

      setProgress(100)
      setProgressMsg('项目创建完成！')
      setPhase('done')
      toast.success('项目创建成功！')
    } catch (err) {
      const error = err as { name?: string; message?: string }
      if (error.name === 'AbortError') {
        return
      }
      setError(error.message || 'Creation failed')
      toast.error('Project creation failed: ' + (error.message || 'Unknown error'))
    }
  }

  const handleStop = () => {
    abortRef.current?.abort()
    // 若正处于分步确认暂停中，释放闸门让流水线感知 abort 并退出
    continueGateRef.current?.()
    setAwaitingStep(null)
    setError('已手动停止生成')
    setProgressMsg('已停止')
    // 如果已经创建了项目，可以进入项目查看已生成的部分
    if (projectId) {
      setPhase('done')
    }
  }

  const handleDirectCreate = async () => {
    if (!form.title.trim()) return
    try {
      const created = await projectApi.createProject({
        title: form.title.trim(),
        description: form.description.trim() || undefined,
        theme: form.theme.trim() || undefined,
        genre: form.genre || undefined,
        target_words: form.target_words || undefined,
        narrative_perspective: form.narrative_perspective || undefined,
        chapter_count: form.chapter_count || undefined,
        character_count: form.character_count || undefined,
      })
      toast.success('项目已创建')
      onSuccess(created.id)
    } catch { /* api 拦截器已 toast */ }
  }

  const enterProject = () => onSuccess(projectId, { nextRoute: 'volume_planning' })
  const enterLabel = '进入卷纲规划'
  const isSuccess = phase === 'done' && !error
  const canClose = phase === 'form' || phase === 'done' || Boolean(error)

  const advancedSummary = [
    stepConfirm ? '分步确认' : '连续生成',
    refPack.enabled ? '拆书参考已启用' : '未用拆书参考',
    enableMcp ? 'MCP 已启用' : '未用 MCP',
  ].join(' · ')

  // 最小化视图
  if (minimized) {
    return createPortal(
      <div className="hh-glass fixed bottom-5 right-5 z-50 w-80 overflow-hidden animate-fade-in">
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            {phase === 'generating' && !awaitingStep && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand" />}
            {phase === 'generating' && awaitingStep && <CheckCircle2 className="h-4 w-4 shrink-0 text-amber-500" />}
            {phase === 'done' && <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />}
            <span className="truncate text-sm font-medium text-content">
              {phase === 'done' ? '创建完成' : awaitingStep ? '等待确认 · 展开继续' : form.title || '生成中...'}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-0.5">
            <button onClick={() => setMinimized(false)} className="hh-icon-btn-plain h-8 w-8" title="展开" aria-label="展开">
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
            {phase === 'generating' && !error && (
              <button onClick={handleStop} className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="停止" aria-label="停止">
                <StopCircle className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
        <div className="hh-progress h-1">
          <div className="hh-progress-bar" style={{ width: `${Math.min(progress, 100)}%` }} />
        </div>
        {phase === 'done' && projectId && (
          <div className="p-3">
            <button onClick={enterProject} className="hh-btn-primary hh-btn-sm w-full">
              {enterLabel}
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>,
      document.body,
    )
  }

  return createPortal(
    <div className="hh-modal-mask">
      <div className="hh-modal max-w-[640px]" role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div className="min-w-0">
            <p className="hh-eyebrow">快速开始</p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">
              {phase === 'form' ? '新建小说项目' : isSuccess ? '项目创建完成' : error ? '生成已停止' : '正在生成设定'}
            </h2>
            <p className="mt-1 text-sm text-content-secondary">
              {phase === 'form'
                ? '填好书名与简介，AI 将依次生成世界观、角色、总纲与卷纲。'
                : isSuccess
                  ? '设定与卷纲已就位，下一步在卷纲里逐个剧情单元生成章纲，确认后就能开写。'
                  : `《${form.title}》`}
            </p>
          </div>
          {canClose && (
            <button onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" title="关闭" aria-label="关闭">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        <div className="hh-modal-body">
          {phase === 'form' && (
            <div className="space-y-5">
              <div>
                <label className="hh-label">
                  书名 <span className="text-red-500">*</span>
                </label>
                <input
                  value={form.title}
                  onChange={e => updateField('title', e.target.value)}
                  placeholder="给你的小说起个名字"
                  className="hh-field"
                  autoFocus
                />
              </div>

              <div>
                <label className="hh-label">
                  简介 <span className="text-red-500">*</span>
                </label>
                <textarea
                  value={form.description}
                  onChange={e => updateField('description', e.target.value)}
                  placeholder="用几句话描述核心故事：主角是谁、遇到什么、想要什么……"
                  rows={3}
                  className="hh-textarea"
                />
              </div>

              <div>
                <label className="hh-label">主题</label>
                <input
                  value={form.theme}
                  onChange={e => updateField('theme', e.target.value)}
                  placeholder="如：成长、复仇、救赎（可选）"
                  className="hh-field"
                />
              </div>

              <div>
                <label className="hh-label">
                  类型
                  <span className="ml-1.5 text-xs font-normal text-content-tertiary">可多选，组合融合</span>
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {GENRE_OPTIONS.map(g => {
                    const selected = isGenreSelected(g)
                    return (
                      <button
                        key={g}
                        type="button"
                        onClick={() => toggleGenre(g)}
                        className={cn('hh-chip', selected && 'hh-chip--active')}
                      >
                        {g}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div>
                <label className="hh-label">叙事视角</label>
                <div className="inline-flex border border-surface-border bg-white/60 p-1">
                  {PERSPECTIVE_OPTIONS.map(p => {
                    const selected = form.narrative_perspective === p
                    return (
                      <button
                        key={p}
                        type="button"
                        onClick={() => updateField('narrative_perspective', p)}
                        className={cn(
                          'px-3.5 py-1.5 text-xs font-medium transition-colors',
                          selected ? 'bg-brand text-white' : 'text-content-secondary hover:text-content',
                        )}
                      >
                        {p}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="hh-label">目标字数</label>
                  <input
                    type="number"
                    value={form.target_words}
                    onChange={e => updateField('target_words', Number(e.target.value))}
                    className="hh-field"
                  />
                </div>
                <div>
                  <label className="hh-label">章节数</label>
                  <input
                    type="number"
                    value={form.chapter_count}
                    onChange={e => {
                      const n = Number(e.target.value)
                      updateField('chapter_count', n)
                    }}
                    className="hh-field"
                  />
                </div>
                <div>
                  <label className="hh-label">角色数</label>
                  <input
                    type="number"
                    value={form.character_count}
                    onChange={e => updateField('character_count', Number(e.target.value))}
                    className="hh-field"
                  />
                </div>
              </div>

              <div>
                <div>
                  <label className="hh-label">目标平台</label>
                  <select
                    value={form.platform_preset}
                    onChange={e => updateField('platform_preset', e.target.value as PlatformPreset | '')}
                    className="hh-field"
                  >
                    {PLATFORM_CHOICES.map(p => (
                      <option key={p.value || 'generic'} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="hh-label">额外要求</label>
                <textarea
                  value={form.requirements}
                  onChange={e => updateField('requirements', e.target.value)}
                  placeholder="对角色、世界观、大纲的特殊要求（可选）"
                  rows={2}
                  className="hh-textarea"
                />
              </div>

              <div className="border-t border-surface-border/80 pt-4">
                <button
                  type="button"
                  onClick={() => setAdvancedOpen(v => !v)}
                  className="flex w-full items-center justify-between gap-3 text-left"
                >
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-content">高级选项</span>
                    <span className="mt-0.5 block truncate text-xs text-content-tertiary">{advancedSummary}</span>
                  </span>
                  {advancedOpen ? (
                    <ChevronUp className="h-4 w-4 shrink-0 text-content-tertiary" />
                  ) : (
                    <ChevronDown className="h-4 w-4 shrink-0 text-content-tertiary" />
                  )}
                </button>

                {advancedOpen && (
                  <div className="mt-4 space-y-3">
                    {/* V3.2-B：拆书参考包选择器（项目创建前选包，创建后自动挂载） */}
                    <ReferencePackSelector
                      value={refPack}
                      onChange={setRefPack}
                      disabledTitle="拆书参考包"
                      hint="项目创建后会自动挂载到项目"
                    />

                    {/* MCP 插件 */}
                    <MCPSelector
                      value={{ enable: enableMcp, selected: selectedPlugins }}
                      onChange={({ enable, selected }) => {
                        setEnableMcp(enable)
                        setSelectedPlugins(selected)
                      }}
                    />

                    {/* 分步确认开关：世界观/角色各生成完暂停确认 */}
                    <ToggleRow
                      checked={stepConfirm}
                      onChange={setStepConfirm}
                      title="分步确认（推荐）"
                      description="世界观、角色、大纲各生成完先暂停，确认满意（可去项目页修改）再继续下一步；关闭后四步连跑不打断。"
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          {(phase === 'generating' || phase === 'done') && (
            <div className="space-y-5">
              {isSuccess && (
                <div className="flex flex-col items-center py-2 text-center">
                  <span className="flex h-14 w-14 items-center justify-center bg-emerald-50 text-emerald-500">
                    <CheckCircle2 className="h-7 w-7" />
                  </span>
                  <p className="mt-4 text-lg font-semibold text-content">《{form.title}》已创建</p>
                </div>
              )}

              <ol className="hh-subpanel divide-y divide-surface-border/80">
                <StepRow status={steps.world} title="世界观构建" description="时代、地点、氛围与核心规则" />
                <StepRow status={steps.chars} title="角色生成" description={`${form.character_count} 位主要角色及关系`} />
                <StepRow status={steps.outline} title="总纲" description={`${form.chapter_count} 章的全书主线`} />
                <StepRow status={steps.lines} title="卷纲" description="按总纲分卷，第 1 卷细化为剧情单元" />
              </ol>
              {isSuccess && linesPreview && (
                <p className="text-xs leading-6 text-content-secondary">{linesPreview}</p>
              )}

              {!isSuccess && (
                <div>
                  <div className="flex items-center justify-between text-xs text-content-secondary">
                    <span className="truncate">{progressMsg}</span>
                    <span className="ml-3 shrink-0 tabular-nums">{Math.round(progress)}%</span>
                  </div>
                  <div className="hh-progress mt-2">
                    <div className="hh-progress-bar" style={{ width: `${Math.min(progress, 100)}%` }} />
                  </div>
                </div>
              )}

              {/* 分步确认：阶段完成后的暂停确认卡 */}
              {awaitingStep && !error && phase === 'generating' && (
                <div className="space-y-3 border border-brand/25 bg-brand/5 p-4">
                  <p className="text-sm font-medium text-content">
                    {awaitingStep === 'chars' ? '世界观已生成，确认后继续生成角色' : awaitingStep === 'outline' ? '角色已生成，确认后继续生成故事大纲' : '总纲已生成，确认后继续生成卷纲'}
                  </p>
                  {awaitingStep === 'chars' && worldPreview && (
                    <dl className="grid gap-x-4 gap-y-1 text-xs leading-6 text-content-secondary sm:grid-cols-[auto_1fr]">
                      <dt className="text-content-tertiary">时代</dt>
                      <dd>{worldPreview.time_period || '—'}</dd>
                      <dt className="text-content-tertiary">地点</dt>
                      <dd>{worldPreview.location || '—'}</dd>
                      <dt className="text-content-tertiary">氛围</dt>
                      <dd>{worldPreview.atmosphere || '—'}</dd>
                      {worldPreview.rules && (
                        <>
                          <dt className="text-content-tertiary">规则</dt>
                          <dd className="line-clamp-3">{worldPreview.rules}</dd>
                        </>
                      )}
                    </dl>
                  )}
                  {awaitingStep === 'outline' && charsPreview.length > 0 && (
                    <p className="text-xs leading-6 text-content-secondary">已生成角色：{charsPreview.join('、')}</p>
                  )}
                  <p className="text-[11px] leading-5 text-content-tertiary">
                    不满意？可先「缩小到后台」，去项目页修改{awaitingStep === 'chars' ? '世界观设定' : awaitingStep === 'outline' ? '角色设定' : '故事大纲'}后再回来继续，后续步骤会基于最新数据生成。
                  </p>
                  <button onClick={() => continueGateRef.current?.()} className="hh-btn-primary hh-btn-sm">
                    <Sparkles className="h-3.5 w-3.5" />
                    继续生成{awaitingStep === 'chars' ? '角色' : awaitingStep === 'outline' ? '总纲' : '卷纲'}
                  </button>
                </div>
              )}

              {error && (
                <div className="flex items-start gap-2 border border-red-200 bg-red-50/80 px-4 py-3 text-sm text-red-600">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="hh-modal-foot">
          {phase === 'form' && (
            <>
              <button onClick={onClose} className="hh-btn-ghost">
                取消
              </button>
              <button onClick={handleDirectCreate} disabled={!form.title.trim()} className="hh-btn-secondary" title="只创建项目，不生成任何内容">
                直接创建
              </button>
              <button onClick={handleStart} disabled={!canSubmit} className="hh-btn-primary">
                <Wand2 className="h-4 w-4" />
                AI 生成
              </button>
            </>
          )}
          {phase === 'generating' && !error && (
            <>
              <button onClick={() => setMinimized(true)} className="hh-btn-ghost mr-auto">
                <Minimize2 className="h-4 w-4" />
                缩小到后台
              </button>
              <button onClick={handleStop} className="hh-btn-ghost text-red-500 hover:bg-red-50 hover:text-red-600">
                <StopCircle className="h-4 w-4" />
                停止生成
              </button>
            </>
          )}
          {(phase === 'done' || (phase === 'generating' && error)) && projectId && (
            <button onClick={enterProject} className="hh-btn-primary">
              {enterLabel}
              <ArrowRight className="h-4 w-4" />
            </button>
          )}
          {error && !projectId && (
            <button onClick={onClose} className="hh-btn-secondary">
              关闭
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
