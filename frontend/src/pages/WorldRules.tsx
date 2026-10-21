import { useEffect, useState, useCallback } from 'react'
import { Plus, Pencil, Trash2, Shield, Map, Sword, Loader2, ScrollText } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { worldRulesApi } from '@/services/api'
import { Modal } from '@/components/ui/Modal'
import { useAssistantDataChange } from '@/hooks/useAssistantPage'
import type { AssistantDataChange } from '@/store/assistantStore'
import type { WorldRule, WorldRuleCreate, WorldRuleUpdate } from '@/types'

const CATEGORIES = [
  { value: 'cultivation_realm' as const, label: '修炼境界', icon: Shield },
  { value: 'equipment_template' as const, label: '装备模板', icon: Sword },
  { value: 'map_location' as const, label: '地图位置', icon: Map },
]

type Category = WorldRule['category']

export default function WorldRules() {
  const { currentProject } = useStore()
  const [rules, setRules] = useState<WorldRule[]>([])
  const [loading, setLoading] = useState(false)
  const [activeCategory, setActiveCategory] = useState<Category | 'all'>('all')
  const [showModal, setShowModal] = useState(false)
  const [editingRule, setEditingRule] = useState<WorldRule | null>(null)

  // 表单
  const [form, setForm] = useState<WorldRuleCreate>({
    category: 'cultivation_realm',
    key: '',
    name: '',
    order_index: 0,
    summary: '',
    details: '',
  })

  const fetchRules = useCallback(async () => {
    if (!currentProject?.id) return
    try {
      setLoading(true)
      const cat = activeCategory === 'all' ? undefined : activeCategory
      const res = await worldRulesApi.list(currentProject.id, cat)
      setRules(res.items)
    } catch {
      // api 层已 toast
    } finally {
      setLoading(false)
    }
  }, [currentProject?.id, activeCategory])

  useEffect(() => { fetchRules() }, [fetchRules])

  // 智能助笔建了 / 改了世界规则：刷新列表
  const onAssistantData = useCallback((change: AssistantDataChange) => {
    if (change.entity === 'world_rule') void fetchRules()
  }, [fetchRules])
  useAssistantDataChange(onAssistantData)

  const openCreate = () => {
    setEditingRule(null)
    setForm({ category: 'cultivation_realm', key: '', name: '', order_index: rules.length, summary: '', details: '' })
    setShowModal(true)
  }

  const openEdit = (rule: WorldRule) => {
    setEditingRule(rule)
    setForm({ category: rule.category, key: rule.key, name: rule.name, order_index: rule.order_index, summary: rule.summary || '', details: rule.details || '' })
    setShowModal(true)
  }

  const handleSubmit = async () => {
    if (!currentProject?.id) return
    if (!form.key.trim() || !form.name.trim()) {
      toast.error('请填写标识和名称')
      return
    }
    try {
      if (editingRule) {
        const data: WorldRuleUpdate = { ...form }
        const updated = await worldRulesApi.update(editingRule.id, data)
        setRules(prev => prev.map(r => r.id === updated.id ? updated : r))
        toast.success('规则已更新')
      } else {
        const created = await worldRulesApi.create(currentProject.id, form)
        setRules(prev => [...prev, created])
        toast.success('规则已创建')
      }
      setShowModal(false)
    } catch {
      // api 层已 toast
    }
  }

  const handleDelete = async (rule: WorldRule) => {
    const onMap = rule.category === 'map_location' ? '世界地图上的这个地点（含坐标和档案）也会一起删除。' : ''
    if (!confirm(`确定删除「${rule.name}」？${onMap}`)) return
    try {
      await worldRulesApi.delete(rule.id)
      setRules(prev => prev.filter(r => r.id !== rule.id))
      toast.success('规则已删除')
    } catch {
      // api 层已 toast
    }
  }

  const filtered = activeCategory === 'all' ? rules : rules.filter(r => r.category === activeCategory)
  const getCategoryLabel = (cat: Category) => CATEGORIES.find(c => c.value === cat)?.label || cat
  const getCategoryIcon = (cat: Category) => CATEGORIES.find(c => c.value === cat)?.icon || ScrollText

  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">世界规则</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            把修炼境界、装备模板与地图位置整理成规则条目，AI 写作时会据此保持设定一致。地图位置会自动出现在世界地图上。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={openCreate} className="hh-btn-primary">
            <Plus className="h-4 w-4" />
            添加规则
          </button>
        </div>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setActiveCategory('all')}
            className={cn('hh-chip', activeCategory === 'all' && 'hh-chip--active')}
          >
            全部
          </button>
          {CATEGORIES.map(cat => (
            <button
              key={cat.value}
              onClick={() => setActiveCategory(cat.value)}
              className={cn('hh-chip', activeCategory === cat.value && 'hh-chip--active')}
            >
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
            <ScrollText className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">
            {activeCategory === 'all' ? '还没有世界规则' : `暂无「${getCategoryLabel(activeCategory)}」规则`}
          </h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            点击右上角「添加规则」录入设定，也可以切换上方分类查看其他规则。
          </p>
        </section>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map(rule => {
            const Icon = getCategoryIcon(rule.category)
            return (
              <article key={rule.id} className="hh-panel flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-brand/10 text-brand">
                      <Icon className="h-5 w-5" />
                    </span>
                    <div className="min-w-0">
                      <h3 className="truncate text-[15px] font-semibold text-content">{rule.name}</h3>
                      <span className="mt-1 inline-block bg-surface-hover px-2 py-0.5 text-[11px] font-medium text-content-secondary">
                        {getCategoryLabel(rule.category)}
                      </span>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button onClick={() => openEdit(rule)} className="hh-icon-btn-plain h-8 w-8" title="编辑" aria-label="编辑">
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button onClick={() => handleDelete(rule)} className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="删除" aria-label="删除">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
                {(rule.summary || rule.details) && (
                  <div className="mt-4 space-y-3">
                    {rule.summary && <p className="line-clamp-2 text-[13px] leading-6 text-content-secondary">{rule.summary}</p>}
                    {rule.details && (
                      <div className="hh-subpanel px-3.5 py-3">
                        <p className="line-clamp-3 text-xs leading-5 text-content-tertiary">{rule.details}</p>
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
          title={editingRule ? '编辑规则' : '添加规则'}
          onClose={() => setShowModal(false)}
          size="lg"
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleSubmit} className="hh-btn-primary">{editingRule ? '保存修改' : '创建规则'}</button>
            </>
          )}
        >
          <div className="space-y-5">
            <div>
              <label className="hh-label">分类</label>
              <select
                value={form.category}
                onChange={e => setForm(f => ({ ...f, category: e.target.value as Category }))}
                className="hh-field"
              >
                {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <label className="hh-label">
                  标识 (key) <span className="text-red-500">*</span>
                </label>
                <input value={form.key} onChange={e => setForm(f => ({ ...f, key: e.target.value }))} placeholder="如 qi_refining" className="hh-field" />
              </div>
              <div>
                <label className="hh-label">
                  名称 <span className="text-red-500">*</span>
                </label>
                <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="如 炼气期" className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">摘要</label>
              <input value={form.summary || ''} onChange={e => setForm(f => ({ ...f, summary: e.target.value }))} placeholder="一句话概括这条规则" className="hh-field" />
            </div>
            <div>
              <label className="hh-label">详情</label>
              <textarea value={form.details || ''} onChange={e => setForm(f => ({ ...f, details: e.target.value }))} rows={4} placeholder="补充具体内容、限制与代价…" className="hh-textarea" />
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
