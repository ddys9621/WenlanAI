import { useEffect, useState, useCallback, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { GitBranch, Plus, Pencil, Trash2, Loader2, Heart, Swords, Users, Handshake, Minus, X } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { relationshipApi, characterApi } from '@/services/api'
import { Modal } from '@/components/ui/Modal'
import { useAssistantDataChange } from '@/hooks/useAssistantPage'
import type { AssistantDataChange } from '@/store/assistantStore'
import type { Character } from '@/types'

/** 后端 RelationshipTypeResponse */
interface RelationshipTypeItem {
  id: number
  name: string
  category: string
  reverse_name?: string
  intimacy_range?: string
  icon?: string
  description?: string
}

/** 后端返回的关系记录 */
interface RelationshipItem {
  id: string
  project_id: string
  character_from_id: string
  character_to_id: string
  relationship_type_id?: number
  relationship_name?: string
  intimacy_level: number
  status: string
  description?: string
}

/** 表单状态 */
interface RelationshipForm {
  character_from_id: string
  character_to_id: string
  relationship_type_id: number | ''
  relationship_name: string
  intimacy_level: number
  status: string
  description: string
}

const CATEGORY_STYLES: Record<string, { icon: ReactNode }> = {
  friendly:  { icon: <Handshake className="h-3.5 w-3.5" /> },
  hostile:   { icon: <Swords className="h-3.5 w-3.5" /> },
  neutral:   { icon: <Minus className="h-3.5 w-3.5" /> },
  romantic:  { icon: <Heart className="h-3.5 w-3.5" /> },
  family:    { icon: <Users className="h-3.5 w-3.5" /> },
}
const DEFAULT_STYLE = { icon: <GitBranch className="h-3.5 w-3.5" /> }

const STATUS_OPTIONS = [
  { value: 'active', label: '进行中' },
  { value: 'broken', label: '已破裂' },
  { value: 'past', label: '已结束' },
  { value: 'complicated', label: '复杂' },
]

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-emerald-50 text-emerald-600',
  broken: 'bg-red-50 text-red-600',
  past: 'bg-surface-hover text-content-secondary',
  complicated: 'bg-amber-50 text-amber-600',
}

const emptyForm: RelationshipForm = {
  character_from_id: '',
  character_to_id: '',
  relationship_type_id: '',
  relationship_name: '',
  intimacy_level: 50,
  status: 'active',
  description: '',
}

export default function Relationships() {
  const { currentProject } = useStore()

  const [relationships, setRelationships] = useState<RelationshipItem[]>([])
  const [characters, setCharacters] = useState<Character[]>([])
  const [types, setTypes] = useState<RelationshipTypeItem[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const [showModal, setShowModal] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<RelationshipForm>(emptyForm)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  const projectId = currentProject?.id

  const fetchData = useCallback(async () => {
    if (!projectId) return
    try {
      setLoading(true)
      const [rels, chars, typeList] = await Promise.all([
        relationshipApi.getProjectRelationships(projectId),
        characterApi.getCharacters(projectId),
        relationshipApi.getTypes(),
      ])
      setRelationships(rels as unknown as RelationshipItem[])
      setCharacters(Array.isArray(chars) ? chars : [])
      setTypes(Array.isArray(typeList) ? typeList : [])
    } catch {
      /* api 层已 toast */
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { fetchData() }, [fetchData])

  // 智能助笔建了 / 改了关系（或建了、改名了人物）：刷新列表
  const onAssistantData = useCallback((change: AssistantDataChange) => {
    if (change.entity === 'relationship' || change.entity === 'character') void fetchData()
  }, [fetchData])
  useAssistantDataChange(onAssistantData)

  const charMap = new Map(characters.filter(c => !c.is_organization).map(c => [c.id, c]))
  const typeMap = new Map(types.map(t => [t.id, t]))

  const getCharName = (id: string) => charMap.get(id)?.name ?? '未知角色'
  const getTypeName = (typeId?: number) => {
    if (typeId == null) return '未分类'
    return typeMap.get(typeId)?.name ?? '未知类型'
  }
  const getTypeStyle = (typeId?: number) => {
    if (typeId == null) return DEFAULT_STYLE
    const t = typeMap.get(typeId)
    if (!t) return DEFAULT_STYLE
    return CATEGORY_STYLES[t.category] ?? DEFAULT_STYLE
  }
  const getStatusLabel = (status: string) => STATUS_OPTIONS.find(o => o.value === status)?.label ?? status

  const openCreate = () => {
    setEditingId(null)
    setForm(emptyForm)
    setShowModal(true)
  }

  const openEdit = (rel: RelationshipItem) => {
    setEditingId(rel.id)
    setForm({
      character_from_id: rel.character_from_id,
      character_to_id: rel.character_to_id,
      relationship_type_id: rel.relationship_type_id ?? '',
      relationship_name: rel.relationship_name ?? '',
      intimacy_level: rel.intimacy_level ?? 50,
      status: rel.status ?? 'active',
      description: rel.description ?? '',
    })
    setShowModal(true)
  }

  const closeModal = () => {
    setShowModal(false)
    setEditingId(null)
    setForm(emptyForm)
  }

  const handleSave = async () => {
    if (!projectId) return
    if (!form.character_from_id || !form.character_to_id) {
      toast.error('请选择角色A和角色B')
      return
    }
    if (form.character_from_id === form.character_to_id) {
      toast.error('角色A和角色B不能相同')
      return
    }
    try {
      setSaving(true)
      if (editingId) {
        await relationshipApi.updateRelationship(editingId, {
          relationship_type_id: form.relationship_type_id === '' ? undefined : form.relationship_type_id,
          relationship_name: form.relationship_name || undefined,
          intimacy_level: form.intimacy_level,
          status: form.status,
          description: form.description || undefined,
        })
        toast.success('关系已更新')
      } else {
        await relationshipApi.createRelationship({
          project_id: projectId,
          character_from_id: form.character_from_id,
          character_to_id: form.character_to_id,
          relationship_type_id: form.relationship_type_id === '' ? undefined : form.relationship_type_id,
          relationship_name: form.relationship_name || undefined,
          intimacy_level: form.intimacy_level,
          status: form.status,
          description: form.description || undefined,
        })
        toast.success('关系已创建')
      }
      closeModal()
      fetchData()
    } catch {
      /* api 层已 toast */
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await relationshipApi.deleteRelationship(id)
      toast.success('关系已删除')
      setDeleteConfirmId(null)
      fetchData()
    } catch {
      /* api 层已 toast */
    }
  }

  const selectableChars = characters.filter(c => !c.is_organization)

  const hasRelationships = relationships.length > 0
  const involvedCount = new Set(relationships.flatMap(r => [r.character_from_id, r.character_to_id])).size
  const activeCount = relationships.filter(r => r.status === 'active').length
  const avgIntimacy = hasRelationships
    ? Math.round(relationships.reduce((sum, r) => sum + (r.intimacy_level ?? 0), 0) / relationships.length)
    : 0
  const deletingRel = deleteConfirmId ? relationships.find(r => r.id === deleteConfirmId) : undefined

  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">关系管理</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            记录角色两两之间的关系类型、亲密度与当前状态，理清人物脉络。
            {hasRelationships && `当前共 ${relationships.length} 条关系。`}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={openCreate} className="hh-btn-primary">
            <Plus className="h-4 w-4" />
            添加关系
          </button>
        </div>
      </section>

      {hasRelationships && !loading && (
        <section className="hh-panel grid grid-cols-2 divide-surface-border/80 md:grid-cols-4 md:divide-x">
          <StatItem label="关系总数" value={relationships.length} />
          <StatItem label="涉及角色" value={involvedCount} />
          <StatItem label="进行中" value={activeCount} />
          <StatItem label="平均亲密度" value={avgIntimacy} />
        </section>
      )}

      {loading ? (
        <section className="hh-panel flex items-center justify-center py-14">
          <Loader2 className="h-6 w-6 animate-spin text-brand" />
        </section>
      ) : !hasRelationships ? (
        <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <GitBranch className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">还没有角色关系</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            点击右上角「添加关系」，选择两位角色并标注他们之间的关系类型、亲密度与状态。
          </p>
        </section>
      ) : (
        <section className="hh-panel overflow-hidden">
          <ul className="divide-y divide-surface-border/80">
            {relationships.map(rel => {
              const style = getTypeStyle(rel.relationship_type_id)
              return (
                <li key={rel.id} className="px-5 py-4 transition-colors hover:bg-brand/[0.04] md:px-6">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2.5">
                      <span className="text-[15px] font-semibold text-content">{getCharName(rel.character_from_id)}</span>
                      <span className="hh-tag">
                        {style.icon}
                        {rel.relationship_name || getTypeName(rel.relationship_type_id)}
                      </span>
                      <span className="text-[15px] font-semibold text-content">{getCharName(rel.character_to_id)}</span>
                      <span
                        className={cn(
                          'px-2 py-0.5 text-[11px] font-medium',
                          STATUS_STYLES[rel.status] ?? 'bg-surface-hover text-content-secondary',
                        )}
                      >
                        {getStatusLabel(rel.status)}
                      </span>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <span className="mr-2 text-xs text-content-tertiary">
                        亲密度 <span className="font-medium text-content tabular-nums">{rel.intimacy_level}</span>
                      </span>
                      <button onClick={() => openEdit(rel)} className="hh-icon-btn-plain h-8 w-8" title="编辑" aria-label="编辑">
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => setDeleteConfirmId(rel.id)}
                        className="hh-icon-btn-plain h-8 w-8 hover:text-red-500"
                        title="删除"
                        aria-label="删除"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                  {rel.description && (
                    <p className="mt-2 text-[13px] leading-6 text-content-secondary">{rel.description}</p>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {showModal && (
        <Modal
          title={editingId ? '编辑关系' : '添加关系'}
          onClose={closeModal}
          size="xl"
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={closeModal} className="hh-btn-ghost">
                取消
              </button>
              <button onClick={handleSave} disabled={saving} className="hh-btn-primary">
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                {editingId ? '保存' : '创建'}
              </button>
            </>
          )}
        >
          <div className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="hh-label">角色A</label>
                <select
                  value={form.character_from_id}
                  onChange={e => setForm(f => ({ ...f, character_from_id: e.target.value }))}
                  disabled={!!editingId}
                  className="hh-field disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">请选择角色</option>
                  {selectableChars.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="hh-label">角色B</label>
                <select
                  value={form.character_to_id}
                  onChange={e => setForm(f => ({ ...f, character_to_id: e.target.value }))}
                  disabled={!!editingId}
                  className="hh-field disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">请选择角色</option>
                  {selectableChars.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="hh-label">关系类型</label>
                <select
                  value={form.relationship_type_id}
                  onChange={e => {
                    const val = e.target.value
                    setForm(f => ({ ...f, relationship_type_id: val === '' ? '' : Number(val) }))
                  }}
                  className="hh-field"
                >
                  <option value="">请选择关系类型</option>
                  {types.map(t => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="hh-label">
                  自定义关系名称
                  <span className="ml-1.5 text-xs font-normal text-content-tertiary">可选</span>
                </label>
                <input
                  type="text"
                  value={form.relationship_name}
                  onChange={e => setForm(f => ({ ...f, relationship_name: e.target.value }))}
                  placeholder="如不填则使用关系类型名称"
                  className="hh-field"
                />
              </div>
            </div>

            <div>
              <div className="mb-1.5 flex items-center justify-between gap-3">
                <label className="text-[13px] font-medium text-content">亲密度</label>
                <span className="text-xs text-content-tertiary tabular-nums">{form.intimacy_level}</span>
              </div>
              <input
                type="range"
                min={-100}
                max={100}
                value={form.intimacy_level}
                onChange={e => setForm(f => ({ ...f, intimacy_level: Number(e.target.value) }))}
                className="w-full"
              />
              <div className="mt-1 flex justify-between text-xs text-content-tertiary">
                <span>-100 敌对</span>
                <span>0</span>
                <span>100 亲密</span>
              </div>
            </div>

            <div>
              <label className="hh-label">状态</label>
              <select
                value={form.status}
                onChange={e => setForm(f => ({ ...f, status: e.target.value }))}
                className="hh-field"
              >
                {STATUS_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="hh-label">关系描述</label>
              <textarea
                value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                placeholder="描述两个角色之间的关系..."
                rows={3}
                className="hh-textarea"
              />
            </div>
          </div>
        </Modal>
      )}

      {deleteConfirmId && createPortal(
        <div className="hh-modal-mask" onClick={() => setDeleteConfirmId(null)}>
          <div className="hh-modal max-w-[420px]" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
            <div className="hh-modal-head">
              <div>
                <p className="hh-eyebrow text-red-500">危险操作</p>
                <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">删除关系</h2>
              </div>
              <button onClick={() => setDeleteConfirmId(null)} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="hh-modal-body">
              <p className="text-sm leading-7 text-content-secondary">
                确定要删除
                {deletingRel && (
                  <>
                    「<span className="font-medium text-content">{getCharName(deletingRel.character_from_id)}</span>」与「
                    <span className="font-medium text-content">{getCharName(deletingRel.character_to_id)}</span>」之间的
                  </>
                )}
                这条关系吗？此操作不可撤销。
              </p>
            </div>
            <div className="hh-modal-foot">
              <button onClick={() => setDeleteConfirmId(null)} className="hh-btn-ghost">
                取消
              </button>
              <button onClick={() => handleDelete(deleteConfirmId)} className="hh-btn-danger">
                <Trash2 className="h-4 w-4" />
                确认删除
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}

function StatItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="px-5 py-4 md:px-6">
      <p className="text-xs text-content-tertiary">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-content tabular-nums">{value}</p>
    </div>
  )
}
