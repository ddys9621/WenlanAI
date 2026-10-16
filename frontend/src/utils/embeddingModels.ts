/** 设置页「记忆检索」：每个模型该给什么按钮、为什么不能点（纯函数，便于单测） */
import type { EmbeddingModelItem, EmbeddingStatus } from '@/types/embedding'

export type EmbeddingAction =
  | { kind: 'active' }
  | { kind: 'activate'; disabled: string | null }
  | { kind: 'download'; disabled: string | null }
  | { kind: 'none'; note: string }

/** 整个面板为什么只读（null = 可以改） */
export function lockReason(status: Pick<EmbeddingStatus, 'can_manage' | 'env_locked' | 'env_model'>): string | null {
  if (status.env_locked) return `已由环境变量 / 配置文件 EMBEDDING_MODEL 指定为 ${status.env_model}，这里不能切换`
  if (!status.can_manage) return '向量模型全站共用，只有管理员能下载或切换'
  return null
}

export function embeddingAction(item: EmbeddingModelItem, status: EmbeddingStatus): EmbeddingAction {
  if (item.active) return { kind: 'active' }
  const locked = lockReason(status)
  const busy = status.downloading ? '正在下载模型，等完成后再操作' : null
  if (item.installed) return { kind: 'activate', disabled: locked ?? busy }
  if (item.preset) return { kind: 'download', disabled: locked ?? busy }
  return { kind: 'none', note: '本地模型缺少权重文件' }
}

/** 「一次读 512 个 token · 512 维」 */
export function describeLoaded(status: Pick<EmbeddingStatus, 'available' | 'active_model' | 'dimension' | 'max_tokens'>): string {
  if (!status.available || !status.active_model) return '未加载向量模型：召回只按人物 / 关键词匹配'
  const parts = [status.max_tokens ? `一次读 ${status.max_tokens} 个 token` : '', status.dimension ? `${status.dimension} 维` : '']
  return parts.filter(Boolean).join(' · ')
}
