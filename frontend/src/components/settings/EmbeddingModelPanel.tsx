/**
 * 设置页「记忆检索」：选向量模型（故事账本的语义召回、世界规则检索用它）。即时生效，不用点「保存设置」。
 * 预设模型可在线下载（后台任务，托盘可见、可取消），embedding 目录里手动放进去的模型也能选；
 * 切换后后台按账本重建各项目的检索索引（只用本机 CPU，不调用大模型）。
 */
import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Database, Download, Loader2, Lock } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { settingsApi } from '@/services/api'
import { useAIJobsStore } from '@/store/aiJobsStore'
import { Pill } from '@/components/ui/Pill'
import type { EmbeddingDownloadResult, EmbeddingModelItem, EmbeddingStatus } from '@/types/embedding'
import { describeLoaded, embeddingAction, lockReason } from '@/utils/embeddingModels'

export function EmbeddingModelPanel() {
  const [status, setStatus] = useState<EmbeddingStatus | null>(null)
  const [switching, setSwitching] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setStatus(await settingsApi.getEmbedding())
    } catch {
      /* 拦截器已 toast */
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const activate = async (item: EmbeddingModelItem) => {
    setSwitching(item.id)
    try {
      const res = await settingsApi.activateEmbedding(item.id)
      setStatus(res.status)
      toast.success(`已切换为「${item.label}」，正在后台重建各项目的检索索引`)
    } catch {
      /* 拦截器已 toast */
    } finally {
      setSwitching(null)
    }
  }

  const download = async (item: EmbeddingModelItem) => {
    try {
      await useAIJobsStore.getState().start<EmbeddingDownloadResult>({
        kind: 'embedding_model_download',
        title: `下载向量模型：${item.label}`,
        connect: (options) => settingsApi.downloadEmbeddingStream({ model: item.id, activate: true }, options),
        onSettled: (job) => {
          if (job.status === 'done') toast.success(`「${item.label}」已下载并启用，正在后台重建检索索引`)
          void load()
        },
      })
      void load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '下载启动失败')
    }
  }

  if (!status) {
    return <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>
  }

  const locked = lockReason(status)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-3 border border-surface-border bg-surface-paper px-4 py-3">
        <Database className={cn('mt-0.5 h-4 w-4 shrink-0', status.available ? 'text-brand' : 'text-amber-600')} />
        <div className="min-w-0 flex-1 text-sm">
          <p className="font-medium text-content">
            正在使用：{status.active_model ? status.models.find((m) => m.id === status.active_model)?.label ?? status.active_model : '无'}
          </p>
          <p className={cn('mt-0.5 text-xs', status.available ? 'text-content-tertiary' : 'text-amber-700')}>{describeLoaded(status)}</p>
        </div>
        {status.downloading && (
          <span className="flex items-center gap-1 text-xs text-brand"><Loader2 className="h-3.5 w-3.5 animate-spin" />正在下载…</span>
        )}
      </div>

      {locked && (
        <p className="flex items-center gap-1.5 text-xs text-content-secondary"><Lock className="h-3.5 w-3.5" />{locked}</p>
      )}

      <ul className="space-y-2">
        {status.models.map((item) => {
          const action = embeddingAction(item, status)
          return (
            <li key={item.id} className={cn('flex flex-wrap items-center gap-3 border px-4 py-3', item.active ? 'border-brand/50 bg-brand/[0.04]' : 'border-surface-border bg-white')}>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-sm font-medium text-content">{item.label}</span>
                  {item.recommended && <Pill tone="brand">推荐</Pill>}
                  {item.active && <Pill tone="green">使用中</Pill>}
                  {!item.active && item.installed && <Pill>已下载</Pill>}
                  <span className="text-xs text-content-tertiary">{item.size_label}</span>
                </div>
                <p className="mt-0.5 text-xs leading-5 text-content-secondary">{item.description}</p>
                {item.label !== item.id && <p className="font-mono text-[11px] text-content-tertiary">{item.id}</p>}
              </div>
              {action.kind === 'active' && (
                <span className="flex items-center gap-1 text-xs font-medium text-emerald-600"><CheckCircle2 className="h-4 w-4" />使用中</span>
              )}
              {action.kind === 'activate' && (
                <button
                  type="button"
                  onClick={() => void activate(item)}
                  disabled={Boolean(action.disabled) || switching !== null}
                  title={action.disabled ?? '切换到这个模型（即时生效）'}
                  className="inline-flex items-center gap-1.5 rounded-btn border border-surface-border px-3 py-1.5 text-sm hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {switching === item.id && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  使用
                </button>
              )}
              {action.kind === 'download' && (
                <button
                  type="button"
                  onClick={() => void download(item)}
                  disabled={Boolean(action.disabled)}
                  title={action.disabled ?? `下载（${item.size_label}）并启用`}
                  className="inline-flex items-center gap-1.5 rounded-btn border border-surface-border px-3 py-1.5 text-sm hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Download className="h-3.5 w-3.5" />下载并使用
                </button>
              )}
              {action.kind === 'none' && <span className="text-xs text-content-tertiary">{action.note}</span>}
            </li>
          )
        })}
      </ul>

      <div className="space-y-1 text-xs leading-5 text-content-tertiary">
        <p>即时生效，不用点「保存设置」。切换后各项目的检索索引会在后台按故事账本重建（只用本机 CPU，不调用大模型），重建完成前召回只按人物 / 关键词匹配。</p>
        <p>下载走镜像（hf-mirror，可用环境变量 HF_ENDPOINT 改）；其它模型可以手动放进 <span className="font-mono">{status.embedding_dir}</span> 后在这里选用。</p>
      </div>
    </div>
  )
}
