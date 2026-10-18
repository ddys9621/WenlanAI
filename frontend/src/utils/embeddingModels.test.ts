import { describe, expect, it } from 'vitest'
import type { EmbeddingModelItem, EmbeddingStatus } from '@/types/embedding'
import { describeLoaded, embeddingAction, lockReason } from './embeddingModels'

const item = (over: Partial<EmbeddingModelItem>): EmbeddingModelItem => ({
  id: 'BAAI/bge-base-zh-v1.5', label: '中文 · 标准', size_label: '约 400MB', description: '', language: '中文',
  recommended: false, preset: true, installed: false, active: false, ...over,
})

const status = (over: Partial<EmbeddingStatus> = {}): EmbeddingStatus => ({
  available: true, active_model: 'BAAI/bge-small-zh-v1.5', dimension: 512, max_tokens: 512, selected_model: null,
  env_model: null, env_locked: false, can_manage: true, downloading: false, download_job_id: null, embedding_dir: 'D:/x',
  models: [], ...over,
})

describe('记忆检索模型的按钮', () => {
  it('在用 / 已下载可切换 / 预设可下载 / 本地缺权重', () => {
    expect(embeddingAction(item({ active: true, installed: true }), status())).toEqual({ kind: 'active' })
    expect(embeddingAction(item({ installed: true }), status())).toEqual({ kind: 'activate', disabled: null })
    expect(embeddingAction(item({}), status())).toEqual({ kind: 'download', disabled: null })
    expect(embeddingAction(item({ preset: false }), status()).kind).toBe('none')
  })

  it('非管理员 / 环境变量锁定 / 正在下载时不能点，并说明原因', () => {
    expect(embeddingAction(item({ installed: true }), status({ can_manage: false }))).toEqual({
      kind: 'activate', disabled: '向量模型全站共用，只有管理员能下载或切换',
    })
    const locked = embeddingAction(item({}), status({ env_locked: true, env_model: 'BAAI/bge-m3' }))
    expect(locked.kind === 'download' && locked.disabled).toContain('BAAI/bge-m3')
    const busy = embeddingAction(item({ installed: true }), status({ downloading: true }))
    expect(busy.kind === 'activate' && busy.disabled).toContain('正在下载')
    expect(lockReason(status())).toBeNull()
  })

  it('当前模型说明', () => {
    expect(describeLoaded(status())).toBe('一次读 512 个 token · 512 维')
    expect(describeLoaded(status({ available: false, active_model: null }))).toContain('只按人物 / 关键词')
  })
})
