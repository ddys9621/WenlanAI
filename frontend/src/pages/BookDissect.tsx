import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  FileText,
  Loader2,
  Play,
  Sparkles,
  StopCircle,
  Trash2,
  Upload,
  Wand2,
} from 'lucide-react'
import { toast } from 'sonner'
import { bookDissectApi, referencePackApi } from '@/services/api'
import { useAIJobsStore, useRunningAIJobs } from '@/store/aiJobsStore'
import type { AIJobSummary } from '@/types/ai_job'
import type {
  BookDissectExtractionOptions,
  BookDissectStage,
  BookDissectStatus,
  BookDissectTask,
} from '@/types'
import { BookDissectExtractionModal } from '@/components/BookDissectExtractionModal'
import { BookDissectV2View } from './BookDissectV2View'

const ACCEPT_TYPES = '.txt,.md,.markdown'
const MAX_BYTES = 10 * 1024 * 1024
const POLL_INTERVAL_MS = 3000
/** 后端 ai_jobs 里拆书抽取任务的 kind（meta.task_id 对应拆书任务 id） */
const DISSECT_JOB_KINDS = ['book_dissect']

const STAGE_LABELS: Record<string, string> = {
  // V2 阶段
  splitting: '章节切分',
  scanning: '实体扫描',
  dictionary: '字典分类',
  extracting: '章节抽取',
  aggregating: '全书聚合',
  synthesizing: '生成概览',
  // 通用
  split_done: '已切分，待抽取',
  queued: '排队中',
  done: '完成',
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function formatNumber(num: number): string {
  return num.toLocaleString('zh-CN')
}

function formatDate(iso?: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

function statusBadgeClass(status: BookDissectStatus): string {
  switch (status) {
    case 'completed':
      return 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30'
    case 'running':
      return 'bg-blue-500/15 text-blue-300 ring-1 ring-blue-500/30'
    case 'failed':
      return 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30'
    case 'cancelled':
      return 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30'
    default:
      return 'bg-white/5 text-content-secondary ring-1 ring-white/10'
  }
}

function stageLabel(stage?: BookDissectStage | null): string {
  if (!stage) return ''
  return STAGE_LABELS[stage] ?? stage
}

/** 状态徽标文案：手动停止显示「已停止」，其余沿用阶段名 */
function statusText(task: BookDissectTask): string {
  if (task.status === 'cancelled') return '已停止'
  return stageLabel(task.stage) || task.status
}

export default function BookDissect() {
  const [tasks, setTasks] = useState<BookDissectTask[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [extractionModalOpen, setExtractionModalOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const pollTimerRef = useRef<number | null>(null)
  // 抽取跑在通用 AI 后台任务里：启动后接入弹窗 / 托盘；刷新后由 AIJobHost.syncFromServer 找回运行中的任务
  const attachJob = useAIJobsStore((s) => s.attach)
  const openJobModal = useAIJobsStore((s) => s.openModal)
  const runningDissectJobs = useRunningAIJobs(null, DISSECT_JOB_KINDS)

  // ============================================================
  // 数据加载
  // ============================================================

  const fetchAll = useCallback(async () => {
    try {
      setLoading(true)
      const list = await bookDissectApi.listTasks()
      setTasks(list)
      // 默认选中第一个
      if (list.length > 0) {
        setSelectedId((prev) => prev ?? list[0].id)
      } else {
        setSelectedId(null)
      }
    } catch {
      /* api 拦截器已 toast */
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchOne = useCallback(async (taskId: string): Promise<BookDissectTask | null> => {
    try {
      const t = await bookDissectApi.getTask(taskId)
      setTasks((prev) => prev.map((x) => (x.id === t.id ? t : x)))
      return t
    } catch {
      return null
    }
  }, [])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  // ============================================================
  // running 状态自动轮询
  // ============================================================

  const selectedTask = useMemo(
    () => tasks.find((t) => t.id === selectedId) ?? null,
    [tasks, selectedId],
  )
  const selectedTaskId = selectedTask?.id
  const selectedTaskStatus = selectedTask?.status
  // 当前任务对应的后台 AI 任务（弹窗最小化后从这里「查看任务」重新打开）
  const selectedJob = useMemo(
    () => runningDissectJobs.find((j) => j.meta?.task_id === selectedTaskId) ?? null,
    [runningDissectJobs, selectedTaskId],
  )
  const selectedJobId = selectedJob?.id ?? null

  useEffect(() => {
    if (!selectedTaskId || selectedTaskStatus !== 'running') {
      if (pollTimerRef.current) {
        window.clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
      return
    }
    // 启动轮询
    pollTimerRef.current = window.setInterval(() => {
      fetchOne(selectedTaskId)
    }, POLL_INTERVAL_MS)
    return () => {
      if (pollTimerRef.current) {
        window.clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [selectedTaskId, selectedTaskStatus, fetchOne])

  // 后台任务到终态（完成 / 失败 / 停止）立刻刷新任务，不等下一次轮询
  useEffect(() => {
    if (!selectedJobId || !selectedTaskId) return
    return useAIJobsStore.getState().onSettled(selectedJobId, () => void fetchOne(selectedTaskId))
  }, [selectedJobId, selectedTaskId, fetchOne])

  // ============================================================
  // 上传
  // ============================================================

  const handleSelectFile = () => fileInputRef.current?.click()

  const handleFileChosen = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // 允许重复选择同一文件
    if (!file) return
    if (file.size > MAX_BYTES) {
      toast.error(`文件过大（${formatBytes(file.size)}），上限 10 MB`)
      return
    }
    try {
      setUploading(true)
      const resp = await bookDissectApi.upload(file)
      toast.success(
        `上传完成：识别 ${resp.chapter_count} 章，编码 ${resp.encoding}`,
      )
      await fetchAll()
      setSelectedId(resp.task_id)
    } catch {
      /* api 拦截器已 toast */
    } finally {
      setUploading(false)
    }
  }

  // ============================================================
  // 启动抽取 / 删除
  // ============================================================

  const handleStartExtraction = async (options: BookDissectExtractionOptions) => {
    if (!selectedTask) return
    try {
      setExtracting(true)
      const t = await bookDissectApi.startExtraction(selectedTask.id, options)
      setTasks((prev) => prev.map((x) => (x.id === t.id ? t : x)))
      setExtractionModalOpen(false)
      // 接入通用 AI 任务弹窗：实时进度 / 模型调用 / 阶段，可最小化到托盘、可停止
      if (t.job_id) {
        try {
          await attachJob(t.job_id)
          openJobModal(t.job_id)
          return
        } catch {
          /* 快照拉取失败：退回页面轮询显示进度 */
        }
      }
      const scope = options.chapter_limit ? `前 ${options.chapter_limit} 章` : '全书'
      toast.success(`已排队抽取（${scope}）…`)
    } catch {
      /* api 拦截器已 toast */
    } finally {
      setExtracting(false)
    }
  }

  const handleCancelExtraction = async () => {
    if (!selectedTask || selectedTask.status !== 'running') return
    const done = selectedTask.chapters_extracted ?? 0
    const hint = done > 0 ? `已抽取的 ${done} 章事实会保留，` : ''
    if (!confirm(`确定停止「${selectedTask.file_name ?? selectedTask.id}」的抽取？${hint}之后可重新抽取。`)) return
    try {
      setCancelling(true)
      const t = await bookDissectApi.cancelExtraction(selectedTask.id)
      setTasks((prev) => prev.map((x) => (x.id === t.id ? t : x)))
      toast.success('已停止抽取')
    } catch {
      /* api 拦截器已 toast */
    } finally {
      setCancelling(false)
    }
  }

  const handleDelete = async (task: BookDissectTask) => {
    const runningHint = task.status === 'running' ? '（正在抽取，会先停止）' : ''
    if (!confirm(`确定删除「${task.file_name ?? task.id}」${runningHint}？`)) return
    try {
      await bookDissectApi.deleteTask(task.id)
      setTasks((prev) => prev.filter((x) => x.id !== task.id))
      if (selectedId === task.id) setSelectedId(null)
      toast.success('已删除')
    } catch {
      /* api 拦截器已 toast */
    }
  }

  // ============================================================
  // 渲染
  // ============================================================

  return (
    <div className="space-y-6">
      {/* 标题 + 红字声明 */}
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="rounded-2xl bg-brand/15 p-2.5 ring-1 ring-brand/30">
              <BookOpen className="h-5 w-5 text-brand" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-content">拆书参考</h1>
              <p className="mt-0.5 text-sm text-content-secondary">
                上传一本 txt/md 参考小说，反向拆解为创作素材，可一键填充新建项目向导。
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleSelectFile}
            disabled={uploading}
            className="inline-flex items-center gap-1.5 rounded-btn bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {uploading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
            {uploading ? '上传中…' : '上传参考书'}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT_TYPES}
            onChange={handleFileChosen}
            className="hidden"
          />
        </div>

        <div className="flex items-start gap-2 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            <span className="font-semibold">仅供学习参考。</span>
            禁止上传未授权作品，请尊重原作者版权。所有文件仅在你本地处理，不会上传到第三方服务器。
          </p>
        </div>
      </div>

      {/* 主体：左侧任务列表 + 右侧详情 */}
      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <TaskList
          tasks={tasks}
          loading={loading}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onDelete={handleDelete}
        />

        <TaskDetail
          task={selectedTask}
          job={selectedJob}
          extracting={extracting}
          cancelling={cancelling}
          onStartExtraction={() => setExtractionModalOpen(true)}
          onCancelExtraction={handleCancelExtraction}
          onOpenJob={() => selectedJobId && openJobModal(selectedJobId)}
          onDelete={handleDelete}
        />
      </div>

      {selectedTask && (
        <BookDissectExtractionModal
          open={extractionModalOpen}
          task={selectedTask}
          submitting={extracting}
          onClose={() => setExtractionModalOpen(false)}
          onStart={handleStartExtraction}
        />
      )}
    </div>
  )
}

// ============================================================
// 子组件：任务列表
// ============================================================

interface TaskListProps {
  tasks: BookDissectTask[]
  loading: boolean
  selectedId: string | null
  onSelect: (id: string) => void
  onDelete: (task: BookDissectTask) => void
}

function TaskList({ tasks, loading, selectedId, onSelect, onDelete }: TaskListProps) {
  if (loading && tasks.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-card border border-white/5 bg-card">
        <Loader2 className="h-5 w-5 animate-spin text-content-secondary" />
      </div>
    )
  }

  if (tasks.length === 0) {
    return (
      <div className="flex h-40 flex-col items-center justify-center gap-2 rounded-card border border-dashed border-white/10 bg-card text-sm text-content-secondary">
        <FileText className="h-5 w-5" />
        <p>还没有拆书任务</p>
        <p className="text-xs">点击右上角"上传参考书"开始</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <h2 className="px-1 text-xs font-semibold uppercase tracking-wider text-content-secondary">
        历史任务（{tasks.length}）
      </h2>
      <ul className="space-y-2">
        {tasks.map((t) => {
          const isActive = t.id === selectedId
          return (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => onSelect(t.id)}
                className={`group w-full rounded-card border px-3 py-3 text-left transition-all ${
                  isActive
                    ? 'border-brand/40 bg-brand/10 shadow-[0_8px_24px_-18px_rgba(255,113,72,0.6)]'
                    : 'border-white/5 bg-card hover:border-white/10 hover:bg-white/[0.04]'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-content">
                      {t.file_name ?? '(未命名)'}
                    </p>
                    <p className="mt-0.5 text-xs text-content-secondary">
                      {t.chapter_count} 章 · {formatNumber(t.total_words)} 字
                    </p>
                  </div>
                  <ChevronRight
                    className={`h-4 w-4 shrink-0 transition-colors ${
                      isActive ? 'text-brand' : 'text-content-secondary/40 group-hover:text-content-secondary'
                    }`}
                  />
                </div>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <span
                    className={`inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-[11px] font-medium ${statusBadgeClass(t.status)}`}
                  >
                    {t.status === 'running' && <Loader2 className="h-3 w-3 animate-spin" />}
                    {t.status === 'completed' && <CheckCircle2 className="h-3 w-3" />}
                    {t.status === 'failed' && <AlertTriangle className="h-3 w-3" />}
                    {t.status === 'cancelled' && <StopCircle className="h-3 w-3" />}
                    {statusText(t)}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete(t)
                    }}
                    className="text-content-secondary/60 transition-colors hover:text-rose-400"
                    title="删除"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                {t.status === 'running' && (
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/5">
                    <div
                      className="h-full bg-brand transition-all"
                      style={{ width: `${Math.min(100, Math.max(0, t.progress))}%` }}
                    />
                  </div>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// ============================================================
// 子组件：详情面板
// ============================================================

interface TaskDetailProps {
  task: BookDissectTask | null
  /** 本任务正在运行的后台 AI 任务摘要（实时进度文案；null = 未运行 / 尚未同步到） */
  job: AIJobSummary | null
  extracting: boolean
  cancelling: boolean
  onStartExtraction: () => void
  onCancelExtraction: () => void
  onOpenJob: () => void
  onDelete: (task: BookDissectTask) => void
}

function TaskDetail({
  task,
  job,
  extracting,
  cancelling,
  onStartExtraction,
  onCancelExtraction,
  onOpenJob,
  onDelete,
}: TaskDetailProps) {
  // 注意：所有 hooks 必须在任何 early-return 之前（task 可能为 null）
  const isReadyForImitation = task?.status === 'completed' && task?.stage === 'done'
  const taskId = task?.id

  // CTA 需参考包真实状态：任务完成 ≠ 参考包可用（可能 generating/failed/覆盖率不足被判 failed）
  const [ctaPackStatus, setCtaPackStatus] = useState<string | null>(null)
  useEffect(() => {
    if (!taskId || !isReadyForImitation) {
      setCtaPackStatus(null)
      return
    }
    let cancelled = false
    referencePackApi
      .list()
      .then((packs) => {
        if (cancelled) return
        const pack = (packs ?? []).find((p) => p.task_id === taskId) ?? null
        setCtaPackStatus(pack?.status ?? 'missing')
      })
      .catch(() => {
        if (!cancelled) setCtaPackStatus(null)
      })
    return () => {
      cancelled = true
    }
  }, [isReadyForImitation, taskId])

  if (!task) {
    return (
      <div className="flex h-72 flex-col items-center justify-center gap-3 rounded-card border border-dashed border-white/10 bg-card text-content-secondary">
        <BookOpen className="h-10 w-10" />
        <p className="text-sm">从左侧选择一个任务查看详情，或上传一本新参考书</p>
      </div>
    )
  }

  // 与后端对齐：仅 running 期间禁用；已完成任务允许重新抽取（幂等覆盖旧数据）
  const canStart = task.status !== 'running'
  const packUsable = ctaPackStatus === 'ready' || ctaPackStatus === 'partial'

  return (
    <div className="space-y-4 rounded-card border border-white/5 bg-card p-5">
      <DetailHeader
        task={task}
        job={job}
        canStart={canStart}
        extracting={extracting}
        cancelling={cancelling}
        onStartExtraction={onStartExtraction}
        onCancelExtraction={onCancelExtraction}
        onOpenJob={onOpenJob}
        onDelete={() => onDelete(task)}
      />

      {/* V3 R6 迁移提示 + V3.2-A 跳转创建项目 CTA（仅参考包就绪时展示，failed 不诱导挂载） */}
      {isReadyForImitation && packUsable && (
        <div className="flex flex-col gap-3 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100 sm:flex-row sm:items-start">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
          <div className="min-w-0 flex-1 space-y-1">
            <p className="font-medium">
              抽取完成 · 可使用本书作为参考创建项目、或去项目中一键仿写
              {ctaPackStatus === 'partial' && (
                <span className="ml-2 rounded-pill border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                  部分维度未生成
                </span>
              )}
            </p>
            <p className="text-xs text-emerald-200/80">
              拆书产物已赋能为参考包（ReferencePack）。下面“创建新项目”会跳转项目创建向导，预选本书参考包，
              项目创建后会自动挂载该参考包；也可去《参考库》手动挂载到其他已有项目。
            </p>
          </div>
          {/* V3.2-A：跳转创建项目 + 预选本书，过 wizard 参数 ?wizard=1&pack_task_id=xxx */}
          <Link
            to={`/projects?wizard=1&pack_task_id=${task.id}`}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-btn bg-emerald-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-emerald-600"
          >
            <Wand2 className="h-3.5 w-3.5" />
            以本书作参考创建项目
          </Link>
        </div>
      )}
      {isReadyForImitation && ctaPackStatus === 'failed' && (
        <div className="flex items-start gap-2 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p className="min-w-0 text-xs leading-6">
            抽取流程已结束，但参考包生成失败（核心维度缺失或章节抽取覆盖率过低），
            <strong>暂不可用于挂载/仿写</strong>。可点击右上角「重新抽取」重跑本书。
          </p>
        </div>
      )}

      {task.error_message && task.status === 'cancelled' && (
        <div className="flex items-start gap-2 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <StopCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0">
            <p className="font-medium">已手动停止</p>
            <p className="mt-0.5 break-all text-xs text-amber-300/80">{task.error_message}</p>
          </div>
        </div>
      )}
      {task.error_message && task.status !== 'cancelled' && (
        <div className="flex items-start gap-2 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0">
            <p className="font-medium">抽取失败</p>
            <p className="mt-0.5 break-all text-xs text-rose-300/80">{task.error_message}</p>
          </div>
        </div>
      )}

      <FileInfoCard task={task} />

      {task.status !== 'pending' && (
        <BookDissectV2View
          taskId={task.id}
          status={task.status}
          progress={task.progress ?? 0}
          extractionPhase={task.extraction_phase ?? task.stage ?? null}
          chaptersTotal={task.chapters_total ?? 0}
          chaptersExtracted={task.chapters_extracted ?? 0}
          chaptersFailed={task.chapters_failed ?? 0}
        />
      )}
    </div>
  )
}

// ============================================================
// 子组件：详情头部（标题 + 操作按钮）
// ============================================================

interface DetailHeaderProps {
  task: BookDissectTask
  job: AIJobSummary | null
  canStart: boolean
  extracting: boolean
  cancelling: boolean
  onStartExtraction: () => void
  onCancelExtraction: () => void
  onOpenJob: () => void
  onDelete: () => void
}

function DetailHeader({
  task,
  job,
  canStart,
  extracting,
  cancelling,
  onStartExtraction,
  onCancelExtraction,
  onOpenJob,
  onDelete,
}: DetailHeaderProps) {
  const isRunning = task.status === 'running'
  // 后台任务的实时进度（SSE）比 3 秒一次的轮询更细；拿不到时退回 DB 进度
  const progress = job?.progress?.pct ?? task.progress
  const progressMessage = job?.progress?.message
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1 space-y-1">
        <h2 className="truncate text-lg font-semibold text-content">
          {task.file_name ?? '(未命名)'}
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={`inline-flex items-center gap-1 rounded-pill px-2 py-0.5 font-medium ${statusBadgeClass(task.status)}`}>
            {task.status === 'running' && <Loader2 className="h-3 w-3 animate-spin" />}
            {task.status === 'completed' && <CheckCircle2 className="h-3 w-3" />}
            {task.status === 'failed' && <AlertTriangle className="h-3 w-3" />}
            {task.status === 'cancelled' && <StopCircle className="h-3 w-3" />}
            {statusText(task)}
          </span>
          {isRunning && (
            <span className="text-content-secondary">{progress}%</span>
          )}
        </div>
        {isRunning && (
          <div className="mt-1 h-1.5 w-full max-w-md overflow-hidden rounded-full bg-white/5">
            <div
              className="h-full bg-brand transition-all"
              style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
            />
          </div>
        )}
        {isRunning && job && (
          <p className="max-w-md truncate text-xs text-content-secondary" title={progressMessage}>
            {progressMessage || '正在准备…'}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {isRunning && job && (
          <button
            type="button"
            onClick={onOpenJob}
            className="inline-flex items-center gap-1.5 rounded-btn border border-brand/40 bg-brand/10 px-3 py-1.5 text-xs font-medium text-brand transition-colors hover:bg-brand/20"
          >
            <Activity className="h-3.5 w-3.5" />
            查看任务
          </button>
        )}
        {isRunning ? (
          <button
            type="button"
            onClick={onCancelExtraction}
            disabled={cancelling}
            className="inline-flex items-center gap-1.5 rounded-btn border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-300 transition-colors hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {cancelling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <StopCircle className="h-3.5 w-3.5" />}
            {cancelling ? '停止中…' : '停止抽取'}
          </button>
        ) : (
          <button
            type="button"
            onClick={onStartExtraction}
            disabled={!canStart || extracting}
            className="inline-flex items-center gap-1.5 rounded-btn bg-brand px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {extracting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {task.stage === 'done' || task.status === 'cancelled' ? '重新抽取' : '启动抽取'}
          </button>
        )}
        <button
          type="button"
          onClick={onDelete}
          className="inline-flex items-center gap-1.5 rounded-btn border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:border-rose-500/40 hover:bg-rose-500/10 hover:text-rose-300"
        >
          <Trash2 className="h-3.5 w-3.5" />
          删除
        </button>
      </div>
    </div>
  )
}

// ============================================================
// 子组件：文件信息卡片
// ============================================================

function FileInfoCard({ task }: { task: BookDissectTask }) {
  const items: Array<[string, string]> = [
    ['编码', task.encoding ?? '—'],
    ['大小', formatBytes(task.file_size)],
    ['章节数', `${task.chapter_count}`],
    ['总字数', formatNumber(task.total_words)],
    ['创建时间', formatDate(task.created_at)],
    ['完成时间', formatDate(task.completed_at)],
  ]
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-2xl border border-white/5 bg-white/[0.02] p-4 sm:grid-cols-3">
      {items.map(([k, v]) => (
        <div key={k}>
          <p className="text-[11px] font-medium uppercase tracking-wider text-content-secondary/70">
            {k}
          </p>
          <p className="mt-0.5 truncate text-sm text-content">{v}</p>
        </div>
      ))}
    </div>
  )
}

// V1 抽取结果卡片（项目骨架 / 世界观 / 主要角色 / 章纲 / 文风）与章节预览
// 已随 V1 逻辑一并移除；V2 视图自带概览 / 章节 / 实体 / 关系 / 事件等 tab。
