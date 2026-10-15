import { useMemo, useState } from 'react'
import { BookOpen, Check, ChevronDown, ChevronRight, Layers, Loader2, Pencil, Plus, Sparkles, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { volumeApi } from '@/services/api'
import { useAIJobsStore, useRunningAIJobs } from '@/store/aiJobsStore'
import { AIJobBanner } from '@/components/ai-job/AIJobBanner'
import { Modal } from '@/components/ui/Modal'
import type { SSEClientOptions } from '@/utils/sseClient'
import type { ChapterOutline, Volume, VolumeFields, VolumeJobResult, VolumeUnit, VolumeUnitInput } from '@/types'

/** 与后端 volume_jobs.KIND 一致：分卷 / 细化 / 单元章纲共用一个互斥键 */
const JOB_KIND = 'volume_plan'

interface VolumesViewProps {
  projectId?: string
  chapterCount?: number | null
  volumes: Volume[]
  chapterOutlines: ChapterOutline[]
  refreshVolumes: (projectId: string) => Promise<unknown>
  refreshChapterOutlines: () => Promise<unknown>
  saveVolume: (id: string, data: VolumeFields) => Promise<Volume>
  confirmVolume: (id: string) => Promise<Volume>
  deleteVolume: (id: string) => Promise<void>
  onOpenChapterOutlines: () => void
}

type Prompt =
  | { kind: 'plan' }
  | { kind: 'detail'; volume: Volume }
  | { kind: 'outlines'; volume: Volume; unit: VolumeUnit }

const statusBadge = (v: Volume) => {
  if (v.upstream_stale) return <span className="lj-badge lj-badge--stale" title={v.upstream_reason || '总纲改过'}>上游已改</span>
  if (v.review_status === 'draft') return <span className="lj-badge lj-badge--draft" title="AI 草拟，看过没问题再确认">待确认</span>
  return <span className="lj-badge lj-badge--ok">已确认</span>
}

const errorText = (err: unknown, fallback: string) => {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail || (err instanceof Error ? err.message : fallback)
}

export function VolumesView({
  projectId, chapterCount, volumes, chapterOutlines, refreshVolumes, refreshChapterOutlines,
  saveVolume, confirmVolume, deleteVolume, onOpenChapterOutlines,
}: VolumesViewProps) {
  const startJob = useAIJobsStore((s) => s.start)
  const running = useRunningAIJobs(projectId, [JOB_KIND]).length > 0
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(volumes[0] ? [volumes[0].id] : []))
  const [prompt, setPrompt] = useState<Prompt | null>(null)
  const [instruction, setInstruction] = useState('')
  const [planChapters, setPlanChapters] = useState<number>(chapterCount || 0)
  const [planVolumes, setPlanVolumes] = useState<number | ''>('')
  const [editing, setEditing] = useState<Volume | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const outlinesByChapter = useMemo(() => new Map(chapterOutlines.map((o) => [o.chapter_number, o])), [chapterOutlines])
  const unconfirmed = volumes.filter((v) => v.review_status === 'draft' || v.upstream_stale)

  const toggle = (id: string) => setExpanded((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const unitStats = (unit: VolumeUnit) => {
    let have = 0
    let drafts = 0
    for (let n = unit.chapter_start; n <= unit.chapter_end; n += 1) {
      const outline = outlinesByChapter.get(n)
      if (!outline) continue
      have += 1
      if (outline.review_status === 'draft' || outline.upstream_stale) drafts += 1
    }
    return { have, drafts, total: unit.chapter_end - unit.chapter_start + 1 }
  }

  const runJob = async (title: string, connect: (o: SSEClientOptions<VolumeJobResult>) => Promise<unknown>, done: (r: VolumeJobResult | null) => string) => {
    if (!projectId) return
    try {
      await startJob({
        kind: JOB_KIND,
        title,
        projectId,
        connect: (options) => connect(options as SSEClientOptions<VolumeJobResult>),
        onSettled: (job) => {
          if (job.status !== 'done') return
          void refreshVolumes(projectId)
          void refreshChapterOutlines()
          toast.success(done((job.result as VolumeJobResult | null) ?? null))
        },
      })
    } catch (err) {
      toast.error(errorText(err, '启动失败'))
    }
  }

  const submitPrompt = async () => {
    if (!prompt || !projectId) return
    const text = instruction.trim() || undefined
    setPrompt(null)
    setInstruction('')
    if (prompt.kind === 'plan') {
      await runJob(
        '按总纲分卷',
        (o) => volumeApi.planStream(projectId, {
          total_chapters: planChapters > 0 ? planChapters : undefined,
          volume_count: planVolumes === '' ? undefined : planVolumes,
          instruction: text,
        }, o),
        (r) => `分好了 ${r?.volumes?.length ?? 0} 卷（草稿），看过后点「确认」`,
      )
    } else if (prompt.kind === 'detail') {
      const v = prompt.volume
      setExpanded((prev) => new Set(prev).add(v.id))
      await runJob(
        `细化第${v.volume_number}卷《${v.title}》`,
        (o) => volumeApi.detailStream(v.id, { instruction: text }, o),
        (r) => `第${v.volume_number}卷拆成了 ${r?.volume?.units.length ?? 0} 个剧情单元`,
      )
    } else {
      const { volume: v, unit } = prompt
      await runJob(
        `第${v.volume_number}卷单元 ${unit.index}《${unit.title}》章纲`,
        (o) => volumeApi.unitOutlinesStream(v.id, unit.index, { instruction: text }, o),
        (r) => `生成了 ${r?.chapter_numbers?.length ?? 0} 章章纲，去「章纲」确认后就能写正文`,
      )
    }
  }

  const withBusy = async (key: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(key)
    try {
      await fn()
      if (ok) toast.success(ok)
    } catch (err) {
      toast.error(errorText(err, '操作失败'))
    } finally {
      setBusy(null)
    }
  }

  const confirmAll = () => withBusy('all', async () => {
    if (!projectId) return
    const { confirmed } = await volumeApi.confirmAll(projectId)
    await refreshVolumes(projectId)
    toast.success(`已确认 ${confirmed} 卷`)
  })

  const createVolume = () => withBusy('create', async () => {
    if (!projectId) return
    const created = await volumeApi.create(projectId, {})
    await refreshVolumes(projectId)
    setEditing(created)
  })

  const removeVolume = (v: Volume) => {
    if (!confirm(`确定删除第${v.volume_number}卷《${v.title}》？`)) return
    void withBusy(`del-${v.id}`, () => deleteVolume(v.id), '已删除')
  }

  return (
    <section className="hh-panel space-y-4 p-6">
      <AIJobBanner projectId={projectId} kinds={[JOB_KIND]} />
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-tight text-content">卷纲</h2>
          <p className="mt-1 max-w-[640px] text-sm leading-6 text-content-secondary">
            把总纲扩写成卷：每卷是一个新的局面，细化为几件完整的事（剧情单元）和要推进的线索；再把剧情单元展开成章纲。
            AI 草拟的内容都要看过再确认，共 {volumes.length} 卷。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          {unconfirmed.length > 0 && (
            <button onClick={() => void confirmAll()} disabled={busy !== null} className="hh-btn-secondary">
              {busy === 'all' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}全部确认 ({unconfirmed.length})
            </button>
          )}
          <button onClick={() => void createVolume()} disabled={busy !== null} className="hh-btn-ghost">
            <Plus className="h-4 w-4" />新建一卷
          </button>
          <button onClick={() => { setPlanChapters(chapterCount || 0); setPrompt({ kind: 'plan' }) }} disabled={running} className="hh-btn-primary">
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {volumes.length > 0 ? '重新分卷' : '按总纲分卷'}
          </button>
        </div>
      </div>

      {volumes.length === 0 ? (
        <div className="mt-6 flex flex-col items-center px-6 py-12 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand"><Layers className="h-7 w-7" /></span>
          <h3 className="mt-5 text-xl font-semibold tracking-tight text-content">还没有卷纲</h3>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            先在「总纲」里写好梗概和全书主线，再点「按总纲分卷」；也可以在智能助笔里对主编说「帮我分卷」。
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {volumes.map((v) => {
            const open = expanded.has(v.id)
            return (
              <article key={v.id} className="hh-subpanel p-4">
                <div className="flex items-start justify-between gap-3">
                  <button onClick={() => toggle(v.id)} className="flex min-w-0 flex-1 items-start gap-2 text-left">
                    {open ? <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-content-tertiary" /> : <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-content-tertiary" />}
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="shrink-0 bg-brand-100 px-2 py-0.5 text-[11px] font-medium text-brand-600">第{v.volume_number}卷</span>
                        <h3 className="min-w-0 truncate text-[15px] font-semibold text-content">{v.title || '未命名'}</h3>
                        {statusBadge(v)}
                        <span className="text-xs text-content-tertiary tabular-nums">第 {v.chapter_start}-{v.chapter_end} 章 · 剧情单元 {v.units.length} · 章纲 {v.outline_count}</span>
                      </div>
                      {v.goal && <p className="mt-1 line-clamp-1 text-[13px] text-content-secondary">{v.goal}</p>}
                    </div>
                  </button>
                  <div className="flex shrink-0 items-center gap-1">
                    {(v.review_status === 'draft' || v.upstream_stale) && (
                      <button onClick={() => void withBusy(`c-${v.id}`, () => confirmVolume(v.id), '已确认')} disabled={busy !== null} className="hh-btn-secondary hh-btn-sm h-8">
                        {busy === `c-${v.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}确认
                      </button>
                    )}
                    {v.outline_count === 0 && (
                      <button onClick={() => setPrompt({ kind: 'detail', volume: v })} disabled={running} className="hh-btn-ghost hh-btn-sm h-8" title="把本卷拆成剧情单元与线索">
                        <Sparkles className="h-3.5 w-3.5 text-brand" />{v.units.length > 0 ? '重新细化' : '细化剧情单元'}
                      </button>
                    )}
                    <button onClick={() => setEditing(v)} className="hh-icon-btn-plain h-8 w-8" title="编辑"><Pencil className="h-3.5 w-3.5" /></button>
                    <button onClick={() => removeVolume(v)} disabled={v.outline_count > 0} className="hh-icon-btn-plain h-8 w-8 hover:text-cinnabar disabled:opacity-40" title={v.outline_count > 0 ? '本卷已有章纲，先删章纲' : '删除'}><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>

                {open && (
                  <div className="mt-3 space-y-3 border-t border-surface-border/80 pt-3 text-[13px] leading-6">
                    {v.upstream_stale && v.upstream_reason && <p className="text-[12px] text-cinnabar">{v.upstream_reason}</p>}
                    {v.summary && <p className="whitespace-pre-wrap text-content">{v.summary}</p>}
                    <div className="grid gap-2 sm:grid-cols-2">
                      {v.climax && <p className="text-content-secondary"><span className="font-medium text-content">卷末高潮：</span>{v.climax}</p>}
                      {v.ending_hook && <p className="text-content-secondary"><span className="font-medium text-content">卷末钩子：</span>{v.ending_hook}</p>}
                    </div>
                    {v.threads.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-content-tertiary">线索编排</p>
                        <ul className="mt-1 space-y-0.5">
                          {v.threads.map((t, i) => <li key={i} className="text-content-secondary">· {t}</li>)}
                        </ul>
                      </div>
                    )}
                    {v.review_note && <p className="bg-brand/5 px-3 py-2 text-content-secondary"><span className="font-medium text-content">上一卷复盘：</span>{v.review_note}</p>}

                    <div>
                      <p className="text-xs font-medium text-content-tertiary">剧情单元</p>
                      {v.units.length === 0 ? (
                        <p className="mt-1 text-content-tertiary">还没细化。点右上角「细化剧情单元」，AI 会按事件大小把本卷拆成几件完整的事。</p>
                      ) : (
                        <div className="mt-2 space-y-2">
                          {v.units.map((u) => {
                            const stats = unitStats(u)
                            const missing = stats.total - stats.have
                            return (
                              <div key={u.index} className="border border-surface-border/80 bg-white/60 p-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                                    <span className="text-xs font-medium text-brand">单元 {u.index}</span>
                                    <span className="font-medium text-content">{u.title}</span>
                                    <span className="text-xs text-content-tertiary tabular-nums">第 {u.chapter_start}-{u.chapter_end} 章（{stats.total} 章）</span>
                                    <span className={cn('text-xs tabular-nums', stats.have === stats.total ? 'text-emerald-600' : 'text-content-tertiary')}>
                                      章纲 {stats.have}/{stats.total}{stats.drafts > 0 ? ` · 待确认 ${stats.drafts}` : ''}
                                    </span>
                                  </div>
                                  <div className="flex items-center gap-1.5">
                                    {missing > 0 && (
                                      <button onClick={() => setPrompt({ kind: 'outlines', volume: v, unit: u })} disabled={running} className="hh-btn-secondary hh-btn-sm h-7">
                                        <Sparkles className="h-3.5 w-3.5 text-brand" />{stats.have > 0 ? `补齐 ${missing} 章章纲` : '生成章纲'}
                                      </button>
                                    )}
                                    {stats.have > 0 && (
                                      <button onClick={onOpenChapterOutlines} className="hh-btn-ghost hh-btn-sm h-7">
                                        <BookOpen className="h-3.5 w-3.5" />看章纲
                                      </button>
                                    )}
                                  </div>
                                </div>
                                {u.story && <p className="mt-1.5 whitespace-pre-wrap text-content-secondary">{u.story}</p>}
                                {u.turn && <p className="mt-1 text-xs text-content-tertiary">结束时：{u.turn}</p>}
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}

      {prompt && (
        <Modal
          title={prompt.kind === 'plan' ? '按总纲分卷' : prompt.kind === 'detail' ? `细化第${prompt.volume.volume_number}卷` : `生成单元 ${prompt.unit.index}《${prompt.unit.title}》的章纲`}
          onClose={() => setPrompt(null)}
          size="lg"
          footer={(
            <>
              <button onClick={() => setPrompt(null)} className="hh-btn-ghost">取消</button>
              <button onClick={() => void submitPrompt()} className="hh-btn-primary"><Sparkles className="h-4 w-4" />开始</button>
            </>
          )}
        >
          <div className="space-y-4">
            {prompt.kind === 'plan' && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="hh-label">全书章数</label>
                    <input type="number" min={1} value={planChapters || ''} onChange={(e) => setPlanChapters(Number(e.target.value) || 0)} className="hh-field" />
                  </div>
                  <div>
                    <label className="hh-label">卷数（可空，按篇幅估算）</label>
                    <input type="number" min={1} value={planVolumes} onChange={(e) => setPlanVolumes(e.target.value ? Number(e.target.value) : '')} className="hh-field" />
                  </div>
                </div>
                {volumes.length > 0 && (
                  <p className="text-xs leading-5 text-content-tertiary">已有章纲的卷会保留，其后的卷会按总纲重新规划（没有章纲的旧卷会被替换）。</p>
                )}
              </>
            )}
            {prompt.kind === 'outlines' && (
              <p className="text-xs leading-5 text-content-tertiary">
                只补这件事里还没有章纲的章；超过 10 章会分段生成，后一段接着前一段的结尾写。生成的章纲是草稿，确认后再写正文。
              </p>
            )}
            <div>
              <label className="hh-label">你的要求（可空）</label>
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                rows={4}
                placeholder={prompt.kind === 'plan' ? '例如：前两卷在小镇，第三卷进京；感情线在第二卷确立' : '例如：这件事里让女主先误会男主，结尾再和解'}
                className="hh-textarea"
              />
            </div>
          </div>
        </Modal>
      )}

      {editing && (
        <VolumeEditModal
          volume={editing}
          onClose={() => setEditing(null)}
          onSave={async (data) => {
            await saveVolume(editing.id, data)
            toast.success('卷纲已保存（本卷章纲会提示上游已改）')
            setEditing(null)
          }}
        />
      )}
    </section>
  )
}

function VolumeEditModal({ volume, onClose, onSave }: {
  volume: Volume
  onClose: () => void
  onSave: (data: VolumeFields) => Promise<void>
}) {
  const [form, setForm] = useState({
    title: volume.title, chapter_start: volume.chapter_start, chapter_end: volume.chapter_end, goal: volume.goal,
    summary: volume.summary, climax: volume.climax, ending_hook: volume.ending_hook, threads: volume.threads.join('\n'),
  })
  const [units, setUnits] = useState<VolumeUnitInput[]>(volume.units.map(({ title, chapter_start, chapter_end, story, turn }) => ({ title, chapter_start, chapter_end, story, turn })))
  const [saving, setSaving] = useState(false)

  const setUnit = (i: number, patch: Partial<VolumeUnitInput>) => setUnits((prev) => prev.map((u, k) => (k === i ? { ...u, ...patch } : u)))

  const submit = async () => {
    if (form.chapter_end < form.chapter_start) { toast.error('结束章号不能小于起始章号'); return }
    setSaving(true)
    try {
      await onSave({
        ...form,
        threads: form.threads.split('\n').map((t) => t.trim()).filter(Boolean),
        units: units.filter((u) => u.title.trim()),
      })
    } catch (err) {
      toast.error(errorText(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`编辑第${volume.volume_number}卷`}
      onClose={onClose}
      size="2xl"
      closeOnMaskClick={false}
      footer={(
        <>
          <button onClick={onClose} className="hh-btn-ghost">取消</button>
          <button onClick={() => void submit()} disabled={saving} className="hh-btn-primary">{saving && <Loader2 className="h-4 w-4 animate-spin" />}保存</button>
        </>
      )}
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_110px_110px]">
          <div>
            <label className="hh-label">卷名</label>
            <input value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} className="hh-field" />
          </div>
          <div>
            <label className="hh-label">起始章</label>
            <input type="number" min={1} value={form.chapter_start} onChange={(e) => setForm((f) => ({ ...f, chapter_start: Number(e.target.value) || 1 }))} className="hh-field" />
          </div>
          <div>
            <label className="hh-label">结束章</label>
            <input type="number" min={1} value={form.chapter_end} onChange={(e) => setForm((f) => ({ ...f, chapter_end: Number(e.target.value) || 1 }))} className="hh-field" />
          </div>
        </div>
        <div>
          <label className="hh-label">目标与核心冲突</label>
          <textarea value={form.goal} onChange={(e) => setForm((f) => ({ ...f, goal: e.target.value }))} rows={2} className="hh-textarea" />
        </div>
        <div>
          <label className="hh-label">本卷故事</label>
          <textarea value={form.summary} onChange={(e) => setForm((f) => ({ ...f, summary: e.target.value }))} rows={5} placeholder="谁在什么处境下做了什么、别人怎样回应、结果如何、怎样引出下一卷" className="hh-textarea" />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="hh-label">卷末高潮</label>
            <textarea value={form.climax} onChange={(e) => setForm((f) => ({ ...f, climax: e.target.value }))} rows={2} className="hh-textarea" />
          </div>
          <div>
            <label className="hh-label">卷末钩子</label>
            <textarea value={form.ending_hook} onChange={(e) => setForm((f) => ({ ...f, ending_hook: e.target.value }))} rows={2} className="hh-textarea" />
          </div>
        </div>
        <div>
          <label className="hh-label">线索编排（一行一条）</label>
          <textarea value={form.threads} onChange={(e) => setForm((f) => ({ ...f, threads: e.target.value }))} rows={3} placeholder="感情线：本卷从相识推进到互相信任" className="hh-textarea" />
        </div>
        <div>
          <div className="flex items-center justify-between">
            <label className="hh-label">剧情单元（章号会自动校正为连续覆盖本卷）</label>
            <button
              onClick={() => setUnits((prev) => [...prev, { title: '', chapter_start: form.chapter_end, chapter_end: form.chapter_end, story: '', turn: '' }])}
              className="hh-btn-ghost hh-btn-sm"
            >
              <Plus className="h-3.5 w-3.5" />加一个
            </button>
          </div>
          <div className="mt-2 space-y-2">
            {units.map((u, i) => (
              <div key={i} className="space-y-2 border border-surface-border/80 p-3">
                <div className="grid gap-2 sm:grid-cols-[1fr_90px_90px_32px]">
                  <input value={u.title} onChange={(e) => setUnit(i, { title: e.target.value })} placeholder={`单元 ${i + 1} 标题`} className="hh-field" />
                  <input type="number" min={1} value={u.chapter_start} onChange={(e) => setUnit(i, { chapter_start: Number(e.target.value) || 1 })} className="hh-field" />
                  <input type="number" min={1} value={u.chapter_end} onChange={(e) => setUnit(i, { chapter_end: Number(e.target.value) || 1 })} className="hh-field" />
                  <button onClick={() => setUnits((prev) => prev.filter((_, k) => k !== i))} className="hh-icon-btn-plain h-9 w-8 hover:text-cinnabar" title="删除"><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
                <textarea value={u.story} onChange={(e) => setUnit(i, { story: e.target.value })} rows={2} placeholder="这件事的经过：起因 → 经过（阻碍、选择、代价）→ 结果" className="hh-textarea" />
                <input value={u.turn} onChange={(e) => setUnit(i, { turn: e.target.value })} placeholder="结束时局面怎样变化" className="hh-field" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  )
}
