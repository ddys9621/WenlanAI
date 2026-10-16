/**
 * 可选的模型字段（分析模型 / 补全模型）：默认「跟随」某个模型（值为空）；取消勾选后从已拉取的模型列表里直接选，
 * 或手动输入模型名（部分网关不提供列表）。列表用 ModelListPicker（带搜索、按厂商分组），不用原生 datalist。
 */
import { useState, type ReactNode } from 'react'
import { ModelListPicker } from '@/components/ai-model/ModelListPicker'
import type { AIModelOption } from '@/types'

export function OptionalModelField({
  label,
  followText,
  hint,
  value,
  onChange,
  models,
  loading,
  onRefresh,
}: {
  label: ReactNode
  /** 勾选框文字，如「跟随 LLM 模型（gpt-4o）」 */
  followText: string
  hint: ReactNode
  value: string
  onChange: (v: string) => void
  models: AIModelOption[]
  loading: boolean
  onRefresh: () => void
}) {
  const [custom, setCustom] = useState(Boolean(value))
  const picking = custom || Boolean(value)

  const toggleFollow = (follow: boolean) => {
    setCustom(!follow)
    if (follow) onChange('')
  }

  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-content">{label}</span>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-content-secondary">
          <input type="checkbox" className="accent-brand" checked={!picking} onChange={(e) => toggleFollow(e.target.checked)} />
          {followText}
        </label>
      </div>
      {picking && <ModelListPicker value={value} onChange={onChange} models={models} loading={loading} onRefresh={onRefresh} />}
      <p className="mt-1 text-xs text-content-tertiary">{hint}</p>
    </div>
  )
}
