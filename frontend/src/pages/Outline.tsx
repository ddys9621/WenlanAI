import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Pencil, Trash2, FileText, Loader2, Sparkles, LayoutGrid, GitBranch, BookOpen, BarChart3, Check, ChevronDown, ChevronUp, Link2, Eye } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { useOutlineSync } from '@/store/hooks'
import { usePlotCardSync, usePlotLineSync, useChapterOutlineSync } from '@/store/plotHooks'
import { useAIJobsStore, useRunningAIJobs } from '@/store/aiJobsStore'
import { wizardStreamApi, outlineApi, chapterOutlineLinkApi, plotLineApi, plotCardApi } from '@/services/api'
import { AIJobBanner } from '@/components/ai-job/AIJobBanner'
import { MCPSelector } from '@/components/MCPSelector'
import {
  ReferencePackSelector,
  DEFAULT_SELECTOR_VALUE,
  type ReferencePackSelectorValue,
} from '@/components/ReferencePackSelector'
import { Modal as UiModal, type ModalSize } from '@/components/ui/Modal'
import type {
  Outline, OutlineCreate, OutlineUpdate,
  PlotCard, PlotCardCreate, PlotCardUpdate,
  PlotLine, PlotLineCreate, PlotLineUpdate,
  PlotLineProgress, TimelineData, TimelineBeat,
  PlotCardGenerateRequest, PlotLineGenerateRequest,
  ChapterOutline, ChapterOutlineCreate, ChapterOutlineUpdate,
  ChapterOutlineBatchCreateRequest,
} from '@/types'

type TabKey = 'outlines' | 'plotCards' | 'plotLines' | 'chapterOutlines' | 'overview'

const TABS: { key: TabKey; label: string; icon: React.ElementType }[] = [
  { key: 'outlines', label: '故事大纲', icon: FileText },
  { key: 'plotCards', label: '剧情卡片', icon: LayoutGrid },
  { key: 'plotLines', label: '剧情线', icon: GitBranch },
  { key: 'chapterOutlines', label: '章纲', icon: BookOpen },
  { key: 'overview', label: '关联总览', icon: BarChart3 },
]

const PLOT_LINE_TYPE_LABELS: Record<string, string> = {
  main: '主线',
  sub: '支线',
  character: '角色线',
  foreshadow: '伏笔线',
  other: '其他',
}

const PLOT_LINE_TYPE_ALIASES: Record<string, string> = {
  main: 'main',
  '主线': 'main',
  sub: 'sub',
  '支线': 'sub',
  character: 'character',
  '角色线': 'character',
  foreshadow: 'foreshadow',
  '伏笔线': 'foreshadow',
  other: 'other',
  '其他': 'other',
}

const PLOT_LINE_TYPE_COLORS: Record<string, string> = {
  main: 'bg-brand/10 text-brand',
  sub: 'bg-surface-hover text-content-secondary',
  character: 'bg-surface-hover text-content-secondary',
  foreshadow: 'bg-surface-hover text-content-secondary',
  other: 'bg-surface-hover text-content-secondary',
}

const STATUS_TAG = 'px-2 py-0.5 text-[11px] font-medium'

const normalizePlotLineType = (type?: string | null) => {
  const value = type?.trim()
  if (!value) return 'main'
  return PLOT_LINE_TYPE_ALIASES[value] || value
}

const getPlotLineTypeLabel = (type?: string | null) => {
  const normalized = normalizePlotLineType(type)
  return PLOT_LINE_TYPE_LABELS[normalized] || normalized
}

const getPlotLineTypeColor = (type?: string | null) => {
  const normalized = normalizePlotLineType(type)
  return PLOT_LINE_TYPE_COLORS[normalized] || PLOT_LINE_TYPE_COLORS.other
}


export default function OutlinePage() {
  const { currentProject, outlines } = useStore()
  const projectId = currentProject?.id
  const [activeTab, setActiveTab] = useState<TabKey>('outlines')
  const [loading, setLoading] = useState(false)

  // hooks
  const { refreshOutlines, createOutline, updateOutline, deleteOutline, activateOutline } = useOutlineSync()
  const { plotCards, refreshPlotCards, createPlotCard, updatePlotCard, deletePlotCard } = usePlotCardSync()
  const { plotLines, refreshPlotLines, createPlotLine, updatePlotLine: updatePlotLineData, deletePlotLine } = usePlotLineSync()
  const { chapterOutlines, refreshChapterOutlines, createChapterOutline, updateChapterOutline: updateChapterOutlineData, deleteChapterOutline, batchCreateChapterOutlines } = useChapterOutlineSync()

  // 初始化加载
  useEffect(() => {
    if (!projectId) return
    setLoading(true)
    Promise.all([
      refreshOutlines(),
      refreshPlotCards(projectId),
      refreshPlotLines(projectId),
      refreshChapterOutlines(projectId),
    ]).finally(() => setLoading(false))
  }, [projectId, refreshChapterOutlines, refreshOutlines, refreshPlotCards, refreshPlotLines])

  // ==================== Tab 容器 ====================
  return (
    <div className="animate-fade-in space-y-6">
      <section className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <h1 className="text-[28px] font-semibold tracking-tight text-content md:text-[32px]">故事大纲</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            先定整本书的骨架，再拆成剧情卡片、剧情线与章纲。当前有 {outlines.length} 个大纲版本、{plotCards.length} 张剧情卡片、{plotLines.length} 条剧情线、{chapterOutlines.length} 份章纲。
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
          {activeTab === 'outlines' && <OutlinesView outlines={outlines} projectId={projectId} createOutline={createOutline} updateOutline={updateOutline} deleteOutline={deleteOutline} activateOutline={activateOutline} refreshOutlines={refreshOutlines} />}
          {activeTab === 'plotCards' && <PlotCardsView plotCards={plotCards} projectId={projectId} outlines={outlines} createPlotCard={createPlotCard} updatePlotCard={updatePlotCard} deletePlotCard={deletePlotCard} refreshPlotCards={refreshPlotCards} />}
          {activeTab === 'plotLines' && <PlotLinesView plotLines={plotLines} plotCards={plotCards} projectId={projectId} outlines={outlines} createPlotLine={createPlotLine} updatePlotLine={updatePlotLineData} deletePlotLine={deletePlotLine} refreshPlotLines={refreshPlotLines} />}
          {activeTab === 'chapterOutlines' && <ChapterOutlinesView chapterOutlines={chapterOutlines} projectId={projectId} createChapterOutline={createChapterOutline} updateChapterOutline={updateChapterOutlineData} deleteChapterOutline={deleteChapterOutline} batchCreateChapterOutlines={batchCreateChapterOutlines} plotLines={plotLines} />}
          {activeTab === 'overview' && <OverviewPanel plotCards={plotCards} plotLines={plotLines} chapterOutlines={chapterOutlines} />}
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
function OutlinesView({ outlines, projectId, createOutline, updateOutline, deleteOutline, activateOutline, refreshOutlines }: {
  outlines: Outline[]
  projectId?: string
  createOutline: (data: OutlineCreate) => Promise<Outline>
  updateOutline: (id: string, data: OutlineUpdate) => Promise<Outline>
  deleteOutline: (id: string) => Promise<void>
  activateOutline: (id: string) => Promise<Outline>
  refreshOutlines: () => Promise<Outline[]>
}) {
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<Outline | null>(null)
  const [form, setForm] = useState({ title: '', premise: '', golden_finger: '', selling_points: '', power_system: '', main_tropes: '', ultimate_goal: '', opening_hook: '' })
  const [generating, setGenerating] = useState(false)
  const [showGenModal, setShowGenModal] = useState(false)
  const [genForm, setGenForm] = useState({ narrative_perspective: '第三人称', chapter_count: 30, target_words: 100000, requirements: '' })
  const [genEnableMcp, setGenEnableMcp] = useState(false)
  const [genPlugins, setGenPlugins] = useState<string[]>([])
  // R8：拆书参考包选择器状态（默认关；disabled 时不传任何 R8 字段走"自动模式"）
  const [genRefPack, setGenRefPack] = useState<ReferencePackSelectorValue>(DEFAULT_SELECTOR_VALUE)
  const [viewingOutline, setViewingOutline] = useState<Outline | null>(null)
  const [expandedOutlineId, setExpandedOutlineId] = useState<string | null>(null)
  const [linkedPlotLines, setLinkedPlotLines] = useState<Record<string, Array<{ id: string; title: string; description?: string; line_type?: string }>>>({})
  const [loadingLinks, setLoadingLinks] = useState<string | null>(null)

  const togglePlotLines = async (outlineId: string) => {
    if (expandedOutlineId === outlineId) { setExpandedOutlineId(null); return }
    setExpandedOutlineId(outlineId)
    if (linkedPlotLines[outlineId]) return
    setLoadingLinks(outlineId)
    try {
      const lines = await outlineApi.getPlotLines(outlineId)
      setLinkedPlotLines(prev => ({ ...prev, [outlineId]: lines }))
    } catch { /* ignore failed relation preview */ }
    finally { setLoadingLinks(null) }
  }

  const openCreate = () => { setEditing(null); setForm({ title: '', premise: '', golden_finger: '', selling_points: '', power_system: '', main_tropes: '', ultimate_goal: '', opening_hook: '' }); setShowModal(true) }
  const openEdit = (o: Outline) => {
    const f = { title: o.title, premise: o.content, golden_finger: '', selling_points: '', power_system: '', main_tropes: '', ultimate_goal: '', opening_hook: '' };
    try {
      const parsed = JSON.parse(o.content);
      if (typeof parsed === 'object') {
        f.premise = parsed.premise || '';
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

  const handleAIGenerate = async () => {
    if (!projectId) return
    setGenerating(true)
    setShowGenModal(false)
    try {
      await wizardStreamApi.generateCompleteOutlineStream(
        {
          project_id: projectId,
          narrative_perspective: genForm.narrative_perspective,
          chapter_count: genForm.chapter_count,
          target_words: genForm.target_words,
          requirements: genForm.requirements.trim() || undefined,
          enable_mcp: genEnableMcp,
          selected_plugins: genPlugins,
          // R8：仅 enabled 时传递拆书参考包参数（否则后端走默认自动模式）
          ...(genRefPack.enabled ? {
            pack_ids: genRefPack.packIds.length > 0 ? genRefPack.packIds : undefined,
            dimensions: genRefPack.dimensions.length > 0 ? genRefPack.dimensions : undefined,
            strength: genRefPack.strength,
          } : {}),
        },
        {
          onProgress: (msg) => { toast.info(msg, { id: 'outline-gen' }) },
          onResult: () => { toast.success('故事大纲生成完成', { id: 'outline-gen' }); refreshOutlines() },
          onError: (err) => { toast.error(`生成失败: ${err}`, { id: 'outline-gen' }) },
        }
      )
    } catch { toast.error('AI 生成故事大纲失败') } finally { setGenerating(false) }
  }

  const handleSubmit = async () => {
    if (!projectId) return
    if (!form.title.trim()) { toast.error('请填写标题'); return }
    const contentJson = JSON.stringify({
      premise: form.premise,
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
            整本书的骨架：梗概、金手指、卖点与终极目标。活跃版本会作为剧情卡片、剧情线与章纲生成的依据，共 {outlines.length} 个版本。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={() => setShowGenModal(true)} disabled={generating} className="hh-btn-secondary">
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
                    <button
                      onClick={() => togglePlotLines(o.id)}
                      className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand hover:text-brand-600"
                    >
                      <GitBranch className="h-3 w-3" />
                      关联剧情线
                      {expandedOutlineId === o.id ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    </button>
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
              {expandedOutlineId === o.id && (
                <div className="mt-3 border-t border-surface-border/80 pt-3">
                  {loadingLinks === o.id ? (
                    <div className="flex items-center gap-2 text-xs text-content-secondary"><Loader2 className="h-3 w-3 animate-spin" />加载中...</div>
                  ) : (linkedPlotLines[o.id] || []).length === 0 ? (
                    <p className="text-xs text-content-tertiary">暂无关联剧情线</p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {(linkedPlotLines[o.id] || []).map(pl => (
                        <span key={pl.id} className="hh-tag">
                          <GitBranch className="h-3 w-3" />
                          {pl.title}
                          {pl.line_type && <span className="text-brand/60">({getPlotLineTypeLabel(pl.line_type)})</span>}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
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
                <input type="number" value={genForm.chapter_count} onChange={e => setGenForm(f => ({ ...f, chapter_count: Number(e.target.value) }))} className="hh-field" />
              </div>
              <div>
                <label className="hh-label">目标字数</label>
                <input type="number" value={genForm.target_words} onChange={e => setGenForm(f => ({ ...f, target_words: Number(e.target.value) }))} className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">额外要求（可选）</label>
              <textarea value={genForm.requirements} onChange={e => setGenForm(f => ({ ...f, requirements: e.target.value }))} placeholder="对大纲的特殊要求..." rows={2} className="hh-textarea" />
            </div>
            <MCPSelector value={{ enable: genEnableMcp, selected: genPlugins }} onChange={({ enable, selected }) => { setGenEnableMcp(enable); setGenPlugins(selected) }} />
            {projectId && (
              <ReferencePackSelector
                projectId={projectId}
                value={genRefPack}
                onChange={setGenRefPack}
                hint="让本次故事大纲参考拆书的方法论/结构/世界观"
                disabledTitle="使用拆书参考包作为对标书"
              />
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
              <label className="hh-label">金手指设定</label>
              <input value={form.golden_finger} onChange={e => setForm(f => ({ ...f, golden_finger: e.target.value }))} placeholder="主角的核心优势" className="hh-field" />
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
              <label className="hh-label">升级路线</label>
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
          ['golden_finger', '金手指设定'],
          ['selling_points', '核心卖点'],
          ['power_system', '升级路线'],
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
// ==================== Tab 2: 剧情卡片 ====================
function PlotCardsView({ plotCards, projectId, outlines, createPlotCard, updatePlotCard, deletePlotCard, refreshPlotCards }: {
  plotCards: PlotCard[]
  projectId?: string
  outlines: Outline[]
  createPlotCard: (data: PlotCardCreate) => Promise<PlotCard>
  updatePlotCard: (id: string, data: PlotCardUpdate) => Promise<PlotCard>
  deletePlotCard: (id: string) => Promise<void>
  refreshPlotCards: (projectId: string) => Promise<unknown>
}) {
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<PlotCard | null>(null)
  const [form, setForm] = useState({ title: '', content: '', card_type: '起因', order_index: 0 })
  // AI 生成走通用后台任务：禁用态由 store 派生（刷新后仍正确）
  const startJob = useAIJobsStore((s) => s.start)
  const generating = useRunningAIJobs(projectId, ['plot_cards_generate']).length > 0
  const [showGenModal, setShowGenModal] = useState(false)
  const [genForm, setGenForm] = useState({ card_type: '起因', count: 5, prompt: '', extend_from_card_id: '' })
  const [genEnableMcp, setGenEnableMcp] = useState(false)
  const [genPlugins, setGenPlugins] = useState<string[]>([])

  const CARD_TYPES = ['起因', '经过', '高潮', '结局', '伏笔', '转折', '其他']

  const openCreate = () => { setEditing(null); setForm({ title: '', content: '', card_type: '起因', order_index: plotCards.length }); setShowModal(true) }
  const openEdit = (c: PlotCard) => { setEditing(c); setForm({ title: c.title, content: c.content || '', card_type: c.card_type, order_index: c.order_index ?? 0 }); setShowModal(true) }

  const handleSubmit = async () => {
    if (!projectId) return
    if (!form.title.trim()) { toast.error('请填写标题'); return }
    try {
      if (editing) {
        await updatePlotCard(editing.id, { title: form.title, content: form.content, card_type: form.card_type, order_index: form.order_index })
      } else {
        await createPlotCard({ project_id: projectId, title: form.title, content: form.content, card_type: form.card_type, order_index: form.order_index })
      }
      setShowModal(false)
    } catch { /* hook 已 toast */ }
  }

  /** AI 生成剧情卡：通用后台任务（弹窗展示 MCP 规划 / 参考包 / 模型进度；可最小化、可停止、刷新后可重连） */
  const handleGenerate = async () => {
    if (!projectId) return
    const activeOutline = outlines.find(o => o.is_active) || outlines[0]
    if (!activeOutline) { toast.error('请先创建故事大纲'); return }
    const payload: PlotCardGenerateRequest = {
      project_id: projectId,
      outline_id: activeOutline.id,
      card_type: genForm.card_type,
      count: genForm.count,
      extend_from_card_id: genForm.extend_from_card_id || undefined,
      prompt: genForm.prompt.trim() || undefined,
      enable_mcp: genEnableMcp,
      selected_plugins: genPlugins,
    }
    setShowGenModal(false)
    try {
      await startJob({
        kind: 'plot_cards_generate',
        title: `AI 生成剧情卡（${genForm.count} 张）`,
        projectId,
        connect: (options) => plotCardApi.generatePlotCardsStream(payload, options),
        onSettled: (job) => {
          if (job.status !== 'done') return
          const cards = Array.isArray(job.result) ? job.result : []
          toast.success(`成功生成 ${cards.length} 个剧情卡片`)
          void refreshPlotCards(projectId)
        },
      })
    } catch (err) { toast.error(err instanceof Error ? err.message : 'AI 生成剧情卡片失败') }
  }

  const handleDelete = async (c: PlotCard) => {
    if (!confirm(`确定删除「${c.title}」？`)) return
    try { await deletePlotCard(c.id) } catch { /* hook 已 toast */ }
  }

  return (
    <section className="hh-panel space-y-4 p-6">
      <AIJobBanner projectId={projectId} kinds={['plot_cards_generate']} />
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-tight text-content">剧情卡片</h2>
          <p className="mt-1 text-sm leading-6 text-content-secondary">
            把大纲拆成一张张可排序的剧情片段，按起因、经过、高潮、结局组织，共 {plotCards.length} 张。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={() => setShowGenModal(true)} disabled={generating} className="hh-btn-secondary">
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4 text-brand" />}
            AI 生成
          </button>
          <button onClick={openCreate} className="hh-btn-primary">
            <Plus className="h-4 w-4" />
            新建卡片
          </button>
        </div>
      </div>

      {plotCards.length === 0 ? (
        <EmptyBlock
          icon={LayoutGrid}
          title="还没有剧情卡片"
          hint="点击右上角「新建卡片」手动添加，或用「AI 生成」基于活跃的故事大纲批量生成剧情片段。"
        />
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[...plotCards].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0)).map(c => (
            <article key={c.id} className="hh-subpanel flex flex-col gap-2 p-4">
              <div className="flex items-start justify-between gap-2">
                <h3 className="min-w-0 flex-1 truncate text-[15px] font-semibold text-content">{c.title}</h3>
                <div className="flex shrink-0 items-center gap-1">
                  <button onClick={() => openEdit(c)} className="hh-icon-btn-plain h-8 w-8" title="编辑"><Pencil className="h-3.5 w-3.5" /></button>
                  <button onClick={() => handleDelete(c)} className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="删除"><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={cn(STATUS_TAG, 'bg-brand/10 text-brand')}>{c.card_type}</span>
                {c.order_index != null && <span className="text-xs text-content-tertiary tabular-nums">#{c.order_index + 1}</span>}
              </div>
              {c.content && <p className="line-clamp-3 text-[13px] leading-6 text-content-secondary">{c.content}</p>}
            </article>
          ))}
        </div>
      )}

      {showGenModal && (
        <Modal
          title="AI 生成剧情卡片"
          onClose={() => setShowGenModal(false)}
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowGenModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleGenerate} disabled={generating} className="hh-btn-primary">
                {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                开始生成
              </button>
            </>
          )}
        >
          <div className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="hh-label">卡片类型</label>
                <select value={genForm.card_type} onChange={e => setGenForm(f => ({ ...f, card_type: e.target.value }))} className="hh-field">
                  {CARD_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="hh-label">生成数量</label>
                <input type="number" min={1} max={20} value={genForm.count} onChange={e => setGenForm(f => ({ ...f, count: Number(e.target.value) }))} className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">从已有卡片延伸（可选）</label>
              <select value={genForm.extend_from_card_id} onChange={e => setGenForm(f => ({ ...f, extend_from_card_id: e.target.value }))} className="hh-field">
                <option value="">不指定</option>
                {plotCards.map(c => <option key={c.id} value={c.id}>{c.title} [{c.card_type}]</option>)}
              </select>
            </div>
            <div>
              <label className="hh-label">提示词（可选）</label>
              <textarea value={genForm.prompt} onChange={e => setGenForm(f => ({ ...f, prompt: e.target.value }))} placeholder="对剧情卡片的特殊要求..." rows={2} className="hh-textarea" />
            </div>
            <MCPSelector value={{ enable: genEnableMcp, selected: genPlugins }} onChange={({ enable, selected }) => { setGenEnableMcp(enable); setGenPlugins(selected) }} />
          </div>
        </Modal>
      )}

      {showModal && (
        <Modal
          title={editing ? '编辑剧情卡片' : '新建剧情卡片'}
          onClose={() => setShowModal(false)}
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
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="hh-label">类型</label>
                <select value={form.card_type} onChange={e => setForm(f => ({ ...f, card_type: e.target.value }))} className="hh-field">
                  {CARD_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="hh-label">排序号</label>
                <input type="number" value={form.order_index} onChange={e => setForm(f => ({ ...f, order_index: Number(e.target.value) }))} className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">内容</label>
              <textarea value={form.content} onChange={e => setForm(f => ({ ...f, content: e.target.value }))} rows={5} className="hh-textarea" />
            </div>
          </div>
        </Modal>
      )}
    </section>
  )
}
// ==================== Tab 3: 剧情线 ====================
type EditableBeat = {
  key: string
  title: string
  description: string
  weight: number
}

function PlotLinesView({ plotLines, projectId, outlines, plotCards, createPlotLine, updatePlotLine, deletePlotLine, refreshPlotLines }: {
  plotLines: PlotLine[]
  projectId?: string
  outlines: Outline[]
  plotCards: PlotCard[]
  createPlotLine: (data: PlotLineCreate) => Promise<PlotLine>
  updatePlotLine: (id: string, data: PlotLineUpdate) => Promise<PlotLine>
  deletePlotLine: (id: string) => Promise<void>
  refreshPlotLines: (projectId: string) => Promise<unknown>
}) {
  const defaultLineType = normalizePlotLineType(plotLines[0]?.line_type)
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<PlotLine | null>(null)
  const [viewing, setViewing] = useState<PlotLine | null>(null)
  const [viewingProgress, setViewingProgress] = useState<PlotLineProgress | null>(null)
  const [loadingProgress, setLoadingProgress] = useState(false)
  const [form, setForm] = useState({ title: '', description: '', line_type: defaultLineType, estimated_chapters: 0, beats: [] as EditableBeat[] })
  // AI 生成走通用后台任务：禁用态由 store 派生（刷新后仍正确）
  const startJob = useAIJobsStore((s) => s.start)
  const generating = useRunningAIJobs(projectId, ['plot_lines_generate']).length > 0
  const [showGenModal, setShowGenModal] = useState(false)
  const [genForm, setGenForm] = useState({ line_type: defaultLineType, count: 3, prompt: '', based_on_lines: [] as string[], based_on_cards: [] as string[] })
  const [genEnableMcp, setGenEnableMcp] = useState(false)
  const [genPlugins, setGenPlugins] = useState<string[]>([])

  const presetLineTypes = ['main', 'sub', 'character', 'foreshadow', 'other']
  const lineTypes = Array.from(new Set([
    ...presetLineTypes,
    ...plotLines.map(line => normalizePlotLineType(line.line_type)),
    normalizePlotLineType(form.line_type),
    normalizePlotLineType(genForm.line_type),
  ].filter(Boolean)))


  const toEditableBeats = (line: PlotLine | null): EditableBeat[] => {
    const beats = Array.isArray(line?.timeline_data?.beats) ? line.timeline_data.beats : []
    return beats
      .slice()
      .sort((a: TimelineBeat, b: TimelineBeat) => a.index - b.index)
      .map((beat: TimelineBeat, index: number) => ({
        key: beat.key || `beat_${index + 1}`,
        title: beat.title || '',
        description: beat.description || '',
        weight: Number.isFinite(Number(beat.weight)) ? Number(beat.weight) : 0,
      }))
  }

  const buildTimelineData = (beats: EditableBeat[]): TimelineData | undefined => {
    const cleaned = beats
      .map((beat, index) => ({
        index: index + 1,
        key: beat.key.trim() || `beat_${index + 1}`,
        title: beat.title.trim(),
        description: beat.description.trim() || undefined,
        weight: Number(beat.weight),
      }))
      .filter(beat => beat.title)

    return cleaned.length > 0 ? { beats: cleaned } : undefined
  }

  const totalWeight = form.beats.reduce((sum, beat) => sum + (Number(beat.weight) || 0), 0)
  const weightIsValid = form.beats.length === 0 || Math.abs(totalWeight - 1) < 0.01

  const rebalanceBeats = (beats: EditableBeat[]) => {
    if (beats.length === 0) return []
    const evenWeight = Number((1 / beats.length).toFixed(2))
    const next = beats.map((beat, index) => ({
      ...beat,
      weight: index === beats.length - 1
        ? Number((1 - evenWeight * (beats.length - 1)).toFixed(2))
        : evenWeight,
    }))
    return next
  }

  const openCreate = () => {
    setEditing(null)
    setForm({ title: '', description: '', line_type: defaultLineType, estimated_chapters: 0, beats: [] })
    setShowModal(true)
  }

  const openEdit = (line: PlotLine) => {
    setEditing(line)
    setForm({
      title: line.title,
      description: line.description || '',
      line_type: normalizePlotLineType(line.line_type),
      estimated_chapters: line.estimated_chapters ?? 0,
      beats: toEditableBeats(line),
    })
    setShowModal(true)
  }

  const openView = async (line: PlotLine) => {
    setViewing(line)
    setViewingProgress(null)
    setLoadingProgress(true)
    try {
      const progress = await plotLineApi.getPlotLineProgress(line.id)
      setViewingProgress(progress)
    } catch (error) {
      console.error('加载剧情线进度失败:', error)
      toast.error('加载剧情线详情失败')
    } finally {
      setLoadingProgress(false)
    }
  }

  const handleBeatChange = (index: number, field: keyof EditableBeat, value: string | number) => {
    setForm(prev => ({
      ...prev,
      beats: prev.beats.map((beat, beatIndex) => beatIndex === index ? { ...beat, [field]: field === 'weight' ? Number(value) : value } : beat),
    }))
  }

  const handleAddBeat = () => {
    setForm(prev => ({
      ...prev,
      beats: rebalanceBeats([
        ...prev.beats,
        {
          key: `beat_${prev.beats.length + 1}`,
          title: '',
          description: '',
          weight: 0,
        },
      ]),
    }))
  }

  const handleRemoveBeat = (index: number) => {
    setForm(prev => ({
      ...prev,
      beats: rebalanceBeats(prev.beats.filter((_, beatIndex) => beatIndex !== index)),
    }))
  }

  const handleSubmit = async () => {
    if (!projectId) return
    if (!form.title.trim()) { toast.error('请填写名称'); return }
    if (form.beats.some(beat => !beat.title.trim())) { toast.error('请先补全所有节点标题'); return }
    if (!weightIsValid) { toast.error('节点权重总和必须接近 1.00'); return }

    const timelineData = buildTimelineData(form.beats)
    try {
      if (editing) {
        await updatePlotLine(editing.id, {
          title: form.title,
          description: form.description,
          line_type: normalizePlotLineType(form.line_type),
          estimated_chapters: form.estimated_chapters || undefined,
          timeline_data: timelineData,
        })
      } else {
        await createPlotLine({
          project_id: projectId,
          title: form.title,
          description: form.description,
          line_type: normalizePlotLineType(form.line_type),
          estimated_chapters: form.estimated_chapters || undefined,
          timeline_data: timelineData,
        })
      }
      setShowModal(false)
    } catch { /* hook 已 toast */ }
  }

  /** AI 生成剧情线：通用后台任务（弹窗展示每条结构 / 节点规划 / MCP / 参考包进度；可最小化、可停止、刷新后可重连） */
  const handleGenerate = async () => {
    if (!projectId) return
    const activeOutline = outlines.find(o => o.is_active) || outlines[0]
    const payload: PlotLineGenerateRequest = {
      project_id: projectId,
      story_outline_id: activeOutline?.id,
      line_type: normalizePlotLineType(genForm.line_type),
      count: genForm.count,
      based_on_lines: genForm.based_on_lines.length ? genForm.based_on_lines : undefined,
      based_on_cards: genForm.based_on_cards.length ? genForm.based_on_cards : undefined,
      prompt: genForm.prompt.trim() || undefined,
      extend_existing: false,
      enable_mcp: genEnableMcp,
      selected_plugins: genPlugins,
    }
    setShowGenModal(false)
    try {
      await startJob({
        kind: 'plot_lines_generate',
        title: `AI 生成剧情线（${genForm.count} 条）`,
        projectId,
        connect: (options) => plotLineApi.generatePlotLinesStream(payload, options),
        onSettled: (job) => {
          if (job.status !== 'done') return
          const lines = Array.isArray(job.result) ? job.result : []
          toast.success(`成功生成 ${lines.length} 条剧情线`)
          void refreshPlotLines(projectId)
        },
      })
    } catch (err) { toast.error(err instanceof Error ? err.message : 'AI 生成剧情线失败') }
  }

  const handleDelete = async (l: PlotLine) => {
    if (!confirm(`确定删除「${l.title}」？`)) return
    try { await deletePlotLine(l.id) } catch { /* hook 已 toast */ }
  }

  return (
    <section className="hh-panel space-y-4 p-6">
      <AIJobBanner projectId={projectId} kinds={['plot_lines_generate']} />
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-tight text-content">剧情线</h2>
          <p className="mt-1 text-sm leading-6 text-content-secondary">
            主线、支线与伏笔线各自的推进节奏；节点权重决定章纲覆盖时的进度计算，共 {plotLines.length} 条。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={() => setShowGenModal(true)} disabled={generating} className="hh-btn-secondary">
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4 text-brand" />}
            AI 生成
          </button>
          <button onClick={openCreate} className="hh-btn-primary">
            <Plus className="h-4 w-4" />
            新建剧情线
          </button>
        </div>
      </div>

      {plotLines.length === 0 ? (
        <EmptyBlock
          icon={GitBranch}
          title="还没有剧情线"
          hint="点击右上角「新建剧情线」手动规划，或用「AI 生成」基于故事大纲与剧情卡片生成主线和支线。"
        />
      ) : (
        <div className="mt-6 space-y-3">
          {plotLines.map(l => (
            <article key={l.id} className="hh-subpanel p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center bg-brand/10 text-brand">
                    <GitBranch className="h-5 w-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="min-w-0 max-w-full truncate text-[15px] font-semibold text-content">{l.title}</h3>
                      <span className={cn(STATUS_TAG, getPlotLineTypeColor(l.line_type))}>{getPlotLineTypeLabel(l.line_type)}</span>
                    </div>
                    {l.description && <p className="mt-1.5 line-clamp-2 text-[13px] leading-6 text-content-secondary">{l.description}</p>}
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-content-tertiary tabular-nums">
                      {l.plot_card_count != null && <span>关联卡片: {l.plot_card_count}</span>}
                      {l.chapter_outline_count != null && <span>关联章纲: {l.chapter_outline_count}</span>}
                      {l.estimated_chapters != null && l.estimated_chapters > 0 && <span>预计章节: {l.estimated_chapters}</span>}
                    </div>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button onClick={() => openView(l)} className="hh-icon-btn-plain h-8 w-8" title="查看详情"><Eye className="h-3.5 w-3.5" /></button>
                  <button onClick={() => openEdit(l)} className="hh-icon-btn-plain h-8 w-8" title="编辑剧情线与节点"><Pencil className="h-3.5 w-3.5" /></button>
                  <button onClick={() => handleDelete(l)} className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="删除"><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              </div>
              {Array.isArray(l.timeline_data?.beats) && l.timeline_data.beats.length > 0 ? (
                <div className="mt-4 border-t border-surface-border/80 pt-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium text-content">剧情节点</p>
                    <span className="text-xs text-content-tertiary tabular-nums">{l.timeline_data.beats.length} 个</span>
                  </div>
                  <div className="mt-1 divide-y divide-surface-border/80">
                    {l.timeline_data.beats.slice(0, 4).map((beat: TimelineBeat) => (
                      <div key={`${l.id}-${beat.index}`} className="flex items-center justify-between gap-3 py-2">
                        <div className="min-w-0">
                          <p className="truncate text-xs font-medium text-content">节点 {beat.index} · {beat.title}</p>
                          {beat.description && <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-content-secondary">{beat.description}</p>}
                        </div>
                        <span className="shrink-0 text-[11px] text-content-tertiary tabular-nums">权重 {(Number(beat.weight) * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                  {l.timeline_data.beats.length > 4 && (
                    <p className="mt-2 text-xs text-content-tertiary">还有 {l.timeline_data.beats.length - 4} 个节点，点击右侧「查看详情」可查看全部。</p>
                  )}
                </div>
              ) : (
                <div className="mt-4 border border-dashed border-surface-border px-3 py-2.5 text-xs text-content-tertiary">
                  暂无节点，点击右侧「编辑」可直接补充剧情节点。
                </div>
              )}
            </article>
          ))}
        </div>
      )}

      {showGenModal && (
        <Modal
          title="AI 生成剧情线"
          onClose={() => setShowGenModal(false)}
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowGenModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleGenerate} disabled={generating} className="hh-btn-primary">
                {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                开始生成
              </button>
            </>
          )}
        >
          <div className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="hh-label">剧情线类型</label>
                <select value={genForm.line_type} onChange={e => setGenForm(f => ({ ...f, line_type: e.target.value }))} className="hh-field">
                  {lineTypes.map(t => <option key={t} value={t}>{getPlotLineTypeLabel(t)}</option>)}
                </select>
              </div>
              <div>
                <label className="hh-label">生成数量</label>
                <input type="number" min={1} max={10} value={genForm.count} onChange={e => setGenForm(f => ({ ...f, count: Number(e.target.value) }))} className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">基于已有剧情线（可选，保持连贯性）</label>
              <div className="hh-subpanel max-h-32 space-y-0.5 overflow-y-auto p-1.5">
                {plotLines.length > 0 ? plotLines.map(pl => (
                  <label key={pl.id} className="flex cursor-pointer items-center gap-2 px-2 py-1.5 text-sm text-content hover:bg-brand/5">
                    <input type="checkbox" checked={genForm.based_on_lines.includes(pl.id)} onChange={e => {
                      setGenForm(f => ({ ...f, based_on_lines: e.target.checked ? [...f.based_on_lines, pl.id] : f.based_on_lines.filter(id => id !== pl.id) }))
                    }} className="h-3.5 w-3.5" />
                    <span>{pl.title}</span>
                    <span className="text-xs text-content-tertiary">[{getPlotLineTypeLabel(pl.line_type)}]</span>
                  </label>
                )) : <p className="px-2 py-1.5 text-xs text-content-tertiary">暂无已有剧情线</p>}
              </div>
            </div>
            <div>
              <label className="hh-label">基于剧情卡片（可选）</label>
              <div className="hh-subpanel max-h-32 space-y-0.5 overflow-y-auto p-1.5">
                {plotCards.length > 0 ? plotCards.map(pc => (
                  <label key={pc.id} className="flex cursor-pointer items-center gap-2 px-2 py-1.5 text-sm text-content hover:bg-brand/5">
                    <input type="checkbox" checked={genForm.based_on_cards.includes(pc.id)} onChange={e => {
                      setGenForm(f => ({ ...f, based_on_cards: e.target.checked ? [...f.based_on_cards, pc.id] : f.based_on_cards.filter(id => id !== pc.id) }))
                    }} className="h-3.5 w-3.5" />
                    <span>{pc.title}</span>
                    <span className="text-xs text-content-tertiary">[{pc.card_type}]</span>
                  </label>
                )) : <p className="px-2 py-1.5 text-xs text-content-tertiary">暂无剧情卡片</p>}
              </div>
            </div>
            <div>
              <label className="hh-label">提示词（可选）</label>
              <textarea value={genForm.prompt} onChange={e => setGenForm(f => ({ ...f, prompt: e.target.value }))} placeholder="对剧情线的特殊要求..." rows={2} className="hh-textarea" />
            </div>
            <MCPSelector value={{ enable: genEnableMcp, selected: genPlugins }} onChange={({ enable, selected }) => { setGenEnableMcp(enable); setGenPlugins(selected) }} />
          </div>
        </Modal>
      )}

      {showModal && (
        <Modal
          title={editing ? '编辑剧情线' : '新建剧情线'}
          onClose={() => setShowModal(false)}
          size="2xl"
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
              <label className="hh-label">名称</label>
              <input value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} className="hh-field" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="hh-label">类型</label>
                <select value={form.line_type} onChange={e => setForm(f => ({ ...f, line_type: e.target.value }))} className="hh-field">
                  {lineTypes.map(t => <option key={t} value={t}>{getPlotLineTypeLabel(t)}</option>)}
                </select>
              </div>
              <div>
                <label className="hh-label">预计章节数</label>
                <input type="number" value={form.estimated_chapters} onChange={e => setForm(f => ({ ...f, estimated_chapters: Number(e.target.value) }))} className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">描述</label>
              <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={4} className="hh-textarea" />
            </div>
            <div className="hh-subpanel space-y-4 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-content">剧情节点</p>
                  <p className="mt-1 text-xs leading-5 text-content-secondary">可直接编辑节点标题、描述和权重，权重总和需要接近 1.00。</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {form.beats.length > 1 && (
                    <button onClick={() => setForm(prev => ({ ...prev, beats: rebalanceBeats(prev.beats) }))} className="hh-btn-ghost hh-btn-sm">
                      平均分配权重
                    </button>
                  )}
                  <button onClick={handleAddBeat} className="hh-btn-secondary hh-btn-sm">
                    <Plus className="h-3.5 w-3.5" />添加节点
                  </button>
                </div>
              </div>

              {form.beats.length === 0 ? (
                <div className="border border-dashed border-surface-border px-4 py-5 text-center text-xs leading-5 text-content-tertiary">
                  还没有节点。添加后就能在列表里看到节点摘要，也能在详情里看到完整进度。
                </div>
              ) : (
                <div className="max-h-[42vh] space-y-3 overflow-y-auto pr-1">
                  {form.beats.map((beat, index) => (
                    <div key={`beat-editor-${index}`} className="space-y-3 border border-surface-border bg-white/70 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-medium text-content">节点 {index + 1}</p>
                        <button onClick={() => handleRemoveBeat(index)} className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="删除节点">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                        <div>
                          <label className="hh-label">节点标题</label>
                          <input value={beat.title} onChange={e => handleBeatChange(index, 'title', e.target.value)} placeholder={`例如：节点 ${index + 1}`} className="hh-field" />
                        </div>
                        <div>
                          <label className="hh-label">节点标识</label>
                          <input value={beat.key} onChange={e => handleBeatChange(index, 'key', e.target.value)} placeholder={`beat_${index + 1}`} className="hh-field" />
                        </div>
                      </div>
                      <div>
                        <label className="hh-label">节点描述</label>
                        <textarea value={beat.description} onChange={e => handleBeatChange(index, 'description', e.target.value)} rows={3} className="hh-textarea" />
                      </div>
                      <div>
                        <label className="hh-label">权重</label>
                        <input type="number" min={0} max={1} step={0.01} value={beat.weight} onChange={e => handleBeatChange(index, 'weight', e.target.value)} className="hh-field" />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className={cn('px-3 py-2 text-xs font-medium', weightIsValid ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600')}>
                当前权重总和：{totalWeight.toFixed(2)}{weightIsValid ? '，可以保存。' : '，请调整到 1.00 附近。'}
              </div>
            </div>
          </div>
        </Modal>
      )}

      {viewing && (
        <Modal
          title={`剧情线详情：${viewing.title}`}
          onClose={() => { setViewing(null); setViewingProgress(null) }}
          size="2xl"
          footer={(
            <button onClick={() => { const current = viewing; setViewing(null); setViewingProgress(null); if (current) openEdit(current) }} className="hh-btn-primary">
              <Pencil className="h-3.5 w-3.5" />编辑节点
            </button>
          )}
        >
          <div className="space-y-5">
            {/* 顶部元信息栏 */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className={cn(STATUS_TAG, getPlotLineTypeColor(viewing.line_type))}>{getPlotLineTypeLabel(viewing.line_type)}</span>
              <div className="flex flex-wrap items-center gap-4 text-xs text-content-secondary tabular-nums">
                {viewing.estimated_chapters != null && viewing.estimated_chapters > 0 && (
                  <span className="inline-flex items-center gap-1"><BookOpen className="h-3.5 w-3.5" />预计 {viewing.estimated_chapters} 章</span>
                )}
                <span className="inline-flex items-center gap-1"><Link2 className="h-3.5 w-3.5" />章纲 {viewing.chapter_outline_count ?? 0}</span>
                <span className="inline-flex items-center gap-1"><LayoutGrid className="h-3.5 w-3.5" />卡片 {viewing.plot_card_count ?? 0}</span>
              </div>
            </div>

            {/* 剧情简介 */}
            {viewing.description && (
              <div className="hh-subpanel p-4">
                <p className="text-xs font-medium text-content-tertiary">剧情简介</p>
                <p className="mt-1.5 whitespace-pre-wrap text-sm leading-7 text-content">{viewing.description}</p>
              </div>
            )}

            {/* 整体进度概览 */}
            {!loadingProgress && viewingProgress?.has_beats && (
              <div className="hh-subpanel p-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold text-content">整体进度</p>
                  <span className="text-lg font-semibold text-brand tabular-nums">{((viewingProgress.total_progress || 0) * 100).toFixed(1)}%</span>
                </div>
                <div className="hh-progress mt-3">
                  <div className="hh-progress-bar" style={{ width: `${Math.max(0, Math.min(100, (viewingProgress.total_progress || 0) * 100))}%` }} />
                </div>
                <p className="mt-2 text-xs text-content-secondary">已关联 {viewingProgress.linked_chapters_count} 个章纲 · 共 {viewingProgress.beats.length} 个节点</p>
              </div>
            )}

            {/* 节点列表 */}
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-content">节点详情</p>
                {loadingProgress && <Loader2 className="h-4 w-4 animate-spin text-content-secondary" />}
              </div>

              {loadingProgress ? (
                <div className="flex items-center justify-center py-8">
                  <div className="flex flex-col items-center gap-2">
                    <Loader2 className="h-6 w-6 animate-spin text-brand" />
                    <span className="text-xs text-content-secondary">加载节点进度中…</span>
                  </div>
                </div>
              ) : viewingProgress?.has_beats ? (
                <div className="grid max-h-[50vh] grid-cols-1 gap-3 overflow-y-auto pr-1">
                  {viewingProgress.beats.map(beat => {
                    const isCompleted = beat.status === 'completed'
                    const isInProgress = beat.status === 'in_progress'
                    const statusText = isCompleted ? '已完成' : isInProgress ? '进行中' : '未开始'
                    const statusTag = isCompleted
                      ? 'bg-emerald-50 text-emerald-600'
                      : isInProgress
                        ? 'bg-amber-50 text-amber-600'
                        : 'bg-surface-hover text-content-secondary'

                    return (
                      <div key={`progress-${beat.index}`} className="hh-subpanel p-4">
                        <div className="flex items-start gap-3">
                          {/* 序号指示器 */}
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center bg-brand/10 text-xs font-semibold text-brand tabular-nums">{beat.index}</span>
                          {/* 内容 */}
                          <div className="min-w-0 flex-1 space-y-2">
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <p className="truncate text-sm font-semibold text-content">{beat.title}</p>
                                {beat.description && <p className="mt-1 line-clamp-3 text-xs leading-5 text-content-secondary">{beat.description}</p>}
                              </div>
                              <span className={cn(STATUS_TAG, 'shrink-0', statusTag)}>{statusText}</span>
                            </div>
                            {/* 进度条 */}
                            <div>
                              <div className="mb-1 flex items-center justify-between text-[11px] text-content-secondary">
                                <span>覆盖度</span>
                                <span className="font-medium tabular-nums">{(beat.coverage * 100).toFixed(0)}%</span>
                              </div>
                              <div className="hh-progress h-1">
                                <div className="hh-progress-bar" style={{ width: `${Math.max(0, Math.min(100, beat.coverage * 100))}%` }} />
                              </div>
                            </div>
                            {/* 底部元信息 */}
                            <div className="flex items-center gap-3 text-[11px] text-content-tertiary">
                              <span>标识 {beat.key || `beat_${beat.index}`}</span>
                              <span>·</span>
                              <span>权重 {(beat.weight * 100).toFixed(0)}%</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center border border-dashed border-surface-border px-6 py-10 text-center">
                  <span className="flex h-12 w-12 items-center justify-center bg-brand/10 text-brand">
                    <GitBranch className="h-6 w-6" />
                  </span>
                  <p className="mt-3 text-sm text-content-secondary">{viewingProgress?.message || '暂无节点数据'}</p>
                  <p className="mt-1 text-xs text-content-tertiary">点击下方「编辑节点」可添加剧情节点</p>
                </div>
              )}
            </div>
          </div>
        </Modal>
      )}
    </section>
  )
}
// ==================== Tab 4: 章纲 ====================
function ChapterOutlinesView({ chapterOutlines, projectId, createChapterOutline, updateChapterOutline, deleteChapterOutline, batchCreateChapterOutlines, plotLines }: {
  chapterOutlines: ChapterOutline[]
  projectId?: string
  createChapterOutline: (data: ChapterOutlineCreate) => Promise<ChapterOutline>
  updateChapterOutline: (id: string, data: ChapterOutlineUpdate) => Promise<ChapterOutline>
  deleteChapterOutline: (id: string) => Promise<void>
  batchCreateChapterOutlines: (data: ChapterOutlineBatchCreateRequest) => Promise<ChapterOutline[]>
  plotLines: PlotLine[]
}) {
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<ChapterOutline | null>(null)
  const [viewingChapterOutline, setViewingChapterOutline] = useState<ChapterOutline | null>(null)
  const [form, setForm] = useState({ chapter_number: 1, title: '', plot_points: '', scene: '', pov: '', target_word_count: 3000 })
  const [showBatchModal, setShowBatchModal] = useState(false)
  const [batchCount, setBatchCount] = useState(5)
  const [batchCreating, setBatchCreating] = useState(false)

  // 关联管理
  const [expandedLinkId, setExpandedLinkId] = useState<string | null>(null)
  const [linkedLines, setLinkedLines] = useState<Record<string, Array<{ id: string; title: string; line_type?: string }>>>({})
  const [loadingLink, setLoadingLink] = useState<string | null>(null)
  const [showLinkModal, setShowLinkModal] = useState<string | null>(null)
  const [selectedLinkIds, setSelectedLinkIds] = useState<string[]>([])
  const [linkSaving, setLinkSaving] = useState(false)

  const toggleLinks = async (coId: string) => {
    if (expandedLinkId === coId) { setExpandedLinkId(null); return }
    setExpandedLinkId(coId)
    if (linkedLines[coId]) return
    setLoadingLink(coId)
    try {
      const lines = await chapterOutlineLinkApi.getPlotLines(coId)
      setLinkedLines(prev => ({ ...prev, [coId]: lines.map(l => ({ id: l.id, title: l.title, line_type: l.line_type })) }))
    } catch { /* ignore failed relation preview */ }
    finally { setLoadingLink(null) }
  }

  const handleUnlink = async (coId: string, lineId: string) => {
    try {
      await chapterOutlineLinkApi.unlinkPlotLines(coId, [lineId])
      setLinkedLines(prev => ({ ...prev, [coId]: (prev[coId] || []).filter(l => l.id !== lineId) }))
      toast.success('已取消关联')
    } catch { toast.error('取消关联失败') }
  }

  const openLinkModal = (coId: string) => {
    setShowLinkModal(coId)
    setSelectedLinkIds([])
  }

  const handleLink = async () => {
    if (!showLinkModal || selectedLinkIds.length === 0) return
    setLinkSaving(true)
    try {
      await chapterOutlineLinkApi.linkPlotLines(showLinkModal, { plot_line_ids: selectedLinkIds })
      const lines = await chapterOutlineLinkApi.getPlotLines(showLinkModal)
      setLinkedLines(prev => ({ ...prev, [showLinkModal!]: lines.map(l => ({ id: l.id, title: l.title, line_type: l.line_type })) }))
      setShowLinkModal(null)
      toast.success('关联成功')
    } catch { toast.error('关联失败') }
    finally { setLinkSaving(false) }
  }

  const sorted = [...chapterOutlines].sort((a, b) => a.chapter_number - b.chapter_number)

  const openCreate = () => {
    setEditing(null)
    const nextNum = sorted.length > 0 ? sorted[sorted.length - 1].chapter_number + 1 : 1
    setForm({ chapter_number: nextNum, title: '', plot_points: '', scene: '', pov: '', target_word_count: 3000 })
    setShowModal(true)
  }
  const openEdit = (co: ChapterOutline) => {
    setEditing(co)
    setForm({ chapter_number: co.chapter_number, title: co.title, plot_points: co.plot_points || '', scene: co.scene || '', pov: co.pov || '', target_word_count: co.target_word_count })
    setShowModal(true)
  }

  const handleSubmit = async () => {
    if (!projectId) return
    if (!form.title.trim()) { toast.error('请填写标题'); return }
    try {
      if (editing) {
        await updateChapterOutline(editing.id, { chapter_number: form.chapter_number, title: form.title, plot_points: form.plot_points || undefined, scene: form.scene || undefined, pov: form.pov || undefined, target_word_count: form.target_word_count })
      } else {
        await createChapterOutline({ project_id: projectId, chapter_number: form.chapter_number, title: form.title, plot_points: form.plot_points || undefined, scene: form.scene || undefined, pov: form.pov || undefined, target_word_count: form.target_word_count })
      }
      setShowModal(false)
    } catch { /* hook 已 toast */ }
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
          <h2 className="text-lg font-semibold tracking-tight text-content">章纲</h2>
          <p className="mt-1 text-sm leading-6 text-content-secondary">
            逐章的剧情要点、场景与视角，是生成正文前的最后一层规划，共 {chapterOutlines.length} 章。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          {chapterOutlines.length > 0 && (
            <button onClick={handleDeleteSelected} disabled={selectedIds.size === 0} className="hh-btn-ghost text-red-500 hover:bg-red-50 hover:text-red-600">
              <Trash2 className="h-4 w-4" />删除{selectedIds.size > 0 ? ` (${selectedIds.size})` : ''}
            </button>
          )}
          <button onClick={() => setShowBatchModal(true)} className="hh-btn-ghost">
            <Plus className="h-4 w-4" />批量创建
          </button>
          <Link to={`/project/${projectId}/plot-bridges`} className="hh-btn-secondary">
            <Sparkles className="h-4 w-4 text-brand" />去桥段规划生成章纲
          </Link>
          <button onClick={openCreate} className="hh-btn-primary">
            <Plus className="h-4 w-4" />新建章纲
          </button>
        </div>
      </div>

      {sorted.length === 0 ? (
        <EmptyBlock
          icon={BookOpen}
          title="还没有章纲"
          hint="章纲由「桥段规划」展开生成（每桥段 4 章，章号由桥段序号决定）；也可点「新建章纲」手动添加或「批量创建」占位。"
        />
      ) : (
        <div className="mt-6 space-y-3">
          <div className="flex items-center gap-2.5 px-1">
            <input type="checkbox" checked={selectedIds.size === chapterOutlines.length && chapterOutlines.length > 0} onChange={toggleSelectAll} className="h-4 w-4" />
            <span className="text-xs text-content-secondary tabular-nums">{selectedIds.size > 0 ? `已选 ${selectedIds.size}/${chapterOutlines.length}` : '全选'}</span>
          </div>
          {sorted.map(co => (
            <article key={co.id} className={cn('hh-subpanel p-4 transition-colors', selectedIds.has(co.id) && 'border-brand/40 bg-brand/[0.04]')}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <input type="checkbox" checked={selectedIds.has(co.id)} onChange={() => toggleSelect(co.id)} className="mt-1 h-4 w-4 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn(STATUS_TAG, 'shrink-0 bg-brand/10 text-brand tabular-nums')}>#{co.chapter_number}</span>
                      <h3 className="min-w-0 max-w-full truncate text-[15px] font-semibold text-content">{co.title}</h3>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-content-tertiary">
                      {co.scene && <span>场景: {co.scene}</span>}
                      {co.pov && <span>视角: {co.pov}</span>}
                      <span>目标字数: {co.target_word_count}</span>
                      {co.plot_line_count != null && <span>关联剧情线: {co.plot_line_count}</span>}
                    </div>
                    {co.plot_points && <p className="mt-1.5 line-clamp-2 text-[13px] leading-6 text-content-secondary">{co.plot_points}</p>}
                    {co.key_events && co.key_events.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {co.key_events.map((ev, i) => (
                          <span key={i} className="bg-surface-hover px-2 py-0.5 text-[11px] text-content-secondary">{ev}</span>
                        ))}
                      </div>
                    )}
                    <button onClick={() => toggleLinks(co.id)} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand hover:text-brand-600">
                      <Link2 className="h-3 w-3" />关联剧情线
                      {expandedLinkId === co.id ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    </button>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button onClick={() => setViewingChapterOutline(co)} className="hh-icon-btn-plain h-8 w-8" title="查看章纲详情"><Eye className="h-3.5 w-3.5" /></button>
                  <button onClick={() => openEdit(co)} className="hh-icon-btn-plain h-8 w-8" title="编辑"><Pencil className="h-3.5 w-3.5" /></button>
                  <button onClick={() => handleDelete(co)} className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="删除"><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              </div>
              {expandedLinkId === co.id && (
                <div className="mt-3 border-t border-surface-border/80 pt-3">
                  {loadingLink === co.id ? (
                    <div className="flex items-center gap-2 text-xs text-content-secondary"><Loader2 className="h-3 w-3 animate-spin" />加载中...</div>
                  ) : (
                    <>
                      {(linkedLines[co.id] || []).length > 0 ? (
                        <div className="mb-2 flex flex-wrap gap-2">
                          {(linkedLines[co.id] || []).map(pl => (
                            <span key={pl.id} className="hh-tag">
                              <GitBranch className="h-3 w-3" />{pl.title}
                              <button onClick={() => handleUnlink(co.id, pl.id)} className="ml-1 text-brand/60 hover:text-red-500" title="取消关联">&times;</button>
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="mb-2 text-xs text-content-tertiary">暂无关联剧情线</p>
                      )}
                      <button onClick={() => openLinkModal(co.id)} className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:text-brand-600">
                        <Plus className="h-3 w-3" />添加关联
                      </button>
                    </>
                  )}
                </div>
              )}
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

      {/* 关联剧情线选择弹窗 */}
      {showLinkModal && (
        <Modal
          title="关联剧情线"
          onClose={() => setShowLinkModal(null)}
          size="lg"
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowLinkModal(null)} className="hh-btn-ghost">取消</button>
              <button onClick={handleLink} disabled={linkSaving || selectedLinkIds.length === 0} className="hh-btn-primary">
                {linkSaving && <Loader2 className="h-4 w-4 animate-spin" />}
                确定关联 ({selectedLinkIds.length})
              </button>
            </>
          )}
        >
          <div className="max-h-60 space-y-1.5 overflow-y-auto">
            {plotLines.length === 0 ? (
              <p className="text-sm text-content-secondary">暂无可选剧情线，请先创建剧情线</p>
            ) : (
              plotLines.map(pl => {
                const alreadyLinked = (linkedLines[showLinkModal] || []).some(l => l.id === pl.id)
                const selected = selectedLinkIds.includes(pl.id)
                return (
                  <label key={pl.id} className={cn(
                    'flex items-center gap-2.5 border px-3 py-2.5 text-sm text-content transition-colors',
                    alreadyLinked ? 'cursor-not-allowed border-transparent bg-surface-hover opacity-50' : selected ? 'cursor-pointer border-brand bg-brand/10' : 'cursor-pointer border-transparent hover:bg-surface-hover'
                  )}>
                    <input
                      type="checkbox"
                      checked={selected || alreadyLinked}
                      disabled={alreadyLinked}
                      onChange={() => {
                        if (alreadyLinked) return
                        setSelectedLinkIds(prev => prev.includes(pl.id) ? prev.filter(id => id !== pl.id) : [...prev, pl.id])
                      }}
                      className="h-4 w-4"
                    />
                    <GitBranch className="h-3.5 w-3.5 shrink-0 text-brand" />
                    <span className="truncate">{pl.title}</span>
                    <span className="shrink-0 text-xs text-content-tertiary">{getPlotLineTypeLabel(pl.line_type)}</span>
                    {alreadyLinked && <span className="ml-auto text-xs text-content-tertiary">已关联</span>}
                  </label>
                )
              })
            )}
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
              <span className={cn(STATUS_TAG, 'bg-brand/10 text-brand tabular-nums')}>#{viewingChapterOutline.chapter_number}</span>
              {viewingChapterOutline.scene && <span>场景：{viewingChapterOutline.scene}</span>}
              {viewingChapterOutline.pov && <span>视角：{viewingChapterOutline.pov}</span>}
              <span>目标字数：{viewingChapterOutline.target_word_count}</span>
              <span>关联剧情线：{viewingChapterOutline.plot_line_count ?? 0}</span>
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
          </div>
        </Modal>
      )}
    </section>
  )
}
// ==================== Tab 5: 关联总览 ====================
function OverviewPanel({ plotCards, plotLines, chapterOutlines }: {
  plotCards: PlotCard[]
  plotLines: PlotLine[]
  chapterOutlines: ChapterOutline[]
}) {
  const totalCardLinks = plotCards.reduce((sum, c) => sum + (c.plot_line_count ?? 0) + (c.chapter_outline_count ?? 0), 0)
  const totalLineLinks = plotLines.reduce((sum, l) => sum + (l.chapter_outline_count ?? 0) + (l.plot_card_count ?? 0), 0)
  const totalRelations = totalCardLinks + totalLineLinks

  const stats = [
    { label: '剧情卡片', value: plotCards.length },
    { label: '剧情线', value: plotLines.length },
    { label: '章纲', value: chapterOutlines.length },
    { label: '关联关系', value: totalRelations },
  ]

  // 简易关联网络图：节点 = 剧情线 + 章纲，用 SVG 绘制
  const sortedCO = [...chapterOutlines].sort((a, b) => a.chapter_number - b.chapter_number)
  const nodeCount = plotLines.length + sortedCO.length
  const svgW = 700, svgH = Math.max(300, nodeCount * 18)
  const lineX = 120, coX = svgW - 120
  const lineNodes = plotLines.map((l, i) => ({
    id: l.id, label: l.title, type: 'line' as const,
    x: lineX, y: 40 + i * (svgH - 80) / Math.max(plotLines.length - 1, 1),
    linkCount: l.chapter_outline_count ?? 0,
  }))
  const coNodes = sortedCO.map((co, i) => ({
    id: co.id, label: `#${co.chapter_number} ${co.title}`, type: 'co' as const,
    x: coX, y: 40 + i * (svgH - 80) / Math.max(sortedCO.length - 1, 1),
    linkCount: co.plot_line_count ?? 0,
  }))

  return (
    <div className="space-y-6">
      <section className="hh-panel grid grid-cols-2 divide-surface-border/80 md:grid-cols-4 md:divide-x">
        {stats.map(s => (
          <div key={s.label} className="px-5 py-4 md:px-6">
            <p className="text-xs text-content-tertiary">{s.label}</p>
            <p className="mt-1 text-2xl font-semibold tracking-tight text-content tabular-nums">{s.value}</p>
          </div>
        ))}
      </section>

      {plotLines.length === 0 && chapterOutlines.length === 0 && (
        <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <BarChart3 className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">还没有可分析的关联</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            先在「剧情线」和「章纲」里创建内容并建立关联，这里会汇总关联网络与章纲覆盖情况。
          </p>
        </section>
      )}

      {/* 关联网络图 */}
      {plotLines.length > 0 && sortedCO.length > 0 && (
        <section className="hh-panel p-6">
          <h3 className="text-lg font-semibold tracking-tight text-content">关联网络图</h3>
          <p className="mt-1 text-sm leading-6 text-content-secondary">左侧为剧情线，右侧为章纲，圆点大小代表关联数量。</p>
          <div className="mt-5 overflow-x-auto">
            <svg width={svgW} height={svgH} className="mx-auto">
              {/* 连线占位：根据关联数量画虚线 */}
              {lineNodes.map(ln => coNodes.filter(cn => cn.linkCount > 0 || ln.linkCount > 0).slice(0, ln.linkCount || 1).map((cn, ci) => (
                <line key={`${ln.id}-${cn.id}-${ci}`} x1={ln.x + 8} y1={ln.y} x2={cn.x - 8} y2={cn.y}
                  stroke="#b9d7ff" strokeWidth={1} strokeDasharray="4,3" opacity={0.8} />
              )))}
              {/* 剧情线节点 */}
              {lineNodes.map(n => (
                <g key={n.id}>
                  <circle cx={n.x} cy={n.y} r={Math.max(6, Math.min(14, 6 + n.linkCount * 2))} fill="#007aff" opacity={0.85} />
                  <text x={n.x - 14} y={n.y + 4} textAnchor="end" fontSize={11} fill="#5f7090" className="select-none">{n.label}</text>
                </g>
              ))}
              {/* 章纲节点 */}
              {coNodes.map(n => (
                <g key={n.id}>
                  <circle cx={n.x} cy={n.y} r={Math.max(6, Math.min(14, 6 + n.linkCount * 2))} fill="#5f7090" opacity={0.85} />
                  <text x={n.x + 14} y={n.y + 4} textAnchor="start" fontSize={11} fill="#5f7090" className="select-none">{n.label}</text>
                </g>
              ))}
              {/* 图例 */}
              <circle cx={20} cy={svgH - 20} r={6} fill="#007aff" />
              <text x={32} y={svgH - 16} fontSize={10} fill="#5f7090">剧情线</text>
              <circle cx={90} cy={svgH - 20} r={6} fill="#5f7090" />
              <text x={102} y={svgH - 16} fontSize={10} fill="#5f7090">章纲</text>
            </svg>
          </div>
        </section>
      )}

      {/* 剧情线概览 */}
      {plotLines.length > 0 && (
        <section className="hh-panel p-6">
          <h3 className="text-lg font-semibold tracking-tight text-content">剧情线分布</h3>
          <div className="mt-4 divide-y divide-surface-border/80">
            {plotLines.map(l => (
              <div key={l.id} className="flex items-center justify-between gap-3 py-3 text-sm">
                <div className="flex min-w-0 items-center gap-2.5">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center bg-brand/10 text-brand">
                    <GitBranch className="h-4 w-4" />
                  </span>
                  <span className="truncate text-content">{l.title}</span>
                  <span className={cn(STATUS_TAG, 'shrink-0', getPlotLineTypeColor(l.line_type))}>{getPlotLineTypeLabel(l.line_type)}</span>
                </div>
                <div className="flex shrink-0 items-center gap-3 text-xs text-content-secondary tabular-nums">
                  <span>卡片 {l.plot_card_count ?? 0}</span>
                  <span>章纲 {l.chapter_outline_count ?? 0}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 章纲覆盖 */}
      {chapterOutlines.length > 0 && (
        <section className="hh-panel p-6">
          <h3 className="text-lg font-semibold tracking-tight text-content">章纲覆盖</h3>
          <p className="mt-1 text-sm leading-6 text-content-secondary">已关联剧情线的章纲会高亮显示。</p>
          <div className="mt-4 flex flex-wrap gap-1.5">
            {sortedCO.map(co => (
              <span key={co.id} className={cn(
                'px-2 py-1 text-xs',
                (co.plot_line_count ?? 0) > 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-surface-hover text-content-secondary'
              )}>
                #{co.chapter_number} {co.title}
                {(co.plot_line_count ?? 0) > 0 && <span className="ml-1 opacity-60">({co.plot_line_count}线)</span>}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
