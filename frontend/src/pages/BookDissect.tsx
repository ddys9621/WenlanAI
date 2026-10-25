import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  FileText,
  Loader2,
  Play,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  StopCircle,
  Trash2,
  Upload,
  Wand2,
} from 'lucide-react'
import { toast } from 'sonner'
import { bookDissectApi } from '@/services/api'
import { useAIJobsStore, useRunningAIJobs } from '@/store/aiJobsStore'
import type { AIJobSummary } from '@/types/ai_job'
import type { BookDissectExtractionOptions, BookDissectRunMode, BookDissectTask } from '@/types'
import type { ReferencePackDetail } from '@/types/reference_pack'
import { BookDissectExtractionModal } from '@/components/BookDissectExtractionModal'
import { BookDissectV5View } from '@/components/book-dissect/BookDissectV5View'
import { ChapterCheckPanel } from '@/components/book-dissect/ChapterCheckPanel'
import { TaskProgressPanel } from '@/components/book-dissect/TaskProgressPanel'
import { hasCards, primaryAction, taskBadge, type TaskTone } from '@/components/book-dissect/taskState'

const ACCEPT_TYPES = '.txt,.md,.markdown'
const MAX_BYTES = 10 * 1024 * 1024
const POLL_INTERVAL_MS = 3000
/** 后端 ai_jobs 里拆书抽取任务的 kind（meta.task_id 对应拆书任务 id） */
const DISSECT_JOB_KINDS = ['book_dissect']

const TONE_CLASS: Record<TaskTone, string> = {
  running: 'bg-brand-50 text-brand-700 ring-brand-200',
  success: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  partial: 'bg-amber-50 text-amber-700 ring-amber-200',
  warning: 'bg-amber-50 text-amber-700 ring-amber-200',
  danger: 'bg-rose-50 text-rose-700 ring-rose-200',
  idle: 'bg-surface-muted text-content-secondary ring-surface-border',
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
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function StatusBadge({ task, className = '' }: { task: BookDissectTask; className?: string }) {
  const badge = taskBadge(task)
  return (
    <span className={`inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-[11px] font-medium ring-1 ${TONE_CLASS[badge.tone]} ${className}`}>
      {badge.tone === 'running' && <Loader2 className="h-3 w-3 animate-spin" />}
      {badge.tone === 'success' && <CheckCircle2 className="h-3 w-3" />}
      {(badge.tone === 'danger' || badge.tone === 'partial') && <AlertTriangle className="h-3 w-3" />}
      {badge.tone === 'warning' && <StopCircle className="h-3 w-3" />}
      {badge.label}
    </span>
  )
}

export default function BookDissect() {
  const [tasks, setTasks] = useState<BookDissectTask[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [modalMode, setModalMode] = useState<BookDissectRunMode | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // 抽取跑在通用 AI 后台任务里：启动后接入弹窗 / 托盘；刷新后由 AIJobHost.syncFromServer 找回运行中的任务
  const attachJob = useAIJobsStore((s) => s.attach)
  const openJobModal = useAIJobsStore((s) => s.openModal)
  const runningDissectJobs = useRunningAIJobs(null, DISSECT_JOB_KINDS)

  // ============================================================
  // 数据加载：列表不带章节元信息，很轻，有任务在跑时整表轮询（左侧其它任务的进度也跟着动）
  // ============================================================

  const refreshList = useCallback(async () => {
    try {
      const list = await bookDissectApi.listTasks()
      setTasks(list)
      setSelectedId((prev) => (prev && list.some((t) => t.id === prev) ? prev : list[0]?.id ?? null))
    } catch {
      /* api 拦截器已 toast */
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    void refreshList().finally(() => setLoading(false))
  }, [refreshList])

  const anyRunning = tasks.some((t) => t.status === 'running')
  useEffect(() => {
    if (!anyRunning) return
    const id = window.setInterval(() => void refreshList(), POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [anyRunning, refreshList])

  const selectedTask = useMemo(() => tasks.find((t) => t.id === selectedId) ?? null, [tasks, selectedId])
  const selectedTaskId = selectedTask?.id
  // 当前任务对应的后台 AI 任务（弹窗最小化后从这里「查看任务」重新打开）
  const selectedJob = useMemo(
    () => runningDissectJobs.find((j) => j.meta?.task_id === selectedTaskId) ?? null,
    [runningDissectJobs, selectedTaskId],
  )
  const selectedJobId = selectedJob?.id ?? null

  // 后台任务到终态（完成 / 失败 / 停止）立刻刷新，不等下一次轮询
  useEffect(() => {
    if (!selectedJobId) return
    return useAIJobsStore.getState().onSettled(selectedJobId, () => void refreshList())
  }, [selectedJobId, refreshList])

  // ============================================================
  // 上传（按钮 / 拖进来）
  // ============================================================

  const uploadFile = async (file: File) => {
    if (!/\.(txt|md|markdown)$/i.test(file.name)) {
      toast.error('只支持 txt / md 文件')
      return
    }
    if (file.size > MAX_BYTES) {
      toast.error(`文件过大（${formatBytes(file.size)}），上限 10 MB`)
      return
    }
    try {
      setUploading(true)
      const resp = await bookDissectApi.upload(file)
      toast.success(`上传完成：切出 ${resp.chapter_count} 章（编码 ${resp.encoding}），先看看切得对不对`)
      setSelectedId(resp.task_id)
      await refreshList()
    } catch {
      /* api 拦截器已 toast */
    } finally {
      setUploading(false)
    }
  }

  const handleFileChosen = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // 允许重复选择同一文件
    if (file) void uploadFile(file)
  }

  // ============================================================
  // 抽取 / 停止 / 删除
  // ============================================================

  const handleStartExtraction = async (options: BookDissectExtractionOptions) => {
    if (!selectedTask) return
    try {
      setExtracting(true)
      const t = await bookDissectApi.startExtraction(selectedTask.id, options)
      setTasks((prev) => prev.map((x) => (x.id === t.id ? t : x)))
      setModalMode(null)
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
      toast.success('已开始抽取')
    } catch {
      /* api 拦截器已 toast */
    } finally {
      setExtracting(false)
    }
  }

  const handleCancelExtraction = async () => {
    if (!selectedTask || selectedTask.status !== 'running') return
    const done = selectedTask.chapters_extracted ?? 0
    const hint = done > 0 ? `已抽出的 ${done} 章拆书卡会保留，` : ''
    if (!confirm(`停止「${selectedTask.file_name ?? selectedTask.id}」的抽取？${hint}之后点「继续抽取」接着跑。`)) return
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
    if (!confirm(`删除「${task.file_name ?? task.id}」${runningHint}？拆书卡、拆书结果和知识库里的这本书会一起删掉。`)) return
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
    <div className="space-y-5">
      <header className="lj-page-header">
        <div>
          <h1 className="lj-page-title">拆书参考</h1>
          <p className="lj-page-desc">
            上传一本 txt / md 小说，拆成逐章拆书卡、剧情单元、全书骨架和文风，收进知识库，写自己的书时拿它做对标。
          </p>
        </div>
        <div className="lj-page-actions">
          <button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploading} className="hh-btn-primary hh-btn-sm">
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {uploading ? '上传中…' : '上传参考书'}
          </button>
          <input ref={fileInputRef} type="file" accept={ACCEPT_TYPES} onChange={handleFileChosen} className="hidden" />
        </div>
      </header>

      <div className="flex items-start gap-2 rounded border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs leading-5 text-amber-800">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          <span className="font-semibold">仅供学习参考，请勿上传未授权的作品。</span>
          上传的全文保存在本应用的数据目录里，删除任务时一并删除；拆书时章节正文会发送给你在「设置」里配置的 AI 接口。
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <TaskList
          tasks={tasks}
          loading={loading}
          uploading={uploading}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onDropFile={(file) => void uploadFile(file)}
        />
        <TaskDetail
          task={selectedTask}
          job={selectedJob}
          extracting={extracting}
          cancelling={cancelling}
          onOpenExtraction={setModalMode}
          onCancelExtraction={handleCancelExtraction}
          onOpenJob={() => selectedJobId && openJobModal(selectedJobId)}
          onDelete={handleDelete}
        />
      </div>

      {selectedTask && (
        <BookDissectExtractionModal
          open={modalMode != null}
          task={selectedTask}
          initialMode={modalMode ?? 'full'}
          submitting={extracting}
          onClose={() => setModalMode(null)}
          onStart={handleStartExtraction}
        />
      )}
    </div>
  )
}

// ============================================================
// 子组件：任务列表（空的时候是拖放区）
// ============================================================

interface TaskListProps {
  tasks: BookDissectTask[]
  loading: boolean
  uploading: boolean
  selectedId: string | null
  onSelect: (id: string) => void
  onDropFile: (file: File) => void
}

function TaskList({ tasks, loading, uploading, selectedId, onSelect, onDropFile }: TaskListProps) {
  const [dragging, setDragging] = useState(false)

  if (loading && tasks.length === 0) {
    return (
      <div className="hh-panel flex h-40 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-content-secondary" />
      </div>
    )
  }

  if (tasks.length === 0) {
    return (
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          const file = e.dataTransfer.files?.[0]
          if (file) onDropFile(file)
        }}
        className={`flex h-48 flex-col items-center justify-center gap-2 rounded border border-dashed px-4 text-center text-sm transition-colors ${
          dragging ? 'border-brand bg-brand-50 text-brand-700' : 'border-surface-border bg-surface-paper text-content-secondary'
        }`}
      >
        {uploading ? <Loader2 className="h-5 w-5 animate-spin" /> : <FileText className="h-5 w-5" />}
        <p>还没有拆书任务</p>
        <p className="text-xs text-content-tertiary">把一本 txt / md 拖到这里，或点右上角「上传参考书」</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <h2 className="px-1 text-xs font-medium text-content-tertiary">历史任务（{tasks.length}）</h2>
      <ul className="space-y-2">
        {tasks.map((t) => {
          const active = t.id === selectedId
          const running = t.status === 'running'
          const failed = t.chapters_failed ?? 0
          return (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => onSelect(t.id)}
                className={`w-full rounded border px-3 py-2.5 text-left transition-colors ${
                  active ? 'border-brand bg-brand-50 shadow-xs' : 'border-surface-border bg-white hover:border-brand/40'
                }`}
              >
                <p className="truncate text-sm font-medium text-content" title={t.file_name ?? undefined}>
                  {t.file_name ?? '(未命名)'}
                </p>
                <p className="mt-0.5 text-xs text-content-tertiary">
                  {formatNumber(t.chapter_count)} 章 · {formatNumber(t.total_words)} 字
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <StatusBadge task={t} />
                  {(t.chapters_total ?? 0) > 0 && (
                    <span className="text-[11px] tabular-nums text-content-tertiary">
                      {t.chapters_extracted ?? 0}/{t.chapters_total}
                    </span>
                  )}
                  {failed > 0 && !running && <span className="text-[11px] text-rose-700">{failed} 章失败</span>}
                </div>
                {running && (
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface-muted">
                    <div className="h-full bg-brand transition-all" style={{ width: `${Math.min(100, Math.max(0, t.progress))}%` }} />
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
// 子组件：详情
// ============================================================

interface TaskDetailProps {
  task: BookDissectTask | null
  /** 本任务正在运行的后台 AI 任务摘要（实时进度文案；null = 未运行 / 尚未同步到） */
  job: AIJobSummary | null
  extracting: boolean
  cancelling: boolean
  onOpenExtraction: (mode: BookDissectRunMode) => void
  onCancelExtraction: () => void
  onOpenJob: () => void
  onDelete: (task: BookDissectTask) => void
}

function TaskDetail({ task, job, extracting, cancelling, onOpenExtraction, onCancelExtraction, onOpenJob, onDelete }: TaskDetailProps) {
  // 注意：所有 hooks 必须在任何 early-return 之前（task 可能为 null）
  const taskId = task?.id
  const taskStatus = task?.status
  const packStatus = task?.pack_status
  const [focusFailedNonce, setFocusFailedNonce] = useState(0)

  // 拆书结果：维度 tab 直接读它；任务状态 / 结果状态变化（跑完、重建完）时重新拉，抽取中每次轮询不重复请求
  const [pack, setPack] = useState<ReferencePackDetail | null>(null)
  const [packLoading, setPackLoading] = useState(false)
  useEffect(() => {
    setPack(null)
    if (!taskId || taskStatus === 'pending') return
    let cancelled = false
    setPackLoading(true)
    bookDissectApi
      .getResult(taskId)
      .then((detail) => {
        if (!cancelled) setPack(detail ?? null)
      })
      .catch(() => {
        /* api 拦截器已 toast */
      })
      .finally(() => {
        if (!cancelled) setPackLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [taskId, taskStatus, packStatus])

  if (!task) {
    return (
      <div className="hh-panel flex h-72 flex-col items-center justify-center gap-3 text-content-secondary">
        <BookOpen className="h-10 w-10 text-content-tertiary" />
        <p className="text-sm">从左侧选一个任务，或上传一本新参考书</p>
      </div>
    )
  }

  const running = task.status === 'running'
  const extractedBefore = hasCards(task)
  const refreshKey = `${task.status}:${task.extraction_phase ?? task.stage}:${task.chapters_extracted ?? 0}:${task.chapters_failed ?? 0}`
  const showFailed = () => setFocusFailedNonce((n) => n + 1)
  const retryFailed = running ? undefined : () => onOpenExtraction('resume')

  return (
    <div className="space-y-4">
      <DetailHeader
        task={task}
        job={job}
        extracting={extracting}
        cancelling={cancelling}
        onOpenExtraction={onOpenExtraction}
        onCancelExtraction={onCancelExtraction}
        onOpenJob={onOpenJob}
        onDelete={() => onDelete(task)}
      />

      <TaskNotice task={task} onShowFailed={showFailed} />

      {(running || extractedBefore) && (
        <TaskProgressPanel task={task} job={job} showKnowledgeLink={pack != null && task.pack_status !== 'failed'} onShowFailed={showFailed} />
      )}

      <ChapterCheckPanel
        key={`chapters-${task.id}`}
        taskId={task.id}
        refreshKey={refreshKey}
        defaultOpen={!extractedBefore && !running}
        onStart={!extractedBefore && !running ? () => onOpenExtraction('full') : undefined}
      />

      {(running || extractedBefore) && (
        <BookDissectV5View
          key={`v5-${task.id}`}
          taskId={task.id}
          pack={pack}
          packLoading={packLoading}
          initialTab={task.status === 'completed' ? 'skeleton' : 'cards'}
          refreshKey={refreshKey}
          focusFailedNonce={focusFailedNonce}
          onRetryFailed={retryFailed}
        />
      )}
    </div>
  )
}

// ============================================================
// 子组件：详情头部（标题 + 状态 + 主操作）
// ============================================================

interface DetailHeaderProps {
  task: BookDissectTask
  job: AIJobSummary | null
  extracting: boolean
  cancelling: boolean
  onOpenExtraction: (mode: BookDissectRunMode) => void
  onCancelExtraction: () => void
  onOpenJob: () => void
  onDelete: () => void
}

function DetailHeader({ task, job, extracting, cancelling, onOpenExtraction, onCancelExtraction, onOpenJob, onDelete }: DetailHeaderProps) {
  const running = task.status === 'running'
  const action = primaryAction(task)
  const ended = !running && hasCards(task) && task.completed_at
  const meta = [
    `${formatNumber(task.chapter_count)} 章`,
    `${formatNumber(task.total_words)} 字`,
    formatBytes(task.file_size),
    task.encoding ? task.encoding.replace(/-sig$/i, '').toUpperCase() : undefined,
    `上传于 ${formatDate(task.created_at)}`,
    ended ? `结束于 ${formatDate(task.completed_at)}` : undefined,
  ].filter(Boolean)

  return (
    <div className="hh-panel flex flex-wrap items-start justify-between gap-3 px-4 py-3">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="truncate text-lg font-semibold text-content">{task.file_name ?? '(未命名)'}</h2>
          <StatusBadge task={task} />
        </div>
        <p className="text-xs text-content-tertiary">{meta.join(' · ')}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {running && job && (
          <button type="button" onClick={onOpenJob} className="hh-btn-secondary hh-btn-sm">
            <Activity className="h-3.5 w-3.5" />
            查看任务
          </button>
        )}
        {running && (
          <button type="button" onClick={onCancelExtraction} disabled={cancelling} className="hh-btn-secondary hh-btn-sm !text-amber-700">
            {cancelling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <StopCircle className="h-3.5 w-3.5" />}
            {cancelling ? '停止中…' : '停止抽取'}
          </button>
        )}
        {action && (
          <button type="button" onClick={() => onOpenExtraction(action.mode)} disabled={extracting} className="hh-btn-primary hh-btn-sm">
            {extracting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : action.mode === 'full' ? (
              <Play className="h-3.5 w-3.5" />
            ) : (
              <RotateCcw className="h-3.5 w-3.5" />
            )}
            {action.label}
          </button>
        )}
        <button type="button" onClick={onDelete} className="hh-btn-ghost hh-btn-sm hover:!text-rose-700" title="删除任务">
          <Trash2 className="h-3.5 w-3.5" />
          删除
        </button>
      </div>
    </div>
  )
}

// ============================================================
// 子组件：状态说明（中断 / 失败 / 停止 / 部分完成 / 完成）；要做的操作就是头部的主按钮，这里不重复放
// ============================================================

function TaskNotice({ task, onShowFailed }: { task: BookDissectTask; onShowFailed: () => void }) {
  const ok = task.chapters_extracted ?? 0
  const failed = task.chapters_failed ?? 0
  const kept = ok > 0 ? `已抽出的 ${ok} 章拆书卡都保留着，` : ''

  if (task.status === 'interrupted') {
    return (
      <Notice tone="warning" icon={StopCircle} title="抽取中断了">
        服务重启或程序退出时还没抽完。{kept}点右上角「继续抽取」只补没抽完的章，不会重抽已完成的。
      </Notice>
    )
  }
  if (task.status === 'cancelled') {
    return (
      <Notice tone="warning" icon={StopCircle} title="已手动停止">
        {kept}点右上角「继续抽取」接着跑。
      </Notice>
    )
  }
  if (task.status === 'failed') {
    return (
      <Notice tone="danger" icon={AlertTriangle} title="抽取失败">
        <span className="break-all">{task.error_message || '未知原因'}</span>
      </Notice>
    )
  }
  if (task.status !== 'completed' || task.stage !== 'done') return null

  if (task.pack_status === 'failed') {
    return (
      <Notice tone="danger" icon={AlertTriangle} title="拆书结果不可用，暂不能做对标书">
        {task.pack_error || '核心维度缺失或章节抽取覆盖率过低'}
      </Notice>
    )
  }
  if (failed > 0 || task.pack_status === 'partial') {
    return (
      <Notice tone="warning" icon={AlertTriangle} title="部分完成">
        {failed > 0 && (
          <>
            <button type="button" onClick={onShowFailed} className="font-medium underline-offset-2 hover:underline">
              {failed} 章没抽出来
            </button>
            ，点右上角「重试失败章节」只补抽这些章，再重建剧情单元、骨架和文风，已成功的不会重抽。
          </>
        )}
        {task.pack_error && <span className="block">{task.pack_error}</span>}
      </Notice>
    )
  }
  return (
    <Notice
      tone="success"
      icon={Sparkles}
      title="抽取完成 · 已收进知识库，可以拿它做对标书"
      action={
        <Link to={`/projects?wizard=1&dissect_task_id=${task.id}`} className="hh-btn-primary hh-btn-sm shrink-0">
          <Wand2 className="h-3.5 w-3.5" />
          以本书做对标创建项目
        </Link>
      }
    >
      拆书结果写成了知识库条目（导读、分卷、剧情单元、章卡、人物、写法、文风，每条都有去掉人名的版本）；已有项目可以在「仿写参考」页选它。
    </Notice>
  )
}

const NOTICE_TONE: Record<'warning' | 'danger' | 'success', string> = {
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
  danger: 'border-rose-200 bg-rose-50 text-rose-800',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
}

function Notice({
  tone,
  icon: Icon,
  title,
  action,
  children,
}: {
  tone: 'warning' | 'danger' | 'success'
  icon: React.ComponentType<{ className?: string }>
  title: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className={`flex flex-col gap-3 rounded border px-4 py-3 text-sm sm:flex-row sm:items-start ${NOTICE_TONE[tone]}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="font-medium">{title}</p>
        <div className="text-xs leading-5 opacity-90">{children}</div>
      </div>
      {action}
    </div>
  )
}
