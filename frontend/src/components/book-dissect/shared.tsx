/**
 * 拆书 V5 视图共用小组件（BookDissectV5View / LegacyPackNotice 共享）
 */
import { AlertTriangle, Loader2 } from 'lucide-react'
import { renderValue } from './format'

export function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`hh-subpanel rounded-2xl p-4 ${className}`}>{children}</div>
}

export function CardTitle({
  icon: Icon,
  children,
  extra,
}: {
  icon?: React.ComponentType<{ className?: string }>
  children: React.ReactNode
  extra?: React.ReactNode
}) {
  return (
    <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-content">
      {Icon && <Icon className="h-4 w-4 text-brand" />}
      <span className="min-w-0 flex-1">{children}</span>
      {extra && <span className="text-xs font-normal text-content-tertiary">{extra}</span>}
    </h3>
  )
}

export function SectionTip({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-brand/20 bg-brand/5 px-4 py-2.5 text-xs leading-5 text-content-secondary">
      {children}
    </div>
  )
}

export function NoDataHint({ label, hint }: { label: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-surface-border bg-surface px-6 py-12 text-center text-content-secondary">
      <AlertTriangle className="mx-auto h-6 w-6 text-content-tertiary" />
      <p className="mt-2 text-sm">该参考包未生成「{label}」</p>
      <p className="mt-1 text-xs text-content-tertiary">{hint ?? '可能是 LLM 调用失败或抽取尚未完成，可重新抽取本书'}</p>
    </div>
  )
}

export function CenterLoader({ text = '加载中…' }: { text?: string }) {
  return (
    <div className="flex items-center justify-center py-10 text-sm text-content-secondary">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      {text}
    </div>
  )
}

/** 键值行：value 为空时整行不渲染 */
export function Field({
  label,
  value,
  multiline = false,
}: {
  label: string
  value: unknown
  multiline?: boolean
}) {
  const text = renderValue(value)
  if (!text) return null
  return (
    <div className="mb-2 last:mb-0">
      <div className="text-xs font-medium text-content-tertiary">{label}</div>
      <div className={`text-sm text-content ${multiline ? 'whitespace-pre-wrap leading-6' : ''}`}>{text}</div>
    </div>
  )
}

export function TagList({ items, tone = 'brand' }: { items: string[] | undefined; tone?: 'brand' | 'muted' }) {
  if (!items || items.length === 0) return null
  const cls = tone === 'brand' ? 'hh-tag' : 'inline-flex items-center bg-surface px-2 py-0.5 text-xs text-content-secondary'
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((t, i) => (
        <span key={`${t}-${i}`} className={cls}>
          {t}
        </span>
      ))}
    </div>
  )
}

/** 分布条：{标签: 计数或比例}，按值倒序，最大值撑满 */
export function DistributionBars({
  data,
  percent = false,
  max = 12,
}: {
  data: Record<string, number> | undefined
  /** 值本身是 0-1 比例时按百分比显示 */
  percent?: boolean
  max?: number
}) {
  const entries = Object.entries(data ?? {})
    .filter(([, v]) => typeof v === 'number' && Number.isFinite(v))
    .sort((a, b) => b[1] - a[1])
    .slice(0, max)
  if (entries.length === 0) return <p className="text-xs text-content-tertiary">—</p>
  const top = entries[0][1] || 1
  return (
    <ul className="space-y-1.5">
      {entries.map(([k, v]) => (
        <li key={k} className="flex items-center gap-2 text-xs">
          <span className="w-24 shrink-0 truncate text-content" title={k}>
            {k}
          </span>
          <div className="relative h-2 flex-1 bg-brand/10">
            <div className="absolute inset-y-0 left-0 bg-brand/70" style={{ width: `${Math.max(2, (v / top) * 100)}%` }} />
          </div>
          <span className="w-14 shrink-0 text-right tabular-nums text-content-secondary">
            {percent ? `${Math.round(v * 100)}%` : v}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** 十分位折线的简化版：10 根柱子表示全书张力 / 密度走势 */
export function DecileBars({ values, maxValue = 5 }: { values: number[] | undefined; maxValue?: number }) {
  if (!values || values.length === 0) return <p className="text-xs text-content-tertiary">—</p>
  return (
    <div className="flex h-16 items-end gap-1">
      {values.map((v, i) => (
        <div key={i} className="flex flex-1 flex-col items-center gap-1" title={`第 ${i + 1}/10 段：${v}`}>
          <div className="w-full bg-brand/60" style={{ height: `${Math.max(4, (v / maxValue) * 100)}%` }} />
          <span className="text-[10px] tabular-nums text-content-tertiary">{v}</span>
        </div>
      ))}
    </div>
  )
}

