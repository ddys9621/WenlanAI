import { useEffect, useState, useCallback } from 'react'
import { Plus, Pencil, Trash2, Star, Palette, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { writingStyleApi } from '@/services/api'
import { Modal } from '@/components/ui/Modal'
import type { WritingStyle, PresetStyle, WritingStyleCreate, WritingStyleUpdate } from '@/types'

export default function WritingStyles() {
  const { currentProject } = useStore()
  const [styles, setStyles] = useState<WritingStyle[]>([])
  const [presets, setPresets] = useState<PresetStyle[]>([])
  const [loading, setLoading] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [editingStyle, setEditingStyle] = useState<WritingStyle | null>(null)
  const [form, setForm] = useState({ name: '', description: '', prompt_content: '', style_type: 'custom' as 'preset' | 'custom', preset_id: '' })

  const fetchData = useCallback(async () => {
    if (!currentProject?.id) return
    try {
      setLoading(true)
      const [stylesRes, presetsRes] = await Promise.all([
        writingStyleApi.getProjectStyles(currentProject.id),
        writingStyleApi.getPresetStyles(),
      ])
      setStyles(stylesRes.styles)
      setPresets(presetsRes)
    } catch { /* api 层已 toast */ } finally { setLoading(false) }
  }, [currentProject?.id])

  useEffect(() => { fetchData() }, [fetchData])

  const openCreate = () => {
    setEditingStyle(null)
    setForm({ name: '', description: '', prompt_content: '', style_type: 'custom', preset_id: '' })
    setShowModal(true)
  }

  const openEdit = (s: WritingStyle) => {
    setEditingStyle(s)
    setForm({ name: s.name, description: s.description || '', prompt_content: s.prompt_content, style_type: s.style_type, preset_id: s.preset_id || '' })
    setShowModal(true)
  }

  const handlePresetSelect = (presetId: string) => {
    const preset = presets.find(p => p.id === presetId)
    if (preset) {
      setForm(f => ({ ...f, preset_id: presetId, name: preset.name, description: preset.description, prompt_content: preset.prompt_content, style_type: 'preset' }))
    }
  }

  const handleSubmit = async () => {
    if (!currentProject?.id) return
    if (!form.name.trim()) { toast.error('请填写名称'); return }
    try {
      if (editingStyle) {
        const data: WritingStyleUpdate = { name: form.name, description: form.description, prompt_content: form.prompt_content }
        const updated = await writingStyleApi.updateStyle(editingStyle.id, data)
        setStyles(prev => prev.map(s => s.id === updated.id ? updated : s))
        toast.success('风格已更新')
      } else {
        const data: WritingStyleCreate = { project_id: currentProject.id, name: form.name, description: form.description, prompt_content: form.prompt_content, style_type: form.style_type, preset_id: form.preset_id || undefined }
        const created = await writingStyleApi.createStyle(data)
        setStyles(prev => [...prev, created])
        toast.success('风格已创建')
      }
      setShowModal(false)
    } catch { /* api 层已 toast */ }
  }

  const handleDelete = async (s: WritingStyle) => {
    if (!confirm(`确定删除「${s.name}」？`)) return
    try {
      await writingStyleApi.deleteStyle(s.id)
      setStyles(prev => prev.filter(x => x.id !== s.id))
      toast.success('风格已删除')
    } catch { /* api 层已 toast */ }
  }

  const handleSetDefault = async (s: WritingStyle) => {
    if (!currentProject?.id) return
    try {
      await writingStyleApi.setDefaultStyle(s.id, currentProject.id)
      setStyles(prev => prev.map(x => ({ ...x, is_default: x.id === s.id })))
      toast.success(`已将「${s.name}」设为默认风格`)
    } catch { /* api 层已 toast */ }
  }

  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">写作风格</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            定义叙述语气与遣词习惯，AI 生成正文时会按默认风格执行。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={openCreate} className="hh-btn-primary">
            <Plus className="h-4 w-4" />
            添加风格
          </button>
        </div>
      </section>

      {loading ? (
        <section className="hh-panel flex items-center justify-center py-14">
          <Loader2 className="h-6 w-6 animate-spin text-brand" />
        </section>
      ) : styles.length === 0 ? (
        <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <Palette className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">还没有写作风格</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            点击右上角「添加风格」，可从预设快速创建或自定义 Prompt；设为默认后 AI 生成正文时会自动遵循。
          </p>
        </section>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {styles.map(s => (
            <article key={s.id} className={cn('hh-panel flex flex-col p-5', s.is_default && 'border-brand')}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-brand/10 text-brand">
                    <Palette className="h-5 w-5" />
                  </span>
                  <div className="min-w-0">
                    <h3 className="truncate text-[15px] font-semibold text-content">{s.name}</h3>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <span className="bg-surface-hover px-2 py-0.5 text-[11px] font-medium text-content-secondary">
                        {s.style_type === 'preset' ? '预设' : '自定义'}
                      </span>
                      {s.is_default && (
                        <span className="inline-flex items-center gap-1 bg-brand/10 px-2 py-0.5 text-[11px] font-medium text-brand">
                          <Star className="h-3 w-3 fill-current" />
                          默认
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-0.5">
                  {!s.is_default && (
                    <button onClick={() => handleSetDefault(s)} title="设为默认" aria-label="设为默认" className="hh-icon-btn-plain h-8 w-8">
                      <Star className="h-4 w-4" />
                    </button>
                  )}
                  <button onClick={() => openEdit(s)} title="编辑" aria-label="编辑" className="hh-icon-btn-plain h-8 w-8">
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button onClick={() => handleDelete(s)} title="删除" aria-label="删除" className="hh-icon-btn-plain h-8 w-8 hover:text-red-500">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
              <div className="mt-4 space-y-3">
                {s.description && <p className="line-clamp-2 text-[13px] leading-6 text-content-secondary">{s.description}</p>}
                <div className="hh-subpanel px-3.5 py-3">
                  <p className="line-clamp-3 font-mono text-xs leading-5 text-content-tertiary">{s.prompt_content}</p>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {showModal && (
        <Modal
          title={editingStyle ? '编辑风格' : '添加风格'}
          onClose={() => setShowModal(false)}
          size="lg"
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleSubmit} className="hh-btn-primary">{editingStyle ? '保存修改' : '创建风格'}</button>
            </>
          )}
        >
          <div className="space-y-5">
            {!editingStyle && presets.length > 0 && (
              <div>
                <label className="hh-label">从预设创建</label>
                <select
                  value={form.preset_id}
                  onChange={e => handlePresetSelect(e.target.value)}
                  className="hh-field"
                >
                  <option value="">自定义风格</option>
                  {presets.map(p => <option key={p.id} value={p.id}>{p.name} — {p.description}</option>)}
                </select>
                <p className="mt-1.5 text-xs text-content-tertiary">选择预设后会自动填入名称、描述与 Prompt，仍可继续修改。</p>
              </div>
            )}
            <div>
              <label className="hh-label">
                名称 <span className="text-red-500">*</span>
              </label>
              <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="如：冷峭克制、轻松幽默" className="hh-field" />
            </div>
            <div>
              <label className="hh-label">描述</label>
              <input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} placeholder="一句话说明这种风格适合什么场景" className="hh-field" />
            </div>
            <div>
              <label className="hh-label">Prompt 内容</label>
              <textarea value={form.prompt_content} onChange={e => setForm(f => ({ ...f, prompt_content: e.target.value }))} rows={6} placeholder="写给 AI 的风格指令：句式长短、用词偏好、叙述节奏…" className="hh-textarea font-mono" />
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
