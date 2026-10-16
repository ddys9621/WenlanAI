/**
 * 章节档案：每章的摘要 + 章末状态（前情脉络 / 近期剧情的地基）、分析状态、作者版本与 AI 建议。
 * 摘要错了会一路传进单元摘要、卷摘要和规划用的「实际剧情进展」，所以这里能直接改（改过的重新分析不覆盖）。
 */
import { useCallback, useEffect, useState } from 'react'
import { Check, Loader2, Pencil, X } from 'lucide-react'
import { toast } from 'sonner'
import { chapterApi, ledgerApi } from '@/services/api'
import { Pill } from '@/components/ui/Pill'
import { AnalysisStatusDot } from '@/components/chapters/AnalysisStatusDot'
import type { DigestRow } from '@/types/ledger'
import { analysisStatusLabel } from '@/utils/analysisStatus'

export function DigestsTab({ projectId, version }: { projectId: string; version: number }) {
  const [rows, setRows] = useState<DigestRow[]>([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [summary, setSummary] = useState('')
  const [endState, setEndState] = useState('')
  const [busy, setBusy] = useState(false)
  const [onlyProblems, setOnlyProblems] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows((await ledgerApi.digests(projectId)).items)
    } catch {
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { void load() }, [load, version])

  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true)
    try {
      await action()
      toast.success(done)
      setEditing(null)
      await load()
    } catch {
      /* 全局已 toast */
    } finally {
      setBusy(false)
    }
  }

  const visible = onlyProblems ? rows.filter((r) => r.analysis_status !== 'ok' || r.digest?.suggestion || r.digest?.stale) : rows

  return (
    <section className="hh-panel p-4">
      <div className="mb-3 flex items-center gap-3 text-xs text-content-secondary">
        <span>共 {rows.length} 章有正文 · 有档案 {rows.filter((r) => r.digest).length} 章</span>
        <label className="ml-auto flex cursor-pointer items-center gap-1.5">
          <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />只看待处理（未分析 / 过期 / 失败 / 有 AI 建议）
        </label>
      </div>
      {loading ? (
        <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>
      ) : visible.length === 0 ? (
        <p className="py-10 text-center text-xs text-content-tertiary">{rows.length === 0 ? '还没有写好的章节' : '没有待处理的章节'}</p>
      ) : (
        <ul className="divide-y divide-surface-border">
          {visible.map((row) => {
            const d = row.digest
            const isEditing = editing === row.chapter_id
            return (
              <li key={row.chapter_id} className="py-3">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <AnalysisStatusDot status={row.analysis_status} message={row.analysis_message} />
                  <span className="text-[13px] font-semibold text-content">第{row.chapter_number}章《{row.title}》</span>
                  {d && <Pill tone={d.source === 'author' ? 'brand' : 'default'}>{d.source === 'author' ? '作者版本' : 'AI 分析'}</Pill>}
                  {d?.stale && <Pill tone="gold">按旧正文分析</Pill>}
                  {row.analysis_status !== 'ok' && <span className="text-[11px] text-content-tertiary">{analysisStatusLabel(row.analysis_status, row.analysis_message)}</span>}
                  {!isEditing && (
                    <button
                      onClick={() => { setEditing(row.chapter_id); setSummary(d?.summary ?? ''); setEndState(d?.end_state ?? '') }}
                      className="hh-icon-btn-plain ml-auto h-7 w-7 hover:text-brand" title="修改档案" aria-label="修改档案"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                {isEditing ? (
                  <div className="space-y-2">
                    <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={3} maxLength={1000} placeholder="摘要" className="w-full text-xs leading-5" />
                    <textarea value={endState} onChange={(e) => setEndState(e.target.value)} rows={2} maxLength={500} placeholder="章末状态" className="w-full text-xs leading-5" />
                    <div className="flex justify-end gap-2">
                      <button onClick={() => setEditing(null)} className="hh-btn-ghost hh-btn-sm"><X className="h-3.5 w-3.5" />取消</button>
                      <button onClick={() => void run(() => chapterApi.updateDigest(row.chapter_id, { summary, end_state: endState }), '已保存，重新分析不会覆盖')}
                        disabled={busy || !summary.trim()} className="hh-btn-primary hh-btn-sm"><Check className="h-3.5 w-3.5" />保存</button>
                    </div>
                  </div>
                ) : d ? (
                  <div className="text-xs leading-6">
                    <p className="text-content">{d.summary}</p>
                    {d.end_state && <p className="text-content-secondary"><span className="text-content-tertiary">章末：</span>{d.end_state}</p>}
                    {d.suggestion && (
                      <div className="mt-1.5 border border-dashed border-brand/40 bg-brand/[0.04] p-2">
                        <p className="font-medium text-brand">AI 新分析的结果</p>
                        <p className="text-content">{d.suggestion.summary}</p>
                        <div className="mt-1 flex justify-end gap-2">
                          <button onClick={() => void run(() => chapterApi.dismissDigest(row.chapter_id), '已忽略')} disabled={busy} className="hh-btn-ghost hh-btn-sm">忽略</button>
                          <button onClick={() => void run(() => chapterApi.acceptDigest(row.chapter_id), '已采用')} disabled={busy} className="hh-btn-secondary hh-btn-sm">采用</button>
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-content-tertiary">还没有档案：分析本章，或点右边手写一份</p>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
