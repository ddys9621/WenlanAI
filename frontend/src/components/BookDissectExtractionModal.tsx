/**
 * 拆书「开始 / 继续 / 重新抽取」弹窗
 *
 * 用户可选：
 * 1. 运行方式（抽过拆书卡才出现）：继续（只抽失败和没抽过的章）/ 只重建后续产物（拆书卡不动）/ 全部重抽
 * 2. 抽取范围：全书 / 只抽前 N 章（扩大范围用「继续」，只抽新增的章）
 * 3. 分批方式：自动（按模型上下文 + Max Tokens 规划每批章数）/ 自定义每批 N 章 / 逐章 / 整本一次
 *
 * 参数变化时调后端 extraction-plan 预估（不调 LLM）：这次要抽的章、分几批、预计 LLM 调用次数与告警，
 * 让用户在点「开始」之前就知道要花多少请求。
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, Loader2, Play, RotateCcw, X } from 'lucide-react'

import { bookDissectApi } from '@/services/api'
import type {
  BookDissectExtractionOptions,
  BookDissectExtractionPlan,
  BookDissectRunMode,
  BookDissectTask,
} from '@/types'
import { hasCards, pendingChapters } from '@/components/book-dissect/taskState'

type BatchMode = 'auto' | 'custom' | 'chunked' | 'long_context'

const BATCH_MODE_OPTIONS: Array<{ value: BatchMode; label: string; hint: string }> = [
  { value: 'auto', label: '自动分批', hint: '按当前模型上下文窗口与 Max Tokens 规划每批章数（推荐）' },
  { value: 'custom', label: '自定义每批章数', hint: '自己指定每次请求送多少章；超出模型上下文时仍会自动拆开' },
  { value: 'chunked', label: '逐章抽取', hint: '每章一次请求，最稳但请求次数最多' },
  { value: 'long_context', label: '整本一次', hint: '所有目标章节一次送入；截断时只补抽没拿到的章' },
]

const MODE_LABELS: Record<BookDissectExtractionPlan['mode'], string> = {
  single: '逐章',
  batched: '分批',
  one_shot: '整本一批',
}

const RUN_MODE_OPTIONS: Array<{ value: BookDissectRunMode; label: string; hint: (task: BookDissectTask) => string }> = [
  {
    value: 'resume',
    label: '继续 / 补抽',
    hint: (t) => {
      const pending = pendingChapters(t)
      return pending > 0
        ? `保留已成功的 ${t.chapters_extracted ?? 0} 章，只抽失败和没抽过的章，再重建后续结果`
        : '拆书卡都齐了：扩大范围时只抽新增的章，再重建后续结果'
    },
  },
  {
    value: 'rebuild_post',
    label: '只重建后续结果',
    hint: () => '拆书卡一张不动，重新划分剧情单元、分卷 / 骨架、人物、写法和文风（某个维度生成失败时用）',
  },
  { value: 'full', label: '全部重抽', hint: () => '删掉现有的拆书卡从头抽（换了模型、想要一份全新的结果时用）' },
]

const PLAN_DEBOUNCE_MS = 400

interface BookDissectExtractionModalProps {
  open: boolean
  task: BookDissectTask
  /** 打开时预选的运行方式（没抽过拆书卡时恒为全部抽取） */
  initialMode?: BookDissectRunMode
  submitting: boolean
  onClose: () => void
  onStart: (options: BookDissectExtractionOptions) => void
}

function buildOptions(
  runMode: BookDissectRunMode,
  batchMode: BatchMode,
  customPerRequest: number,
  limitEnabled: boolean,
  chapterLimit: number,
): BookDissectExtractionOptions {
  return {
    mode: runMode,
    sampling_mode: 'all',
    sampling_param: 1,
    extraction_engine: batchMode === 'chunked' || batchMode === 'long_context' ? batchMode : 'auto',
    chapters_per_request: batchMode === 'custom' ? Math.max(1, customPerRequest) : 0,
    chapter_limit: limitEnabled ? Math.max(1, chapterLimit) : 0,
  }
}

export function BookDissectExtractionModal({
  open,
  task,
  initialMode = 'full',
  submitting,
  onClose,
  onStart,
}: BookDissectExtractionModalProps) {
  const chapterCount = task.chapter_count || 0
  const rerun = hasCards(task)
  const [runMode, setRunMode] = useState<BookDissectRunMode>('full')
  const [batchMode, setBatchMode] = useState<BatchMode>('auto')
  const [customPerRequest, setCustomPerRequest] = useState(10)
  const [limitEnabled, setLimitEnabled] = useState(false)
  const [chapterLimit, setChapterLimit] = useState(chapterCount)
  const [plan, setPlan] = useState<BookDissectExtractionPlan | null>(null)
  const [planLoading, setPlanLoading] = useState(false)

  // 打开时用任务上一次的参数回填，运行方式取调用方预选的
  useEffect(() => {
    if (!open) return
    setRunMode(rerun ? initialMode : 'full')
    const engine = task.extraction_engine ?? 'auto'
    const perRequest = task.chapters_per_request ?? 0
    setBatchMode(engine === 'chunked' || engine === 'long_context' ? engine : perRequest > 0 ? 'custom' : 'auto')
    setCustomPerRequest(perRequest > 0 ? perRequest : 10)
    const limit = task.chapter_limit ?? 0
    setLimitEnabled(limit > 0 && limit < chapterCount)
    setChapterLimit(limit > 0 && limit < chapterCount ? limit : chapterCount)
    setPlan(null)
  }, [open, rerun, initialMode, task.id, task.extraction_engine, task.chapters_per_request, task.chapter_limit, chapterCount])

  // 参数变化 → 防抖请求预估
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setPlanLoading(true)
    const timer = window.setTimeout(async () => {
      try {
        const p = await bookDissectApi.previewExtractionPlan(
          task.id,
          buildOptions(runMode, batchMode, customPerRequest, limitEnabled, chapterLimit),
        )
        if (!cancelled) setPlan(p)
      } catch {
        if (!cancelled) setPlan(null)
      } finally {
        if (!cancelled) setPlanLoading(false)
      }
    }, PLAN_DEBOUNCE_MS)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [open, task.id, runMode, batchMode, customPerRequest, limitEnabled, chapterLimit])

  if (!open) return null

  const clampLimit = (v: number) => Math.min(chapterCount, Math.max(1, Math.floor(v) || 1))
  const title = !rerun ? '开始抽取' : runMode === 'resume' ? '继续抽取' : runMode === 'rebuild_post' ? '重建拆书结果' : '全部重抽'

  return createPortal(
    <div className="hh-modal-mask z-[60]" onClick={onClose}>
      <div className="hh-modal max-w-[580px]" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="hh-modal-head">
          <div>
            <p className="hh-eyebrow">拆书</p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">{title}</h2>
            <p className="mt-1 text-sm text-content-secondary">
              「{task.file_name ?? '(未命名)'}」共 {chapterCount} 章
              {rerun && `，已抽出 ${task.chapters_extracted ?? 0} 章拆书卡${(task.chapters_failed ?? 0) > 0 ? `、${task.chapters_failed} 章失败` : ''}`}。
            </p>
          </div>
          <button type="button" onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="hh-modal-body space-y-5">
          {rerun && (
            <section className="space-y-2">
              <p className="hh-label mb-0">怎么跑</p>
              <div className="grid gap-2">
                {RUN_MODE_OPTIONS.map((opt) => {
                  const active = runMode === opt.value
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setRunMode(opt.value)}
                      className={`hh-subpanel px-4 py-2.5 text-left transition-colors ${active ? 'border-brand bg-brand/5' : 'hover:border-brand/40'}`}
                    >
                      <p className={`text-sm font-medium ${active ? 'text-brand' : 'text-content'}`}>{opt.label}</p>
                      <p className="mt-0.5 text-xs leading-5 text-content-tertiary">{opt.hint(task)}</p>
                    </button>
                  )
                })}
              </div>
            </section>
          )}

          {/* 抽取范围 */}
          <section className="space-y-2">
            <p className="hh-label mb-0">抽取范围</p>
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => setLimitEnabled(false)} className={`hh-chip ${!limitEnabled ? 'hh-chip--active' : ''}`}>
                全书 {chapterCount} 章
              </button>
              <button type="button" onClick={() => setLimitEnabled(true)} className={`hh-chip ${limitEnabled ? 'hh-chip--active' : ''}`}>
                只抽前 N 章
              </button>
              {limitEnabled && (
                <div className="flex items-center gap-2 text-sm text-content-secondary">
                  <span>前</span>
                  <input
                    type="number"
                    min={1}
                    max={chapterCount}
                    value={chapterLimit}
                    onChange={(e) => setChapterLimit(clampLimit(Number(e.target.value)))}
                    className="hh-field h-9 w-24 px-3"
                  />
                  <span>章</span>
                </div>
              )}
            </div>
            <p className="text-xs leading-5 text-content-tertiary">
              不必拆完整本：只想借鉴开篇节奏时抽前 30-50 章就够了；以后要扩大范围，用「继续 / 补抽」只抽新增的章。
            </p>
          </section>

          {/* 分批方式：只重建后续结果不抽拆书卡，不用选 */}
          {runMode !== 'rebuild_post' && (
            <section className="space-y-2">
              <p className="hh-label mb-0">每次请求的章节数</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {BATCH_MODE_OPTIONS.map((opt) => {
                  const active = batchMode === opt.value
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setBatchMode(opt.value)}
                      className={`hh-subpanel px-4 py-3 text-left transition-colors ${active ? 'border-brand bg-brand/5' : 'hover:border-brand/40'}`}
                    >
                      <p className={`text-sm font-medium ${active ? 'text-brand' : 'text-content'}`}>{opt.label}</p>
                      <p className="mt-0.5 text-xs leading-5 text-content-tertiary">{opt.hint}</p>
                    </button>
                  )
                })}
              </div>
              {batchMode === 'custom' && (
                <div className="flex items-center gap-2 text-sm text-content-secondary">
                  <span>每批</span>
                  <input
                    type="number"
                    min={1}
                    max={60}
                    value={customPerRequest}
                    onChange={(e) => setCustomPerRequest(Math.min(60, Math.max(1, Math.floor(Number(e.target.value)) || 1)))}
                    className="hh-field h-9 w-24 px-3"
                  />
                  <span>章（上限 60）</span>
                </div>
              )}
            </section>
          )}

          <PlanSummary plan={plan} loading={planLoading} />

          {rerun && runMode === 'full' && (
            <div className="flex items-start gap-2 rounded border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>
                会删掉现有的 {task.chapters_extracted ?? 0} 章拆书卡从头抽，并更新拆书结果和知识库条目（你改过的条目不覆盖）。
                只是想补失败的章或扩大范围，选「继续 / 补抽」更省。
              </p>
            </div>
          )}
          <p className="text-xs leading-5 text-content-tertiary">
            单章失败会自动再试；网络断了、限流会等一会儿重试；Key 失效、余额不足会立即停下并说明原因，处理好后「继续抽取」接着跑。
          </p>
        </div>

        <div className="hh-modal-foot">
          <button type="button" onClick={onClose} className="hh-btn-ghost" disabled={submitting}>
            取消
          </button>
          <button
            type="button"
            onClick={() => onStart(buildOptions(runMode, batchMode, customPerRequest, limitEnabled, chapterLimit))}
            disabled={submitting || chapterCount === 0}
            className="hh-btn-primary"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : rerun && runMode !== 'full' ? <RotateCcw className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            {title}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function PlanSummary({ plan, loading }: { plan: BookDissectExtractionPlan | null; loading: boolean }) {
  if (!plan && loading) {
    return (
      <div className="hh-subpanel flex items-center gap-2 px-4 py-3 text-xs text-content-secondary">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        正在估算请求次数…
      </div>
    )
  }
  if (!plan) {
    return <div className="hh-subpanel px-4 py-3 text-xs text-content-tertiary">暂无法估算请求次数（不影响启动）。</div>
  }
  const perBatch = plan.batch_count > 0 ? Math.ceil(plan.pending_chapters / plan.batch_count) : 0
  const ctxLabel = plan.context_window > 0 ? `${Math.round(plan.context_window / 1000)}k 上下文` : '上下文未知'
  const cards =
    plan.run_mode === 'rebuild_post'
      ? `沿用 ${plan.existing_cards} 张拆书卡，不抽拆书卡`
      : plan.run_mode === 'resume'
        ? `这次抽 ${plan.pending_chapters} 章（沿用 ${plan.existing_cards} 张）`
        : `抽 ${plan.pending_chapters} 章`
  return (
    <div className={`hh-subpanel space-y-2 px-4 py-3 text-xs leading-5 text-content-secondary ${loading ? 'opacity-60' : ''}`}>
      <p className="text-sm text-content">
        范围 <span className="font-semibold">{plan.target_chapters}</span> 章 · {cards}
        {plan.batch_count > 1 && <>（{MODE_LABELS[plan.mode]}，约 {perBatch} 章/批，共 {plan.batch_count} 批）</>}
        · 预计 <span className="font-semibold text-brand">≥ {plan.estimated_llm_calls}</span> 次 LLM 调用
      </p>
      <p className="text-content-tertiary">
        拆书卡 {plan.batch_count} 次
        {plan.arc_calls > 0
          ? ` + 剧情单元 ${plan.arc_calls} 次（每轮约 ${plan.arc_window} 章）+ 分卷 / 骨架 / 人物谱 / 文风 ${plan.post_calls - plan.arc_calls} 次`
          : ` + 聚合产物 ${plan.post_calls} 次`}
        ；失败重试另计。模型 {plan.model || '未设置'}（{ctxLabel}，Max Tokens {plan.max_tokens || '未知'}）。
      </p>
      {plan.warnings.map((w) => (
        <p key={w} className="flex items-start gap-1.5 text-amber-700">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{w}</span>
        </p>
      ))}
    </div>
  )
}
