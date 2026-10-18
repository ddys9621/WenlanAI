import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Plus, Pencil, Trash2, FileText, Loader2, Sparkles, Layers, BookOpen, Check, Eye } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { useOutlineSync } from '@/store/hooks'
import { useVolumeSync, useChapterOutlineSync } from '@/store/plotHooks'
import { useAssistantDataChange } from '@/hooks/useAssistantPage'
import type { AssistantDataChange } from '@/store/assistantStore'
import { useAIJobsStore, useRunningAIJobs } from '@/store/aiJobsStore'
import { outlineApi, chapterOutlineApi } from '@/services/api'
import { OUTLINE_BUSY_KINDS, OUTLINE_JOB_KIND, outlineGenerationDefaults, outlineGenerationPayload } from '@/utils/outlineGeneration'
import { VolumesView } from '@/components/outline/VolumesView'
import { MCPSelector } from '@/components/MCPSelector'
import { KbCitationChips } from '@/components/knowledge/KbCitationChips'
import { KbReferenceHint } from '@/components/knowledge/KbReferenceHint'
import { useKbCitations } from '@/hooks/useKbCitations'
import { useProjectKbLink } from '@/hooks/useProjectKbLink'
import { Modal as UiModal, type ModalSize } from '@/components/ui/Modal'
import type {
  Outline, OutlineCreate, OutlineUpdate, Volume, Project, StoryOutlineGenerateResult,
  ChapterOutline, ChapterOutlineCreate, ChapterOutlineUpdate,
  ChapterOutlineBatchCreateRequest, NarrativeTasks,
} from '@/types'

type TabKey = 'outlines' | 'volumes' | 'chapterOutlines'

/** 谋篇：总纲 → 卷纲（剧情单元 + 线索编排）→ 章纲 */
const TABS: { key: TabKey; label: string; icon: React.ElementType; path: string }[] = [
  { key: 'outlines', label: '总纲', icon: FileText, path: '' },
  { key: 'volumes', label: '卷纲', icon: Layers, path: 'volumes' },
  { key: 'chapterOutlines', label: '章纲', icon: BookOpen, path: 'chapters' },
]

const tabFromPath = (path?: string): TabKey => TABS.find((t) => t.path && path?.startsWith(t.path))?.key ?? 'outlines'

const STATUS_TAG = 'px-2 py-0.5 text-[11px] font-medium'

export default function OutlinePage() {
  const { currentProject, outlines } = useStore()
  const projectId = currentProject?.id
  const subPath = useParams()['*']
  const [activeTab, setActiveTab] = useState<TabKey>(() => tabFromPath(subPath))
  useEffect(() => { setActiveTab(tabFromPath(subPath)) }, [subPath])
  const [loading, setLoading] = useState(false)

  // hooks
  const { refreshOutlines, createOutline, updateOutline, deleteOutline, activateOutline } = useOutlineSync()
  const { volumes, refreshVolumes, saveVolume, confirmVolume, deleteVolume } = useVolumeSync()
  const { chapterOutlines, refreshChapterOutlines, createChapterOutline, updateChapterOutline: updateChapterOutlineData, deleteChapterOutline, batchCreateChapterOutlines } = useChapterOutlineSync()

  // 初始化加载
  useEffect(() => {
    if (!projectId) return
    setLoading(true)
    Promise.all([
      refreshOutlines(),
      refreshVolumes(projectId),
      refreshChapterOutlines(projectId),
    ]).finally(() => setLoading(false))
  }, [projectId, refreshChapterOutlines, refreshOutlines, refreshVolumes])

  // 全局智能助笔改了章纲 / 总纲（改总纲会把卷纲和章纲标成「上游已改」）或规划了卷纲：刷新
  const onAssistantData = useCallback((change: AssistantDataChange) => {
    if (!projectId) return
    if (change.entity === 'chapter_outline' || change.entity === 'story_outline' || change.entity === 'volume') {
      void refreshChapterOutlines(projectId)
      void refreshVolumes(projectId)
    }
  }, [projectId, refreshChapterOutlines, refreshVolumes])
  useAssistantDataChange(onAssistantData)

  // ==================== Tab 容器 ====================
  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">谋篇</h1>
          <p className="mt-2 max-w-[600px] text-sm leading-6 text-content-secondary">
            总纲定全书主线，卷纲把每卷拆成几件完整的事，章纲把每件事落到章；AI 草拟的都要你确认后才写正文。
            当前 {outlines.length} 个总纲版本、{volumes.length} 卷卷纲、{chapterOutlines.length} 份章纲。
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap self-start border border-surface-border bg-white/60 p-1 md:self-auto">
          {TABS.map(tab => {
            const selected = activeTab === tab.key
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={cn(
                  'inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium transition-colors',
                  selected ? 'bg-brand text-white' : 'text-content-secondary hover:text-content'
                )}
              >
                <tab.icon className="h-3.5 w-3.5" />
                {tab.label}
              </button>
            )
          })}
        </div>
      </section>

      {loading ? (
        <div className="hh-panel flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-brand" />
        </div>
      ) : (
        <>
          {activeTab === 'outlines' && (
            <OutlinesView
              outlines={outlines}
              projectId={projectId}
              project={currentProject}
              createOutline={createOutline}
              updateOutline={updateOutline}
              deleteOutline={deleteOutline}
              activateOutline={activateOutline}
              refreshOutlines={refreshOutlines}
              onPlanChanged={() => {
                if (!projectId) return
                void refreshVolumes(projectId)
                void refreshChapterOutlines(projectId)
              }}
            />
          )}
          {activeTab === 'volumes' && (
            <VolumesView
              projectId={projectId}
              chapterCount={currentProject?.chapter_count}
              volumes={volumes}
              chapterOutlines={chapterOutlines}
              refreshVolumes={refreshVolumes}
              refreshChapterOutlines={() => (projectId ? refreshChapterOutlines(projectId) : Promise.resolve())}
              saveVolume={saveVolume}
              confirmVolume={confirmVolume}
              deleteVolume={deleteVolume}
              onOpenChapterOutlines={() => setActiveTab('chapterOutlines')}
            />
          )}
          {activeTab === 'chapterOutlines' && <ChapterOutlinesView chapterOutlines={chapterOutlines} volumes={volumes} projectId={projectId} createChapterOutline={createChapterOutline} updateChapterOutline={updateChapterOutlineData} deleteChapterOutline={deleteChapterOutline} batchCreateChapterOutlines={batchCreateChapterOutlines} onOpenVolumes={() => setActiveTab('volumes')} onRefresh={() => (projectId ? refreshChapterOutlines(projectId) : Promise.resolve())} />}
        </>
      )}
    </div>
  )
}

// ==================== 通用弹窗壳（薄壳，转发到全局 Modal） ====================
function Modal({ title, onClose, children, size = 'xl', footer, closeOnMaskClick }: {
  title: string
  onClose: () => void
  children: React.ReactNode
  size?: ModalSize
  footer?: React.ReactNode
  closeOnMaskClick?: boolean
}) {
  return (
    <UiModal title={title} onClose={onClose} size={size} footer={footer} closeOnMaskClick={closeOnMaskClick}>
      {children}
    </UiModal>
  )
}

// ==================== 通用空状态（面板内） ====================
function EmptyBlock({ icon: Icon, title, hint }: { icon: React.ElementType; title: string; hint: string }) {
  return (
    <div className="mt-6 flex flex-col items-center px-6 py-12 text-center">
      <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
        <Icon className="h-7 w-7" />
      </span>
      <h3 className="mt-5 text-xl font-semibold tracking-tight text-content">{title}</h3>
      <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">{hint}</p>
    </div>
  )
}

// ==================== Tab 1: 故事大纲 ====================
export function OutlinesView({ outlines, projectId, project, createOutline, updateOutline, deleteOutline, activateOutline, refreshOutlines, onPlanChanged }: {
  outlines: Outline[]
  projectId?: string
  /** 生成表单的视角 / 章数 / 字数默认取项目设置 */
  project?: Project | null
  createOutline: (data: OutlineCreate) => Promise<Outline>
  updateOutline: (id: string, data: OutlineUpdate) => Promise<Outline>
  deleteOutline: (id: string) => Promise<void>
  activateOutline: (id: string) => Promise<Outline>
  refreshOutlines: () => Promise<Outline[]>
  /** AI 生成了新总纲：已有卷纲 / 章纲会被标「上游已改」，刷新它们 */
  onPlanChanged: () => void
}) {
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<Outline | null>(null)
  const [form, setForm] = useState({ title: '', premise: '', main_plot: '', golden_finger: '', selling_points: '', power_system: '', main_tropes: '', ultimate_goal: '', opening_hook: '' })
  const startJob = useAIJobsStore((s) => s.start)
  // 本项目在跑总纲生成（含向导正在生成总纲）：按钮禁用态由全局任务 store 派生，刷新 / 切页回来仍正确
  const generating = useRunningAIJobs(projectId, OUTLINE_BUSY_KINDS).length > 0
  const [showGenModal, setShowGenModal] = useState(false)
  const [genForm, setGenForm] = useState(() => outlineGenerationDefaults(project))
  const [genEnableMcp, setGenEnableMcp] = useState(false)
  const [genPlugins, setGenPlugins] = useState<string[]>([])
  const kbLink = useProjectKbLink(projectId)
  const [viewingOutline, setViewingOutline] = useState<Outline | null>(null)
  const openCreate = () => { setEditing(null); setForm({ title: '', premise: '', main_plot: '', golden_finger: '', selling_points: '', power_system: '', main_tropes: '', ultimate_goal: '', opening_hook: '' }); setShowModal(true) }
  const openEdit = (o: Outline) => {
    const f = { title: o.title, premise: o.content, main_plot: '', golden_finger: '', selling_points: '', power_system: '', main_tropes: '', ultimate_goal: '', opening_hook: '' };
    try {
      const parsed = JSON.parse(o.content);
      if (typeof parsed === 'object') {
        f.premise = parsed.premise || '';
        f.main_plot = parsed.main_plot || '';
        f.golden_finger = parsed.golden_finger || '';
        f.selling_points = Array.isArray(parsed.selling_points) ? parsed.selling_points.join('、') : (parsed.selling_points || '');
        f.power_system = parsed.power_system || '';
        f.main_tropes = Array.isArray(parsed.main_tropes) ? parsed.main_tropes.join('、') : (parsed.main_tropes || '');
        f.ultimate_goal = parsed.ultimate_goal || '';
        f.opening_hook = parsed.opening_hook || '';
      }
    } catch { /* keep raw outline content when it is not JSON */ }
    setEditing(o); setForm(f); setShowModal(true);
  }

  /** 打开生成表单：视角 / 章数 / 字数按项目当前设置重填，额外要求保留上次没提交的 */
  const openGenerate = () => {
    setGenForm((f) => ({ ...outlineGenerationDefaults(project), requirements: f.requirements }))
    setShowGenModal(true)
  }

  /** AI 生成总纲：交给通用后台任务（弹窗展示阶段 / 参考 / 生成内容；可最小化、可停止、刷新后可重连） */
  const handleAIGenerate = async () => {
    if (!projectId) return
    setShowGenModal(false)
    const payload = outlineGenerationPayload(genForm, { enable: genEnableMcp, selected: genPlugins })
    try {
      await startJob<StoryOutlineGenerateResult>({
        kind: OUTLINE_JOB_KIND,
        title: 'AI 生成总纲',
        projectId,
        connect: (options) => outlineApi.generateStream(projectId, payload, options),
        onSettled: (job) => {
          if (job.status !== 'done') return
          toast.success((job.result as StoryOutlineGenerateResult | null)?.message || '总纲已生成')
          setGenForm((f) => ({ ...f, requirements: '' }))
          // 任务结束时已切到别的项目就不刷新，免得把这个项目的总纲 / 卷纲写进别的项目的列表
          if (useStore.getState().currentProject?.id !== projectId) return
          void refreshOutlines()
          onPlanChanged()
        },
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'AI 生成总纲失败')
    }
  }

  const handleSubmit = async () => {
    if (!projectId) return
    if (!form.title.trim()) { toast.error('请填写标题'); return }
    let original: Record<string, unknown> = {}
    try {
      const parsed = editing ? JSON.parse(editing.content) : null
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) original = parsed as Record<string, unknown>
    } catch { /* 旧的纯文本总纲：整段当作梗概 */ }
    const contentJson = JSON.stringify({
      ...original,
      premise: form.premise,
      main_plot: form.main_plot,
      golden_finger: form.golden_finger,
      selling_points: form.selling_points.split(/[、,，]/).map(s => s.trim()).filter(Boolean),
      power_system: form.power_system,
      main_tropes: form.main_tropes.split(/[、,，]/).map(s => s.trim()).filter(Boolean),
      ultimate_goal: form.ultimate_goal,
      opening_hook: form.opening_hook,
    });
    try {
      if (editing) {
        await updateOutline(editing.id, { title: form.title, content: contentJson, version: editing.version })
      } else {
        await createOutline({ project_id: projectId, title: form.title, content: contentJson, order_index: outlines.length })
        toast.success('大纲已创建')
      }
      setShowModal(false)
    } catch { /* hook 已 toast */ }
  }

  const handleDelete = async (o: Outline) => {
    if (!confirm(`确定删除「${o.title}」？`)) return
    try { await deleteOutline(o.id); toast.success('大纲已删除') } catch { /* hook 已 toast */ }
  }

  const handleActivate = async (o: Outline) => {
    try { await activateOutline(o.id); toast.success('已设为活跃版本'); refreshOutlines() } catch { /* hook 已 toast */ }
  }

  return (
    <section className="hh-panel p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-tight text-content">大纲版本</h2>
          <p className="mt-1 text-sm leading-6 text-content-secondary">
            整本书的骨架：梗概、全书主线、卖点与终极目标。活跃版本是分卷、细化卷纲和生成章纲的依据，共 {outlines.length} 个版本。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={openGenerate} disabled={generating || !projectId} className="hh-btn-secondary">
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4 text-brand" />}
            AI 生成
          </button>
          <button onClick={openCreate} className="hh-btn-primary">
            <Plus className="h-4 w-4" />
            新建大纲
          </button>
        </div>
      </div>

      {outlines.length === 0 ? (
        <EmptyBlock
          icon={FileText}
          title="还没有故事大纲"
          hint="点击右上角「新建大纲」手动填写，或用「AI 生成」根据项目设定生成一版初稿，再回来细修。"
        />
      ) : (
        <div className="mt-6 space-y-3">
          {outlines.map(o => (
            <article key={o.id} className="hh-subpanel p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center bg-brand/10 text-brand">
                    <FileText className="h-5 w-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="min-w-0 max-w-full truncate text-[15px] font-semibold text-content">{o.title}</h3>
                      {o.is_active && <span className={cn(STATUS_TAG, 'bg-emerald-50 text-emerald-600')}>活跃</span>}
                      {o.version != null && <span className="text-xs text-content-tertiary tabular-nums">v{o.version}</span>}
                    </div>
                    {o.content && <p className="mt-1.5 line-clamp-3 whitespace-pre-wrap text-[13px] leading-6 text-content-secondary">{(() => {
                      try { const parsed = JSON.parse(o.content); return typeof parsed === 'object' ? (parsed.premise || parsed.content || JSON.stringify(parsed, null, 2)) : o.content; } catch { return o.content; }
                    })()}</p>}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {!o.is_active && (
                    <button onClick={() => handleActivate(o)} className="hh-btn-secondary h-8 px-3 text-xs">
                      <Check className="h-3 w-3" />激活
                    </button>
                  )}
                  <button onClick={() => setViewingOutline(o)} className="hh-icon-btn-plain h-8 w-8" title="查看全文"><Eye className="h-3.5 w-3.5" /></button>
                  <button onClick={() => openEdit(o)} className="hh-icon-btn-plain h-8 w-8" title="编辑"><Pencil className="h-3.5 w-3.5" /></button>
                  <button onClick={() => handleDelete(o)} className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="删除"><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {showGenModal && (
        <Modal
          title="AI 生成故事大纲"
          onClose={() => setShowGenModal(false)}
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowGenModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleAIGenerate} disabled={generating} className="hh-btn-primary">
                {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                开始生成
              </button>
            </>
          )}
        >
          <div className="space-y-5">
            <p className="text-sm leading-6 text-content-secondary">
              {outlines.length > 0
                ? `生成的总纲存成新版本并设为活跃，现有 ${outlines.length} 个版本保留在列表里、可随时切回；已有的卷纲 / 章纲会标「上游已改」，提醒你核对。`
                : '生成的总纲设为活跃版本，作为分卷、细化卷纲和章纲的依据。'}
              生成在后台进行，弹窗可以最小化，顶栏「AI 任务」里随时查看或停止。
            </p>
            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <label className="hh-label">叙事视角</label>
                <select value={genForm.narrative_perspective} onChange={e => setGenForm(f => ({ ...f, narrative_perspective: e.target.value }))} className="hh-field">
                  <option value="第一人称">第一人称</option>
                  <option value="第三人称">第三人称</option>
                  <option value="全知视角">全知视角</option>
                </select>
              </div>
              <div>
                <label className="hh-label">章节数</label>
                <input type="number" min={1} value={genForm.chapter_count} onChange={e => setGenForm(f => ({ ...f, chapter_count: Number(e.target.value) }))} className="hh-field" />
              </div>
              <div>
                <label className="hh-label">目标字数</label>
                <input type="number" min={1} value={genForm.target_words} onChange={e => setGenForm(f => ({ ...f, target_words: Number(e.target.value) }))} className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">额外要求（可选）</label>
              <textarea value={genForm.requirements} onChange={e => setGenForm(f => ({ ...f, requirements: e.target.value }))} placeholder="对大纲的特殊要求..." rows={2} className="hh-textarea" />
            </div>
            <MCPSelector value={{ enable: genEnableMcp, selected: genPlugins }} onChange={({ enable, selected }) => { setGenEnableMcp(enable); setGenPlugins(selected) }} />
            {projectId && (
              <KbReferenceHint projectId={projectId} link={kbLink} />
            )}
          </div>
        </Modal>
      )}

      {showModal && (
        <Modal
          title={editing ? '编辑大纲' : '新建大纲'}
          onClose={() => setShowModal(false)}
          size="xl"
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleSubmit} className="hh-btn-primary">确定</button>
            </>
          )}
        >
          <div className="space-y-5">
            <div>
              <label className="hh-label">标题</label>
              <input value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} className="hh-field" />
            </div>
            <div>
              <label className="hh-label">故事梗概</label>
              <textarea value={form.premise} onChange={e => setForm(f => ({ ...f, premise: e.target.value }))} rows={4} placeholder="5-8句话概括整个故事..." className="hh-textarea" />
            </div>
            <div>
              <label className="hh-label">全书主线</label>
              <textarea value={form.main_plot} onChange={e => setForm(f => ({ ...f, main_plot: e.target.value }))} rows={6} placeholder="用自然段把整本书从开始讲到结局：主角在什么处境下做了什么选择、别人怎样回应、结果如何、又引出什么" className="hh-textarea" />
            </div>
            <div>
              <label className="hh-label">主角特殊能力（可选）</label>
              <input value={form.golden_finger} onChange={e => setForm(f => ({ ...f, golden_finger: e.target.value }))} placeholder="系统 / 重生 / 传承……题材不需要就留空或填「无」；它只是设定，不必每段剧情都用" className="hh-field" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="hh-label">核心卖点</label>
                <input value={form.selling_points} onChange={e => setForm(f => ({ ...f, selling_points: e.target.value }))} placeholder="用顿号分隔，如：废材逆袭、打脸" className="hh-field" />
              </div>
              <div>
                <label className="hh-label">主要套路</label>
                <input value={form.main_tropes} onChange={e => setForm(f => ({ ...f, main_tropes: e.target.value }))} placeholder="用顿号分隔，如：宗门大比、夺宝" className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">成长路线</label>
              <input value={form.power_system} onChange={e => setForm(f => ({ ...f, power_system: e.target.value }))} placeholder="用→连接各阶段" className="hh-field" />
            </div>
            <div>
              <label className="hh-label">终极目标</label>
              <input value={form.ultimate_goal} onChange={e => setForm(f => ({ ...f, ultimate_goal: e.target.value }))} placeholder="主角最终会达成什么" className="hh-field" />
            </div>
            <div>
              <label className="hh-label">开篇钩子</label>
              <input value={form.opening_hook} onChange={e => setForm(f => ({ ...f, opening_hook: e.target.value }))} placeholder="第一章如何吸引读者" className="hh-field" />
            </div>
          </div>
        </Modal>
      )}

      {viewingOutline && (() => {
        let parsed: Record<string, unknown> | null = null;
        try { const p = JSON.parse(viewingOutline.content); if (typeof p === 'object' && p !== null) parsed = p as Record<string, unknown>; } catch { /* render raw outline content */ }
        const labels: Array<[string, string]> = [
          ['premise', '故事梗概'],
          ['main_plot', '全书主线'],
          ['golden_finger', '主角特殊能力'],
          ['selling_points', '核心卖点'],
          ['power_system', '成长路线'],
          ['main_tropes', '主要套路'],
          ['ultimate_goal', '终极目标'],
          ['opening_hook', '开篇钩子'],
        ];
        const renderValue = (v: unknown) => {
          if (Array.isArray(v)) return v.join('、');
          if (typeof v === 'string') return v;
          return JSON.stringify(v);
        };
        return (
          <Modal
            title={`查看大纲：${viewingOutline.title}`}
            onClose={() => setViewingOutline(null)}
            size="2xl"
            footer={(
              <button onClick={() => { setViewingOutline(null); openEdit(viewingOutline); }} className="hh-btn-primary">
                <Pencil className="h-3.5 w-3.5" />编辑
              </button>
            )}
          >
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
                {viewingOutline.is_active && <span className={cn(STATUS_TAG, 'bg-emerald-50 text-emerald-600')}>活跃</span>}
                {viewingOutline.version != null && <span>版本 v{viewingOutline.version}</span>}
                <span>创建于 {new Date(viewingOutline.created_at).toLocaleString()}</span>
              </div>
              <div className="space-y-3">
                {parsed ? labels.map(([key, label]) => {
                  const val = parsed![key];
                  if (!val) return null;
                  return (
                    <div key={key} className="hh-subpanel p-4">
                      <p className="text-xs font-medium text-content-tertiary">{label}</p>
                      <p className="mt-1.5 whitespace-pre-wrap text-sm leading-7 text-content">{renderValue(val)}</p>
                    </div>
                  );
                }) : (
                  <div className="hh-subpanel whitespace-pre-wrap p-4 text-sm leading-7 text-content">
                    {viewingOutline.content}
                  </div>
                )}
              </div>
            </div>
          </Modal>
        );
      })()}
    </section>
  )
}
// ==================== Tab 4: 章纲 ====================
const EMPTY_CHAPTER_OUTLINE_FORM = {
  chapter_number: 1, title: '', plot_points: '', scene: '', pov: '', target_word_count: 3000,
  key_events: '', entry_state: '', exit_state: '', forbidden: '',
}

const splitLines = (text: string) => text.split('\n').map((s) => s.trim()).filter(Boolean)

/** 章纲状态徽标：AI 草拟待确认 / 上游已改 / 已确认 */
function OutlineReviewBadge({ co }: { co: ChapterOutline }) {
  if (co.upstream_stale) return <span className="lj-badge lj-badge--stale" title={co.upstream_reason || '卷纲 / 总纲改过'}>上游已改</span>
  if (co.review_status === 'draft') return <span className="lj-badge lj-badge--draft" title="AI 草拟的章纲，确认后再写正文更稳">待确认</span>
  if (co.review_status === 'confirmed') return <span className="lj-badge lj-badge--ok">已确认</span>
  return null
}

function ChapterOutlinesView({ chapterOutlines, volumes, projectId, createChapterOutline, updateChapterOutline, deleteChapterOutline, batchCreateChapterOutlines, onOpenVolumes, onRefresh }: {
  chapterOutlines: ChapterOutline[]
  volumes: Volume[]
  projectId?: string
  createChapterOutline: (data: ChapterOutlineCreate) => Promise<ChapterOutline>
  updateChapterOutline: (id: string, data: ChapterOutlineUpdate) => Promise<ChapterOutline>
  deleteChapterOutline: (id: string) => Promise<void>
  batchCreateChapterOutlines: (data: ChapterOutlineBatchCreateRequest) => Promise<ChapterOutline[]>
  onOpenVolumes: () => void
  onRefresh: () => Promise<unknown>
}) {
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<ChapterOutline | null>(null)
  const [viewingChapterOutline, setViewingChapterOutline] = useState<ChapterOutline | null>(null)
  const [form, setForm] = useState(EMPTY_CHAPTER_OUTLINE_FORM)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [showBatchModal, setShowBatchModal] = useState(false)
  const [batchCount, setBatchCount] = useState(5)
  const [batchCreating, setBatchCreating] = useState(false)

  const sorted = [...chapterOutlines].sort((a, b) => a.chapter_number - b.chapter_number)
  const outlineCitations = useKbCitations(
    projectId, 'chapter_outline', sorted.map((co) => co.id), sorted.map((co) => co.updated_at ?? '').join(','),
  )
  const unitLabel = (co: ChapterOutline) => {
    const volume = volumes.find((v) => v.id === co.volume_id)
    if (!volume) return null
    const unit = volume.units.find((u) => u.index === co.unit_index)
    return `第${volume.volume_number}卷${unit ? ` · 单元 ${unit.index}《${unit.title}》` : ''}`
  }

  const openCreate = () => {
    setEditing(null)
    const nextNum = sorted.length > 0 ? sorted[sorted.length - 1].chapter_number + 1 : 1
    setForm({ ...EMPTY_CHAPTER_OUTLINE_FORM, chapter_number: nextNum })
    setShowModal(true)
  }
  const openEdit = (co: ChapterOutline) => {
    setEditing(co)
    setForm({
      chapter_number: co.chapter_number, title: co.title, plot_points: co.plot_points || '', scene: co.scene || '',
      pov: co.pov || '', target_word_count: co.target_word_count,
      key_events: (co.key_events || []).join('\n'), entry_state: co.entry_state || '', exit_state: co.exit_state || '',
      forbidden: (co.forbidden || []).join('\n'),
    })
    setShowModal(true)
  }

  const handleSubmit = async () => {
    if (!projectId) return
    if (!form.title.trim()) { toast.error('请填写标题'); return }
    const contract = {
      key_events: splitLines(form.key_events),
      entry_state: form.entry_state.trim(),
      exit_state: form.exit_state.trim(),
      forbidden: splitLines(form.forbidden),
    }
    try {
      if (editing) {
        await updateChapterOutline(editing.id, { chapter_number: form.chapter_number, title: form.title, plot_points: form.plot_points || undefined, scene: form.scene || undefined, pov: form.pov || undefined, target_word_count: form.target_word_count, ...contract })
      } else {
        await createChapterOutline({ project_id: projectId, chapter_number: form.chapter_number, title: form.title, plot_points: form.plot_points || undefined, scene: form.scene || undefined, pov: form.pov || undefined, target_word_count: form.target_word_count, ...contract })
      }
      setShowModal(false)
    } catch { /* hook 已 toast */ }
  }

  const unconfirmed = sorted.filter(co => co.review_status === 'draft' || co.upstream_stale)

  const confirmOne = async (co: ChapterOutline) => {
    setConfirming(co.id)
    try {
      await chapterOutlineApi.confirmChapterOutline(co.id)
      await onRefresh()
      toast.success(`第${co.chapter_number}章章纲已确认`)
    } catch { /* 已 toast */ } finally { setConfirming(null) }
  }

  const confirmAll = async () => {
    if (!projectId || unconfirmed.length === 0) return
    if (!window.confirm(`确认全部 ${unconfirmed.length} 份待确认 / 上游已改的章纲？确认表示你已看过，可以照它写正文。`)) return
    setConfirming('all')
    try {
      const res = await chapterOutlineApi.confirmAllChapterOutlines(projectId)
      await onRefresh()
      toast.success(`已确认 ${res.confirmed} 份章纲`)
    } catch { /* 已 toast */ } finally { setConfirming(null) }
  }

  const handleBatchCreate = async () => {
    if (!projectId || batchCount < 1) return
    setBatchCreating(true)
    try {
      const startNum = sorted.length > 0 ? sorted[sorted.length - 1].chapter_number + 1 : 1
      const outlines: ChapterOutlineCreate[] = Array.from({ length: batchCount }, (_, i) => ({
        project_id: projectId,
        chapter_number: startNum + i,
        title: `第${startNum + i}章`,
        target_word_count: 3000,
      }))
      await batchCreateChapterOutlines({ project_id: projectId, outlines })
      setShowBatchModal(false)
    } catch { /* hook 已 toast */ } finally { setBatchCreating(false) }
  }

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }
  const toggleSelectAll = () => {
    setSelectedIds(prev => prev.size === chapterOutlines.length ? new Set() : new Set(chapterOutlines.map(co => co.id)))
  }
  const handleDelete = (co: ChapterOutline) => {
    setSelectedIds(new Set([co.id]))
    setConfirmDelete(true)
  }
  const handleDeleteSelected = () => {
    if (selectedIds.size === 0) { toast.error('请先选择要删除的章纲'); return }
    setConfirmDelete(true)
  }
  const executeDelete = async () => {
    setDeleting(true)
    try {
      for (const id of selectedIds) await deleteChapterOutline(id)
      toast.success(`已删除 ${selectedIds.size} 个章纲`)
      setSelectedIds(new Set())
    } catch { toast.error('删除失败') }
    finally { setDeleting(false); setConfirmDelete(false) }
  }

  return (
    <section className="hh-panel p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="font-serif text-lg font-semibold text-content">章纲</h2>
          <p className="mt-1 text-sm leading-6 text-content-secondary">
            逐章的章节契约（进入状态 → 关键事件 → 退出状态，外加禁止事项），是生成正文前的最后一层规划，共 {chapterOutlines.length} 章。
            AI 草拟或上游改过的章纲要确认后再写正文。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          {unconfirmed.length > 0 && (
            <button onClick={() => void confirmAll()} disabled={confirming !== null} className="hh-btn-secondary">
              {confirming === 'all' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}全部确认 ({unconfirmed.length})
            </button>
          )}
          {chapterOutlines.length > 0 && (
            <button onClick={handleDeleteSelected} disabled={selectedIds.size === 0} className="hh-btn-ghost text-cinnabar hover:bg-cinnabar-wash">
              <Trash2 className="h-4 w-4" />删除{selectedIds.size > 0 ? ` (${selectedIds.size})` : ''}
            </button>
          )}
          <button onClick={() => setShowBatchModal(true)} className="hh-btn-ghost">
            <Plus className="h-4 w-4" />批量创建
          </button>
          <button onClick={onOpenVolumes} className="hh-btn-secondary">
            <Sparkles className="h-4 w-4 text-brand" />去卷纲生成章纲
          </button>
          <button onClick={openCreate} className="hh-btn-primary">
            <Plus className="h-4 w-4" />新建章纲
          </button>
        </div>
      </div>

      {sorted.length === 0 ? (
        <EmptyBlock
          icon={BookOpen}
          title="还没有章纲"
          hint="章纲由「卷纲」里的剧情单元展开生成（按事件分章，长短不一）；也可点「新建章纲」手动添加，或在智能助笔里让章节策划师生成。"
        />
      ) : (
        <div className="mt-6 space-y-3">
          <div className="flex items-center gap-2.5 px-1">
            <input type="checkbox" checked={selectedIds.size === chapterOutlines.length && chapterOutlines.length > 0} onChange={toggleSelectAll} className="h-4 w-4" />
            <span className="text-xs text-content-secondary tabular-nums">{selectedIds.size > 0 ? `已选 ${selectedIds.size}/${chapterOutlines.length}` : '全选'}</span>
          </div>
          {sorted.map(co => (
            <article key={co.id} className={cn('hh-subpanel p-4 transition-colors', selectedIds.has(co.id) && 'lj-selected')}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <input type="checkbox" checked={selectedIds.has(co.id)} onChange={() => toggleSelect(co.id)} className="mt-1 h-4 w-4 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn(STATUS_TAG, 'shrink-0 rounded-sm bg-brand-100 text-brand-600 tabular-nums')}>#{co.chapter_number}</span>
                      <h3 className="min-w-0 max-w-full truncate text-[15px] font-semibold text-content">{co.title}</h3>
                      <OutlineReviewBadge co={co} />
                    </div>
                    {co.upstream_stale && co.upstream_reason && (
                      <p className="mt-1 text-[11px] text-cinnabar">{co.upstream_reason}</p>
                    )}
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-content-tertiary">
                      {co.scene && <span>场景: {co.scene}</span>}
                      {co.pov && <span>视角: {co.pov}</span>}
                      <span>目标字数: {co.target_word_count}</span>
                      {unitLabel(co) && <span>{unitLabel(co)}</span>}
                    </div>
                    {co.plot_points && <p className="mt-1.5 line-clamp-2 text-[13px] leading-6 text-content-secondary">{co.plot_points}</p>}
                    <KbCitationChips citations={outlineCitations[co.id]} className="mt-1.5" />
                    {co.key_events && co.key_events.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {co.key_events.map((ev, i) => (
                          <span key={i} className="rounded-sm bg-surface-muted px-2 py-0.5 text-[11px] text-content-secondary">{ev}</span>
                        ))}
                      </div>
                    )}
                    {(co.exit_state || (co.forbidden?.length ?? 0) > 0) && (
                      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-content-tertiary">
                        {co.exit_state && <span>写到：{co.exit_state}</span>}
                        {(co.forbidden?.length ?? 0) > 0 && <span>禁止：{co.forbidden!.join('；')}</span>}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {(co.review_status === 'draft' || co.upstream_stale) && (
                    <button onClick={() => void confirmOne(co)} disabled={confirming !== null} className="hh-btn-secondary hh-btn-sm h-8" title="看过了，可以照这份章纲写正文">
                      {confirming === co.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}确认
                    </button>
                  )}
                  <button onClick={() => setViewingChapterOutline(co)} className="hh-icon-btn-plain h-8 w-8" title="查看章纲详情"><Eye className="h-3.5 w-3.5" /></button>
                  <button onClick={() => openEdit(co)} className="hh-icon-btn-plain h-8 w-8" title="编辑"><Pencil className="h-3.5 w-3.5" /></button>
                  <button onClick={() => handleDelete(co)} className="hh-icon-btn-plain h-8 w-8 hover:text-cinnabar" title="删除"><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* 创建/编辑弹窗 */}
      {showModal && (
        <Modal
          title={editing ? '编辑章纲' : '新建章纲'}
          onClose={() => setShowModal(false)}
          size="xl"
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleSubmit} className="hh-btn-primary">确定</button>
            </>
          )}
        >
          <div className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="hh-label">章节序号</label>
                <input type="number" value={form.chapter_number} onChange={e => setForm(f => ({ ...f, chapter_number: Number(e.target.value) }))} className="hh-field" />
              </div>
              <div>
                <label className="hh-label">目标字数</label>
                <input type="number" value={form.target_word_count} onChange={e => setForm(f => ({ ...f, target_word_count: Number(e.target.value) }))} className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">标题</label>
              <input value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} className="hh-field" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="hh-label">场景</label>
                <input value={form.scene} onChange={e => setForm(f => ({ ...f, scene: e.target.value }))} placeholder="如：拳击场→后台" className="hh-field" />
              </div>
              <div>
                <label className="hh-label">视角角色</label>
                <input value={form.pov} onChange={e => setForm(f => ({ ...f, pov: e.target.value }))} className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">剧情要点</label>
              <textarea value={form.plot_points} onChange={e => setForm(f => ({ ...f, plot_points: e.target.value }))} rows={4} className="hh-textarea" />
            </div>
            <div className="space-y-4 rounded border border-surface-border bg-surface-paper p-4">
              <p className="text-xs leading-5 text-content-secondary">
                <span className="font-medium text-content">章节契约</span>：写正文时照「进入状态 → 关键事件 → 退出状态」推进，禁止事项不能提前发生；写完的遵循度审校也按这里核对。
              </p>
              <div>
                <label className="hh-label">进入状态（开头承接什么局面）</label>
                <textarea value={form.entry_state} onChange={e => setForm(f => ({ ...f, entry_state: e.target.value }))} rows={2} placeholder="如：林尘刚被逐出宗门，身负重伤躲在山洞" className="hh-textarea" />
              </div>
              <div>
                <label className="hh-label">关键事件（每行一条，按顺序；最后一条是章末落点）</label>
                <textarea value={form.key_events} onChange={e => setForm(f => ({ ...f, key_events: e.target.value }))} rows={4} className="hh-textarea" />
              </div>
              <div>
                <label className="hh-label">退出状态（写到哪里停）</label>
                <textarea value={form.exit_state} onChange={e => setForm(f => ({ ...f, exit_state: e.target.value }))} rows={2} placeholder="如：林尘认出画中人是年轻时的师父，章末停在他推门离开" className="hh-textarea" />
              </div>
              <div>
                <label className="hh-label">禁止事项（每行一条：本章不能写的事）</label>
                <textarea value={form.forbidden} onChange={e => setForm(f => ({ ...f, forbidden: e.target.value }))} rows={2} placeholder="如：不能揭露师父的真实身份" className="hh-textarea" />
              </div>
            </div>
          </div>
        </Modal>
      )}

      {/* 删除确认弹窗 */}
      {confirmDelete && (
        <Modal
          title="确认删除"
          onClose={() => setConfirmDelete(false)}
          size="md"
          footer={(
            <>
              <button onClick={() => setConfirmDelete(false)} disabled={deleting} className="hh-btn-ghost">取消</button>
              <button onClick={executeDelete} disabled={deleting} className="hh-btn-danger">
                {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                确认删除 ({selectedIds.size})
              </button>
            </>
          )}
        >
          <div className="space-y-3">
            <p className="text-sm leading-7 text-content-secondary">
              确定删除选中的 <span className="font-medium text-content">{selectedIds.size}</span> 个章纲？此操作不可撤销。
            </p>
            <div className="hh-subpanel max-h-32 space-y-0.5 overflow-y-auto px-4 py-3 text-xs text-content-secondary">
              {chapterOutlines.filter(co => selectedIds.has(co.id)).map(co => (
                <div key={co.id}>• 第{co.chapter_number}章：{co.title}</div>
              ))}
            </div>
          </div>
        </Modal>
      )}

      {/* 批量创建弹窗 */}
      {showBatchModal && (
        <Modal
          title="批量创建章纲"
          onClose={() => setShowBatchModal(false)}
          size="md"
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowBatchModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleBatchCreate} disabled={batchCreating} className="hh-btn-primary">
                {batchCreating && <Loader2 className="h-4 w-4 animate-spin" />}
                确定创建
              </button>
            </>
          )}
        >
          <div className="space-y-3">
            <div>
              <label className="hh-label">创建数量</label>
              <input type="number" min={1} max={50} value={batchCount} onChange={e => setBatchCount(Number(e.target.value))} className="hh-field" />
            </div>
            <p className="text-xs leading-5 text-content-tertiary">将从第 {sorted.length > 0 ? sorted[sorted.length - 1].chapter_number + 1 : 1} 章开始，自动编号创建 {batchCount} 个章纲。</p>
          </div>
        </Modal>
      )}

      {viewingChapterOutline && (
        <Modal
          title={`章纲详情：第${viewingChapterOutline.chapter_number}章`}
          onClose={() => setViewingChapterOutline(null)}
          size="xl"
          footer={(
            <button onClick={() => { const current = viewingChapterOutline; setViewingChapterOutline(null); if (current) openEdit(current) }} className="hh-btn-primary">
              <Pencil className="h-3.5 w-3.5" />编辑
            </button>
          )}
        >
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
              <span className={cn(STATUS_TAG, 'rounded-sm bg-brand-100 text-brand-600 tabular-nums')}>#{viewingChapterOutline.chapter_number}</span>
              <OutlineReviewBadge co={viewingChapterOutline} />
              {viewingChapterOutline.scene && <span>场景：{viewingChapterOutline.scene}</span>}
              {viewingChapterOutline.pov && <span>视角：{viewingChapterOutline.pov}</span>}
              <span>目标字数：{viewingChapterOutline.target_word_count}</span>
              {unitLabel(viewingChapterOutline) && <span>{unitLabel(viewingChapterOutline)}</span>}
            </div>
            <div className="hh-subpanel p-4">
              <p className="text-xs font-medium text-content-tertiary">标题</p>
              <p className="mt-1.5 text-sm font-medium text-content">{viewingChapterOutline.title}</p>
            </div>
            <div className="hh-subpanel p-4">
              <p className="text-xs font-medium text-content-tertiary">剧情要点</p>
              <p className="mt-1.5 whitespace-pre-wrap text-sm leading-7 text-content">{viewingChapterOutline.plot_points || '暂无内容'}</p>
            </div>
            {viewingChapterOutline.key_events && viewingChapterOutline.key_events.length > 0 && (
              <div className="hh-subpanel p-4">
                <p className="text-xs font-medium text-content-tertiary">关键事件</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {viewingChapterOutline.key_events.map((event, index) => (
                    <span key={`key-event-${index}`} className="bg-surface-hover px-2 py-1 text-xs text-content-secondary">
                      {event}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {(viewingChapterOutline.entry_state || viewingChapterOutline.exit_state || (viewingChapterOutline.forbidden?.length ?? 0) > 0) && (
              <div className="hh-subpanel space-y-2 p-4 text-sm">
                {viewingChapterOutline.entry_state && (
                  <p><span className="text-xs font-medium text-content-tertiary">进入状态：</span>{viewingChapterOutline.entry_state}</p>
                )}
                {viewingChapterOutline.exit_state && (
                  <p><span className="text-xs font-medium text-content-tertiary">退出状态：</span>{viewingChapterOutline.exit_state}</p>
                )}
                {(viewingChapterOutline.forbidden?.length ?? 0) > 0 && (
                  <div>
                    <p className="text-xs font-medium text-content-tertiary">禁止事项</p>
                    <ul className="mt-1 space-y-0.5 text-content-secondary">
                      {viewingChapterOutline.forbidden!.map((item) => <li key={item}>· {item}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {viewingChapterOutline.narrative_tasks && (
              <NarrativeTasksPanel tasks={viewingChapterOutline.narrative_tasks} chapterNumber={viewingChapterOutline.chapter_number} />
            )}
          </div>
        </Modal>
      )}
    </section>
  )
}

/** 章纲叙事任务：本章要回收 / 推进 / 埋下的伏笔（章纲展开时按未回收伏笔清单规划，写正文时进本章任务） */
function NarrativeTasksPanel({ tasks, chapterNumber }: { tasks: NarrativeTasks; chapterNumber: number }) {
  const rows = [
    ...tasks.resolve.map((t) => ({ kind: '回收', text: `${t.title}${t.how ? `：${t.how}` : ''}` })),
    ...tasks.advance.map((t) => ({ kind: '推进', text: `${t.title}${t.how ? `：${t.how}` : ''}` })),
    ...tasks.plant.map((t) => ({
      kind: '埋下',
      text: `${t.title}：${t.content}${t.payoff_after ? `（计划第 ${chapterNumber + t.payoff_after} 章前后回收）` : ''}`,
    })),
  ]
  if (rows.length === 0) return null
  return (
    <div className="hh-subpanel p-4">
      <p className="text-xs font-medium text-content-tertiary">叙事任务（伏笔 / 承诺）</p>
      <ul className="mt-2 space-y-1.5">
        {rows.map((r, i) => (
          <li key={`nt-${i}`} className="text-xs leading-5 text-content-secondary">
            <span className="mr-1.5 bg-brand/10 px-1.5 py-px text-[10px] font-medium text-brand">{r.kind}</span>
            {r.text}
          </li>
        ))}
      </ul>
    </div>
  )
}
