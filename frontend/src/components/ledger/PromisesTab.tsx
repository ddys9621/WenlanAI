/**
 * 伏笔 / 承诺：未回收清单（超期 / 临近 / 掉线排前面）、已回收、已放弃。
 * 作者可改标题 / 内容 / 类型 / 优先级 / 计划回收章、手动标回收、放弃、重新打开、登记新伏笔、把重复的并成一条。
 * 改过的字段重新分析不覆盖；写正文时注入的就是这张清单（章纲点名的排最前）。
 */
import { useCallback, useEffect, useState } from 'react'
import { Check, GitMerge, Loader2, Pencil, Plus, RotateCcw, Search, X } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { ledgerApi } from '@/services/api'
import { Pill } from '@/components/ui/Pill'
import type { LedgerPromise, PromiseCreate, PromisePriority, PromiseType, PromiseUpdate } from '@/types/ledger'
import { PRIORITY_LABELS, PRIORITY_TONE, PROMISE_TYPE_LABELS, STATUS_TONE, lockedSummary } from '@/utils/ledger'

type Filter = 'active' | 'resolved' | 'abandoned' | 'all'
const FILTERS: [Filter, string][] = [['active', '未回收'], ['resolved', '已回收'], ['abandoned', '已放弃'], ['all', '全部']]
const TYPES = Object.keys(PROMISE_TYPE_LABELS) as PromiseType[]
const PRIORITIES = Object.keys(PRIORITY_LABELS) as PromisePriority[]

interface EditState {
  title: string
  content: string
  promise_type: PromiseType
  priority: PromisePriority
  deadline_chapter: string
}

export function PromisesTab({ projectId, latestChapter, onChanged }: { projectId: string; latestChapter: number; onChanged: () => void }) {
  const [filter, setFilter] = useState<Filter>('active')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<LedgerPromise[]>([])
  const [loading, setLoading] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [edit, setEdit] = useState<EditState | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [mergeKeep, setMergeKeep] = useState<string | null>(null)
  const [mergePick, setMergePick] = useState<Set<string>>(new Set())
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState<PromiseCreate>({
    title: '', content: '', promise_type: 'foreshadow', priority: 'medium', source_chapter_number: Math.max(1, latestChapter),
  })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await ledgerApi.promises(projectId, filter, query.trim())
      setItems(res.items)
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [projectId, filter, query])

  useEffect(() => { void load() }, [filter]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (id: string, data: PromiseUpdate, done: string) => {
    setBusyId(id)
    try {
      await ledgerApi.updatePromise(projectId, id, data)
      toast.success(done)
      setEditingId(null)
      await load()
      onChanged()
    } catch {
      /* 全局已 toast */
    } finally {
      setBusyId(null)
    }
  }

  const startEdit = (p: LedgerPromise) => {
    setEditingId(p.id)
    setEdit({ title: p.title, content: p.content, promise_type: p.promise_type, priority: p.priority, deadline_chapter: p.deadline_chapter ? String(p.deadline_chapter) : '' })
  }

  const submitEdit = (p: LedgerPromise) => {
    if (!edit) return
    const data: PromiseUpdate = {}
    if (edit.title.trim() !== p.title) data.title = edit.title.trim()
    if (edit.content.trim() !== p.content) data.content = edit.content.trim()
    if (edit.promise_type !== p.promise_type) data.promise_type = edit.promise_type
    if (edit.priority !== p.priority) data.priority = edit.priority
    const deadline = edit.deadline_chapter.trim() ? Number(edit.deadline_chapter) : 0
    if ((p.deadline_chapter ?? 0) !== deadline) data.deadline_chapter = deadline
    if (Object.keys(data).length === 0) { setEditingId(null); return }
    void save(p.id, data, '已保存，之后重新分析不会覆盖这些修改')
  }

  const resolve = (p: LedgerPromise) => {
    const raw = window.prompt(`「${p.title}」在第几章回收？`, String(Math.max(p.source_chapter_number, latestChapter)))
    if (!raw) return
    const chapter = Number(raw)
    if (!Number.isInteger(chapter) || chapter < p.source_chapter_number) { toast.error('回收章应是不早于埋设章的整数'); return }
    const note = window.prompt('怎么回收的？（可留空）', '') ?? ''
    void save(p.id, { status: 'resolved', resolved_chapter_number: chapter, note: note || undefined }, '已标为回收')
  }

  const doMerge = async () => {
    if (!mergeKeep || mergePick.size === 0) return
    setBusyId(mergeKeep)
    try {
      const res = await ledgerApi.mergePromises(projectId, mergeKeep, [...mergePick])
      toast.success(`已并入 ${res.merged} 条`)
      setMergeKeep(null)
      setMergePick(new Set())
      await load()
      onChanged()
    } catch {
      /* 全局已 toast */
    } finally {
      setBusyId(null)
    }
  }

  const create = async () => {
    if (!draft.title.trim()) { toast.error('请填写标题'); return }
    try {
      await ledgerApi.createPromise(projectId, { ...draft, title: draft.title.trim(), content: draft.content?.trim() || undefined })
      toast.success('已登记')
      setCreating(false)
      setDraft((d) => ({ ...d, title: '', content: '' }))
      await load()
      onChanged()
    } catch {
      /* 全局已 toast */
    }
  }

  return (
    <section className="hh-panel p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="inline-flex border border-surface-border bg-white/60 p-0.5">
          {FILTERS.map(([key, label]) => (
            <button key={key} onClick={() => setFilter(key)} className={cn('px-3 py-1 text-xs font-medium', filter === key ? 'bg-brand text-white' : 'text-content-secondary hover:text-content')}>
              {label}
            </button>
          ))}
        </div>
        <div className="relative min-w-[180px] flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void load()} placeholder="按标题 / 内容找（回车）" className="h-8 w-full pl-7 text-xs" />
        </div>
        <button onClick={() => setCreating((v) => !v)} className="hh-btn-secondary hh-btn-sm"><Plus className="h-3.5 w-3.5" />登记伏笔</button>
      </div>

      {creating && (
        <div className="hh-subpanel mb-3 grid gap-2 p-3 sm:grid-cols-2">
          <input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="标题（30 字内）" maxLength={200} className="h-8 text-xs sm:col-span-2" />
          <textarea value={draft.content} onChange={(e) => setDraft({ ...draft, content: e.target.value })} placeholder="内容：埋了什么、打算怎么收" rows={2} className="text-xs sm:col-span-2" />
          <label className="flex items-center gap-2 text-xs text-content-secondary">类型
            <select value={draft.promise_type} onChange={(e) => setDraft({ ...draft, promise_type: e.target.value as PromiseType })} className="h-8 flex-1 text-xs">
              {TYPES.map((t) => <option key={t} value={t}>{PROMISE_TYPE_LABELS[t]}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-content-secondary">优先级
            <select value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value as PromisePriority })} className="h-8 flex-1 text-xs">
              {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_LABELS[p]}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-content-secondary">埋于第
            <input type="number" min={1} value={draft.source_chapter_number} onChange={(e) => setDraft({ ...draft, source_chapter_number: Number(e.target.value) })} className="h-8 w-20 text-xs" />章
          </label>
          <label className="flex items-center gap-2 text-xs text-content-secondary">计划第
            <input type="number" min={1} value={draft.deadline_chapter ?? ''} onChange={(e) => setDraft({ ...draft, deadline_chapter: e.target.value ? Number(e.target.value) : null })} className="h-8 w-20 text-xs" />章前回收
          </label>
          <div className="flex justify-end gap-2 sm:col-span-2">
            <button onClick={() => setCreating(false)} className="hh-btn-ghost hh-btn-sm">取消</button>
            <button onClick={() => void create()} className="hh-btn-primary hh-btn-sm">登记</button>
          </div>
        </div>
      )}

      {mergeKeep && (
        <div className="mb-3 flex flex-wrap items-center gap-2 border border-brand/30 bg-brand/[0.05] px-3 py-2 text-xs">
          <GitMerge className="h-3.5 w-3.5 text-brand" />
          <span>勾选要并进「{items.find((i) => i.id === mergeKeep)?.title}」的重复条目（章纲里对它们的引用会改指过来）</span>
          <span className="ml-auto flex gap-2">
            <button onClick={() => { setMergeKeep(null); setMergePick(new Set()) }} className="hh-btn-ghost hh-btn-sm">取消</button>
            <button onClick={() => void doMerge()} disabled={mergePick.size === 0} className="hh-btn-primary hh-btn-sm">并入 {mergePick.size} 条</button>
          </span>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>
      ) : items.length === 0 ? (
        <p className="py-10 text-center text-xs text-content-tertiary">{filter === 'active' ? '没有未回收的伏笔' : '这里还没有内容'}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((p) => {
            const isEditing = editingId === p.id && edit
            const locked = lockedSummary(p)
            const busy = busyId === p.id
            const pickable = mergeKeep && mergeKeep !== p.id
            return (
              <li key={p.id} className={cn('hh-subpanel border-l-[3px] p-3', p.flag.includes('超期') ? 'border-l-red-400' : p.flag ? 'border-l-amber-400' : 'border-l-brand/40')}>
                <div className="flex items-start gap-2">
                  {pickable && (
                    <input type="checkbox" className="mt-1" checked={mergePick.has(p.id)} aria-label="并入"
                      onChange={(e) => setMergePick((s) => { const next = new Set(s); if (e.target.checked) next.add(p.id); else next.delete(p.id); return next })} />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-1">
                      <Pill tone="purple">{PROMISE_TYPE_LABELS[p.promise_type] ?? p.promise_type}</Pill>
                      <Pill tone={STATUS_TONE[p.status] ?? 'default'}>{p.status_label}</Pill>
                      <Pill tone={PRIORITY_TONE[p.priority] ?? 'default'}>优先级 {PRIORITY_LABELS[p.priority] ?? p.priority}</Pill>
                      {p.flag && <Pill tone={p.flag.includes('超期') ? 'red' : 'gold'}>{p.flag.replace(/^⚠️/, '').trim()}</Pill>}
                      {locked && <Pill tone="brand">{locked}</Pill>}
                    </div>
                    {isEditing ? (
                      <div className="grid gap-2 sm:grid-cols-2">
                        <input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} maxLength={200} className="h-8 text-xs sm:col-span-2" />
                        <textarea value={edit.content} onChange={(e) => setEdit({ ...edit, content: e.target.value })} rows={2} className="text-xs sm:col-span-2" />
                        <select value={edit.promise_type} onChange={(e) => setEdit({ ...edit, promise_type: e.target.value as PromiseType })} className="h-8 text-xs">
                          {TYPES.map((t) => <option key={t} value={t}>{PROMISE_TYPE_LABELS[t]}</option>)}
                        </select>
                        <select value={edit.priority} onChange={(e) => setEdit({ ...edit, priority: e.target.value as PromisePriority })} className="h-8 text-xs">
                          {PRIORITIES.map((pr) => <option key={pr} value={pr}>优先级 {PRIORITY_LABELS[pr]}</option>)}
                        </select>
                        <label className="flex items-center gap-2 text-xs text-content-secondary sm:col-span-2">计划第
                          <input type="number" min={1} value={edit.deadline_chapter} onChange={(e) => setEdit({ ...edit, deadline_chapter: e.target.value })} placeholder="不定" className="h-8 w-20 text-xs" />章前回收（留空 = 不设）
                        </label>
                        <div className="flex justify-end gap-2 sm:col-span-2">
                          <button onClick={() => setEditingId(null)} className="hh-btn-ghost hh-btn-sm"><X className="h-3.5 w-3.5" />取消</button>
                          <button onClick={() => submitEdit(p)} disabled={busy || !edit.title.trim()} className="hh-btn-primary hh-btn-sm"><Check className="h-3.5 w-3.5" />保存</button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <p className="text-[13px] font-semibold text-content">{p.title}</p>
                        {p.content && p.content !== p.title && <p className="mt-0.5 text-xs leading-5 text-content-secondary">{p.content}</p>}
                        <p className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-content-tertiary">
                          <span>第{p.source_chapter_number}章埋下</span>
                          {p.deadline_chapter && <span>计划第{p.deadline_chapter}章前回收</span>}
                          {p.last_activated_chapter && p.last_activated_chapter !== p.source_chapter_number && <span>最近第{p.last_activated_chapter}章提起</span>}
                          {p.resolved_chapter_number && <span>第{p.resolved_chapter_number}章回收{p.resolution_note ? `：${p.resolution_note}` : ''}</span>}
                          {p.owner_name && <span>发起：{p.owner_name}</span>}
                          {p.target_name && <span>对象：{p.target_name}</span>}
                        </p>
                        {p.evidence && <p className="mt-1 text-[11px] text-content-tertiary">原文：「{p.evidence}」</p>}
                      </>
                    )}
                  </div>
                  {!isEditing && !mergeKeep && (
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <div className="flex gap-0.5">
                        <button onClick={() => startEdit(p)} className="hh-icon-btn-plain h-7 w-7 hover:text-brand" title="修改" aria-label="修改"><Pencil className="h-3.5 w-3.5" /></button>
                        <button onClick={() => { setMergeKeep(p.id); setMergePick(new Set()) }} className="hh-icon-btn-plain h-7 w-7 hover:text-brand" title="把重复的并进这一条" aria-label="合并"><GitMerge className="h-3.5 w-3.5" /></button>
                      </div>
                      {['open', 'progressing', 'broken'].includes(p.status) ? (
                        <div className="flex gap-1">
                          <button onClick={() => resolve(p)} disabled={busy} className="hh-btn-ghost hh-btn-sm text-emerald-600">标回收</button>
                          <button onClick={() => void save(p.id, { status: 'abandoned' }, '已放弃追踪')} disabled={busy} className="hh-btn-ghost hh-btn-sm">放弃</button>
                        </div>
                      ) : (
                        <button onClick={() => void save(p.id, { status: 'open' }, '已重新打开')} disabled={busy} className="hh-btn-ghost hh-btn-sm"><RotateCcw className="h-3.5 w-3.5" />重新打开</button>
                      )}
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
