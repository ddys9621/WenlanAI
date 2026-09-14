/**
 * 老参考包（pipeline_version < 5）只读视图：顶部横幅 + 各维度通用 JSON 渲染
 *
 * V2-V4 的实体图谱 / 章节事实等浏览接口已删除，老包只剩 reference_packs 表里的维度 JSON；
 * 不做数据迁移，提示用户重新上传原书按 V5 流水线抽取。
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, History } from 'lucide-react'

import type { ReferenceDimension, ReferencePackDetail } from '@/types/reference_pack'
import { renderValue } from './format'
import { Card } from './shared'

/** 参考包表里实际存了正文的六个维度（corpus 是检索维度，无正文字段） */
type PackDimension = Exclude<ReferenceDimension, 'corpus'>

const LEGACY_DIMENSIONS: Array<[PackDimension, string]> = [
  ['synopsis', '故事骨架'],
  ['methodology', '写作方法论'],
  ['style', '文风范本'],
  ['structure', '章节结构'],
  ['bridges', '桥段范本'],
  ['character_archive', '角色档案'],
]

export function LegacyPackNotice({ pack }: { pack: ReferencePackDetail }) {
  const available = LEGACY_DIMENSIONS.filter(([key]) => pack[key] != null)
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 sm:flex-row sm:items-start">
        <History className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        <div className="min-w-0 flex-1 space-y-1">
          <p className="font-medium">这是旧版流水线（V{pack.pipeline_version ?? 2}）生成的参考包，仅供只读查看</p>
          <p className="text-xs leading-5 text-amber-800/90">
            拆书已升级为 V5（逐章拆书卡 → 情节单元 → 全书骨架 / 文风指纹）。旧包仍可挂载到项目使用，
            但注入内容按旧格式压缩，且无法浏览拆书卡与情节单元。建议在「拆书参考」重新上传原书抽取，生成 V5 参考包后替换挂载。
          </p>
        </div>
        <Link
          to="/book-dissect"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-btn bg-amber-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-amber-600"
        >
          去重新抽取
        </Link>
      </div>

      {available.length === 0 ? (
        <Card>
          <p className="text-sm text-content-secondary">该参考包没有任何可展示的维度内容。</p>
        </Card>
      ) : (
        available.map(([key, label]) => (
          <JsonSection key={key} title={label} data={pack[key] as Record<string, unknown>} defaultOpen={key === 'synopsis' || key === 'style'} />
        ))
      )}
    </div>
  )
}

function JsonSection({
  title,
  data,
  defaultOpen,
}: {
  title: string
  data: Record<string, unknown>
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const entries = Object.entries(data).filter(([, v]) => v != null && v !== '')
  return (
    <Card>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-left text-sm font-semibold text-content"
      >
        {open ? <ChevronDown className="h-4 w-4 text-content-tertiary" /> : <ChevronRight className="h-4 w-4 text-content-tertiary" />}
        {title}
        <span className="ml-auto text-xs font-normal text-content-tertiary">{entries.length} 个字段</span>
      </button>
      {open && (
        <div className="mt-3 space-y-2">
          {entries.map(([k, v]) => (
            <div key={k} className="rounded-lg bg-surface-deeper px-3 py-2">
              <div className="text-xs font-medium text-content-tertiary">{k}</div>
              <div className="mt-0.5 whitespace-pre-wrap break-words text-sm leading-6 text-content">{renderValue(v)}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}
