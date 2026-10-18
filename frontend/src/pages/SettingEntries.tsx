import { useEffect, useState, useCallback } from 'react'
import { Plus, Pencil, Trash2, Languages, Gavel, Flag, ScrollText, Shapes, Loader2, type LucideIcon } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { settingEntriesApi } from '@/services/api'
import { emitAssistantData, ASSISTANT_DATA_EVENT, type AssistantDataChange } from '@/store/assistantStore'
import { Modal } from '@/components/ui/Modal'
import type { SettingEntry, SettingEntryCreate, SettingEntryUpdate } from '@/types'

const CATEGORIES: { value: string; label: string; icon: LucideIcon }[] = [
  { value: 'term', label: '术语', icon: Languages },
  { value: 'law', label: '铁律', icon: Gavel },
  { value: 'faction', label: '势力', icon: Flag },
  { value: 'rule', label: '规则', icon: ScrollText },
  { value: 'other', label: '其他', icon: Shapes },
]

const categoryLabel = (cat: string) => CATEGORIES.find(c => c.value === cat)?.label || cat
const categoryIcon = (cat: string) => CATEGORIES.find(c => c.value === cat)?.icon || Shapes

const emptyForm: SettingEntryCreate = { category: 'term', title: '', summary: '', content: '', order_index: 0 }

export default function SettingEntries() {
  const { currentProject } = useStore()
  const [entries, setEntries] = useState<SettingEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [activeCategory, setActiveCategory] = useState<string>('all')
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<SettingEntry | null>(null)
  const [form, setForm] = useState<SettingEntryCreate>(emptyForm)

  const fetchEntries = useCallback(async () => {
    if (!currentProject?.id) return
    try {
      setLoading(true)
      const res = await settingEntriesApi.list(currentProject.id)
      setEntries(res.items)
    } catch {
      // api 层已 toast
    } finally {
      setLoading(false)
    }
  }, [currentProject?.id])

  useEffect(() => { fetchEntries() }, [fetchEntries])

  // 智能助笔「新建设定条目」应用后，这里自动刷新
  useEffect(() => {
    const handler = (e: Event) => {
      const change = (e as CustomEvent<AssistantDataChange>).detail
      if (change?.entity === 'setting_entry') void fetchEntries()
    }
    window.addEventListener(ASSISTANT_DATA_EVENT, handler)
    return () => window.removeEventListener(ASSISTANT_DATA_EVENT, handler)
  }, [fetchEntries])

  const openCreate = () => {
    setEditing(null)
    setForm({ ...emptyForm, category: activeCategory === 'all' ? 'term' : activeCategory, order_index: entries.length })
    setShowModal(true)
  }

  const openEdit = (entry: SettingEntry) => {
    setEditing(entry)
    setForm({ category: entry.category, title: entry.title, summary: entry.summary || '', content: entry.content || '', order_index: entry.order_index })
    setShowModal(true)
  }

  const handleSubmit = async () => {
    if (!currentProject?.id) return
    if (!form.title.trim()) {
      toast.error('请填写条目名称')
      return
    }
    try {
      if (editing) {
        const data: SettingEntryUpdate = { ...form }
        const updated = await settingEntriesApi.update(editing.id, data)
        setEntries(prev => prev.map(x => x.id === updated.id ? updated : x))
        toast.success('设定条目已更新')
      } else {
        const created = await settingEntriesApi.create(currentProject.id, form)
        setEntries(prev => [...prev, created])
        toast.success('设定条目已创建')
      }
      setShowModal(false)
      emitAssistantData({ entity: 'setting_entry' })
    } catch {
      // api 层已 toast
    }
  }

  const handleDelete = async (entry: SettingEntry) => {
    if (!confirm(`确定删除「${entry.title}」？`)) return
    try {
      await settingEntriesApi.delete(entry.id)
      setEntries(prev => prev.filter(x => x.id !== entry.id))
      toast.success('设定条目已删除')
    } catch {
      // api 层已 toast
    }
  }

  const filtered = activeCategory === 'all' ? entries : entries.filter(x => x.category === activeCategory)

  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">世界设定条目</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            把术语、铁律、势力、通用规则等世界观分条整理，每条独立容量；AI 写作与生成角色时会语义检索相关条目带上，不必再塞进「世界设定」的世界规则一栏。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={openCreate} className="hh-btn-primary">
            <Plus className="h-4 w-4" />
            添加条目
          </button>
        </div>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setActiveCategory('all')} className={cn('hh-chip', activeCategory === 'all' && 'hh-chip--active')}>
            全部
          </button>
          {CATEGORIES.map(cat => (
            <button key={cat.value} onClick={() => setActiveCategory(cat.value)} className={cn('hh-chip', activeCategory === cat.value && 'hh-chip--active')}>
              <cat.icon className="h-3.5 w-3.5" />
              {cat.label}
            </button>
          ))}
        </div>
        {!loading && <span className="text-xs text-content-tertiary tabular-nums">{filtered.length} 条</span>}
      </div>

      {loading ? (
        <section className="hh-panel flex items-center justify-center py-14">
          <Loader2 className="h-6 w-6 animate-spin text-brand" />
        </section>
      ) : filtered.length === 0 ? (
        <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <Shapes className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">
            {activeCategory === 'all' ? '还没有设定条目' : `暂无「${categoryLabel(activeCategory)}」条目`}
          </h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            点击右上角「添加条目」录入设定，也可以让共创室的世界观设定师用「新建设定条目」帮你整理。
          </p>
        </section>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map(entry => {
            const Icon = categoryIcon(entry.category)
            return (
              <article key={entry.id} className="hh-panel flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-brand/10 text-brand">
                      <Icon className="h-5 w-5" />
                    </span>
                    <div className="min-w-0">
                      <h3 className="truncate text-[15px] font-semibold text-content">{entry.title}</h3>
                      <span className="mt-1 inline-block bg-surface-hover px-2 py-0.5 text-[11px] font-medium text-content-secondary">
                        {categoryLabel(entry.category)}
                      </span>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button onClick={() => openEdit(entry)} className="hh-icon-btn-plain h-8 w-8" title="编辑" aria-label="编辑">
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button onClick={() => handleDelete(entry)} className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="删除" aria-label="删除">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
                {(entry.summary || entry.content) && (
                  <div className="mt-4 space-y-3">
                    {entry.summary && <p className="line-clamp-2 text-[13px] leading-6 text-content-secondary">{entry.summary}</p>}
                    {entry.content && (
                      <div className="hh-subpanel px-3.5 py-3">
                        <p className="line-clamp-3 text-xs leading-5 text-content-tertiary">{entry.content}</p>
                      </div>
                    )}
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}

      {showModal && (
        <Modal
          title={editing ? '编辑设定条目' : '添加设定条目'}
          onClose={() => setShowModal(false)}
          size="lg"
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleSubmit} className="hh-btn-primary">{editing ? '保存修改' : '创建条目'}</button>
            </>
          )}
        >
          <div className="space-y-5">
            <div>
              <label className="hh-label">分类</label>
              <select value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))} className="hh-field">
                {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
            <div>
              <label className="hh-label">名称 <span className="text-red-500">*</span></label>
              <input value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} placeholder="如 越境红线、九针门" className="hh-field" />
            </div>
            <div>
              <label className="hh-label">简述</label>
              <input value={form.summary || ''} onChange={e => setForm(f => ({ ...f, summary: e.target.value }))} placeholder="一句话概括这条设定" className="hh-field" />
            </div>
            <div>
              <label className="hh-label">详细设定</label>
              <textarea value={form.content || ''} onChange={e => setForm(f => ({ ...f, content: e.target.value }))} rows={6} placeholder="补充具体内容、边界、代价…" className="hh-textarea" />
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
