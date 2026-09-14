/**
 * 文风导入对话框：把参考包的 style 拷贝到指定项目的写作风格库
 *（原 pages/ReferencePackDetail.tsx 内联组件，V5 起拆书任务页与参考包详情页共用）
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Download, Loader2, X } from 'lucide-react'
import { toast } from 'sonner'

import { projectApi, writingStyleApi } from '@/services/api'
import type { Project } from '@/types'
import type { StyleData } from '@/types/reference_pack'

export function ImportStyleDialog({
  style,
  sourceBookTitle,
  onClose,
}: {
  style: StyleData
  sourceBookTitle: string
  onClose: () => void
}) {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [loadingProjects, setLoadingProjects] = useState(true)
  const [projectId, setProjectId] = useState<string>('')
  const baseName = style.name?.trim() || '未命名风格'
  const [name, setName] = useState<string>(`${baseName} · 拆书：${sourceBookTitle}`)
  const [submitting, setSubmitting] = useState(false)
  const [createdStyleId, setCreatedStyleId] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    projectApi
      .getProjects()
      .then((res) => {
        if (cancelled) return
        const items = (res?.items ?? []) as Project[]
        setProjects(items)
        if (items.length > 0) setProjectId(items[0].id)
      })
      .catch(() => {
        if (!cancelled) toast.error('加载项目列表失败')
      })
      .finally(() => {
        if (!cancelled) setLoadingProjects(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleSubmit = async () => {
    if (!projectId) {
      toast.error('请先选择目标项目')
      return
    }
    if (!name.trim()) {
      toast.error('请填写风格名称')
      return
    }
    if (!style.prompt_content) {
      toast.error('该参考包文风缺少 prompt_content，无法导入')
      return
    }
    setSubmitting(true)
    try {
      const created = await writingStyleApi.createStyle({
        project_id: projectId,
        name: name.trim(),
        description: style.description || `来自拆书：${sourceBookTitle}`,
        prompt_content: style.prompt_content,
        style_type: 'custom',
      })
      // createStyle 返回 WritingStyle，含 id
      setCreatedStyleId((created as { id: number }).id)
      toast.success('已导入到项目写作风格库')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '导入失败')
    } finally {
      setSubmitting(false)
    }
  }

  // 已导入完成的成功视图
  if (createdStyleId !== null) {
    return (
      <DialogShell title="导入成功" onClose={onClose}>
        <div className="space-y-3 text-sm text-content">
          <p>
            已把「<strong>{name}</strong>」添加到目标项目的写作风格库。
          </p>
          <p className="text-xs text-content-secondary">
            接下来你可以在「项目 → 写作风格」里把它设为默认，或在章节生成时手动选择。
          </p>
          <div className="flex gap-2 pt-1">
            <Link
              to={`/project/${projectId}/writing-styles`}
              className="rounded-pill bg-brand px-3 py-1 text-xs font-medium text-white hover:bg-brand-600"
            >
              去查看 →
            </Link>
            <button
              type="button"
              onClick={onClose}
              className="rounded-pill border border-surface-border bg-surface px-3 py-1 text-xs text-content-secondary hover:bg-surface-hover"
            >
              关闭
            </button>
          </div>
        </div>
      </DialogShell>
    )
  }

  return (
    <DialogShell title="导入到项目写作风格库" onClose={onClose}>
      <div className="space-y-4 text-sm">
        <div>
          <label className="mb-1 block text-xs font-medium text-content-tertiary">目标项目</label>
          {loadingProjects ? (
            <div className="flex items-center gap-2 text-xs text-content-secondary">
              <Loader2 className="h-3 w-3 animate-spin" />
              加载项目列表…
            </div>
          ) : !projects || projects.length === 0 ? (
            <div className="rounded-lg border border-dashed border-surface-border bg-surface px-3 py-2 text-xs text-content-secondary">
              你还没有创建任何项目。请先在
              <Link to="/projects" className="mx-1 text-brand hover:underline">
                项目列表
              </Link>
              里新建一个。
            </div>
          ) : (
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="w-full rounded-lg border border-surface-border bg-white px-3 py-2 text-sm text-content focus:border-brand focus:outline-none"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
          )}
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-content-tertiary">写作风格名称</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-lg border border-surface-border bg-white px-3 py-2 text-sm text-content focus:border-brand focus:outline-none"
            placeholder="给这份风格起个名字"
          />
          <p className="mt-1 text-[11px] text-content-tertiary">默认带"拆书：原书名"后缀，方便日后区分来源。</p>
        </div>

        <div className="rounded-lg border border-surface-border bg-surface-deeper p-3">
          <div className="mb-1 text-[11px] font-medium text-content-tertiary">将作为 prompt_content 的内容（只读预览）</div>
          <pre className="max-h-32 overflow-auto whitespace-pre-wrap text-xs text-content">{style.prompt_content || '（缺失）'}</pre>
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-pill border border-surface-border bg-surface px-3 py-1.5 text-xs text-content-secondary hover:bg-surface-hover disabled:opacity-60"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting || loadingProjects || !projects || projects.length === 0}
            className="inline-flex items-center gap-1.5 rounded-pill bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-600 disabled:opacity-60"
          >
            {submitting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
            确认导入
          </button>
        </div>
      </div>
    </DialogShell>
  )
}

function DialogShell({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/50 px-4 py-8">
      <div className="relative my-auto w-full max-w-lg rounded-modal bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-surface-border px-5 py-3">
          <h3 className="text-sm font-semibold text-content">{title}</h3>
          <button type="button" onClick={onClose} className="text-content-tertiary hover:text-content">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  )
}
