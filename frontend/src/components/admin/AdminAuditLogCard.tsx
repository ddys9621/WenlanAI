import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Loader2, RefreshCw, ScrollText } from 'lucide-react'
import { adminApi } from '@/services/api'
import { auditActionLabel } from '@/utils/userManagement'
import type { AdminAuditLog } from '@/types'

const PAGE = 20

/** 把 detail 里值得一看的键拼成一行小字（不含密码：后端本就不记） */
function detailText(d: Record<string, unknown>): string {
  const parts: string[] = []
  if (Array.isArray(d.changed) && d.changed.length) parts.push(`改了：${(d.changed as string[]).join('、')}`)
  if (typeof d.username === 'string') parts.push(`用户名 ${d.username}`)
  if (d.is_admin === true || d.was_admin === true) parts.push('管理员')
  if (d.generated_password === true || d.generated === true) parts.push('系统生成密码')
  return parts.join(' · ')
}

/** 用户管理页「操作记录」卡：折叠式，展开时才拉取；倒序分页，底部「加载更多」。 */
export function AdminAuditLogCard() {
  const [expanded, setExpanded] = useState(false)
  const [items, setItems] = useState<AdminAuditLog[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async (offset: number) => {
    try {
      setLoading(true)
      const res = await adminApi.getAuditLogs({ limit: PAGE, offset })
      setTotal(res.total)
      setItems(prev => offset === 0 ? res.items : [...prev, ...res.items])
      setLoaded(true)
    } catch { /* api 层已 toast */ } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (expanded && !loaded) void load(0)
  }, [expanded, loaded, load])

  return (
    <div className="bg-white border border-surface-border rounded-card">
      <button
        type="button"
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between gap-4 px-5 py-4 text-left hover:bg-surface-hover/40 transition-colors"
      >
        <div className="min-w-0 flex items-center gap-2">
          <ScrollText className="w-4 h-4 text-brand shrink-0" />
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-content">操作记录</h2>
            <p className="mt-0.5 text-xs text-content-secondary truncate">管理员对用户的增、改、禁用、重置密码、强制下线、删除都在这里留痕{loaded ? `（共 ${total} 条）` : ''}</p>
          </div>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 shrink-0 text-content-secondary" /> : <ChevronDown className="w-4 h-4 shrink-0 text-content-secondary" />}
      </button>

      {expanded && (
        <div className="border-t border-surface-border">
          <div className="flex justify-end px-5 py-2">
            <button type="button" onClick={() => void load(0)} disabled={loading} className="inline-flex items-center gap-1 text-xs text-content-secondary hover:text-content disabled:opacity-50">
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />刷新
            </button>
          </div>
          {loading && items.length === 0 ? (
            <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin text-content-secondary" /></div>
          ) : items.length === 0 ? (
            <p className="px-5 pb-6 text-center text-sm text-content-secondary">还没有操作记录</p>
          ) : (
            <ul className="divide-y divide-surface-border">
              {items.map(log => {
                const extra = detailText(log.detail || {})
                return (
                  <li key={log.id} className="px-5 py-2.5 flex items-start gap-3 text-sm">
                    <span className="shrink-0 w-[150px] text-xs text-content-tertiary tabular-nums">
                      {log.created_at ? new Date(log.created_at).toLocaleString('zh-CN') : '-'}
                    </span>
                    <span className="min-w-0 flex-1 text-content">
                      <span className="font-medium">{log.actor_name || log.actor_id}</span>
                      <span className="text-content-secondary"> {auditActionLabel(log.action)} </span>
                      {log.target_name || log.target_id ? <span className="font-medium">「{log.target_name || log.target_id}」</span> : null}
                      {extra && <span className="ml-2 text-xs text-content-tertiary">{extra}</span>}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
          {items.length < total && (
            <div className="flex justify-center py-3 border-t border-surface-border">
              <button type="button" onClick={() => void load(items.length)} disabled={loading} className="hh-btn-ghost text-xs">
                {loading ? '加载中…' : `加载更多（还有 ${total - items.length} 条）`}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
