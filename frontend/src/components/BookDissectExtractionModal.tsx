/**
 * 拆书「启动抽取」选项弹窗
 *
 * 用户可选：
 * 1. 抽取范围：全书 / 只抽前 N 章（不一定要拆完整本）
 * 2. 分批方式：自动（按模型上下文 + Max Tokens 规划每批章数）/ 自定义每批 N 章 / 逐章 / 整本一次
 *
 * 参数变化时调后端 extraction-plan 预估（不调 LLM）：目标章数、分几批、预计 LLM 调用次数与告警，
 * 让用户在点「开始」之前就知道要花多少请求。
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, Loader2, Play, X } from 'lucide-react'

import { bookDissectApi } from '@/services/api'
import type {
  BookDissectExtractionOptions,
  BookDissectExtractionPlan,
  BookDissectTask,
} from '@/types'

type BatchMode = 'auto' | 'custom' | 'chunked' | 'long_context'

const BATCH_MODE_OPTIONS: Array<{ value: BatchMode; label: string; hint: string }> = [
  { value: 'auto', label: '自动分批', hint: '按当前模型上下文窗口与 Max Tokens 规划每批章数（推荐）' },
  { value: 'custom', label: '自定义每批章数', hint: '自己指定每次请求送多少章；超出模型上下文时仍会自动拆开' },
  { value: 'chunked', label: '逐章抽取', hint: '每章一次请求，最稳但请求次数最多' },
  { value: 'long_context', label: '整本一次', hint: '所有目标章节一次送入；失败或截断时自动对半拆分重试' },
]

const MODE_LABELS: Record<BookDissectExtractionPlan['mode'], string> = {
  single: '逐章',
  batched: '分批',
  one_shot: '整本一批',
}

const PLAN_DEBOUNCE_MS = 400

interface BookDissectExtractionModalProps {
  open: boolean
  task: BookDissectTask
  submitting: boolean
  onClose: () => void
  onStart: (options: BookDissectExtractionOptions) => void
}

function buildOptions(
  batchMode: BatchMode,
  customPerRequest: number,
  limitEnabled: boolean,
  chapterLimit: number,
): BookDissectExtractionOptions {
  return {
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
  submitting,
  onClose,
  onStart,
}: BookDissectExtractionModalProps) {
  const chapterCount = task.chapter_count || 0
  const [batchMode, setBatchMode] = useState<BatchMode>('auto')
  const [customPerRequest, setCustomPerRequest] = useState(10)
  const [limitEnabled, setLimitEnabled] = useState(false)
  const [chapterLimit, setChapterLimit] = useState(chapterCount)
  const [plan, setPlan] = useState<BookDissectExtractionPlan | null>(null)
  const [planLoading, setPlanLoading] = useState(false)

  // 打开时用任务上一次的参数回填（重抽场景），默认全书 + 自动
  useEffect(() => {
    if (!open) return
    const engine = task.extraction_engine ?? 'auto'
    const perRequest = task.chapters_per_request ?? 0
    setBatchMode(engine === 'chunked' || engine === 'long_context' ? engine : perRequest > 0 ? 'custom' : 'auto')
    setCustomPerRequest(perRequest > 0 ? perRequest : 10)
    const limit = task.chapter_limit ?? 0
    setLimitEnabled(limit > 0 && limit < chapterCount)
    setChapterLimit(limit > 0 && limit < chapterCount ? limit : chapterCount)
    setPlan(null)
  }, [open, task.id, task.extraction_engine, task.chapters_per_request, task.chapter_limit, chapterCount])

  // 参数变化 → 防抖请求预估
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setPlanLoading(true)
    const timer = window.setTimeout(async () => {
      try {
        const p = await bookDissectApi.previewExtractionPlan(
          task.id,
          buildOptions(batchMode, customPerRequest, limitEnabled, chapterLimit),
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
  }, [open, task.id, batchMode, customPerRequest, limitEnabled, chapterLimit])

  if (!open) return null

  // 已完成、或上次（被停止 / 失败）已经抽出过章节 → 都属于重抽，会覆盖旧数据
  const isRerun = task.stage === 'done' || (task.chapters_extracted ?? 0) > 0
  const clampLimit = (v: number) => Math.min(chapterCount, Math.max(1, Math.floor(v) || 1))

  return createPortal(
    <div className="hh-modal-mask z-[60]" onClick={onClose}>
      <div
        className="hh-modal max-w-[560px]"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="hh-modal-head">
          <div>
            <p className="hh-eyebrow">拆书</p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">
              {isRerun ? '重新抽取' : '启动抽取'}
            </h2>
            <p className="mt-1 text-sm text-content-secondary">
              「{task.file_name ?? '(未命名)'}」共 {chapterCount} 章。选择要抽取的范围与每次请求的章节数。
            </p>
          </div>
          <button type="button" onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="hh-modal-body space-y-5">
          {/* 抽取范围 */}
          <section className="space-y-2">
            <p className="hh-label mb-0">抽取范围</p>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setLimitEnabled(false)}
                className={`hh-chip ${!limitEnabled ? 'hh-chip--active' : ''}`}
              >
                全书 {chapterCount} 章
              </button>
              <button
                type="button"
                onClick={() => setLimitEnabled(true)}
                className={`hh-chip ${limitEnabled ? 'hh-chip--active' : ''}`}
              >
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
              不必拆完整本：只想借鉴开篇节奏时抽前 30-50 章就够了，后面随时可以「重新抽取」扩大范围。
            </p>
          </section>

          {/* 分批方式 */}
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
                    className={`hh-subpanel px-4 py-3 text-left transition-colors ${
                      active ? 'border-brand bg-brand/5' : 'hover:border-brand/40'
                    }`}
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

          {/* 预估 */}
          <PlanSummary plan={plan} loading={planLoading} />

          {isRerun && (
            <div className="flex items-start gap-2 border border-amber-200 bg-amber-50/80 px-4 py-3 text-xs leading-5 text-amber-700">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>
                {task.stage === 'done'
                  ? '本任务已抽取过：重新抽取会覆盖现有抽取数据并更新参考包。'
                  : `上次抽取${task.status === 'cancelled' ? '被手动停止' : '未完成'}（已抽 ${task.chapters_extracted ?? 0} 章）：重新抽取会从头开始并覆盖这些数据。`}
              </p>
            </div>
          )}
        </div>

        <div className="hh-modal-foot">
          <button type="button" onClick={onClose} className="hh-btn-ghost" disabled={submitting}>
            取消
          </button>
          <button
            type="button"
            onClick={() => onStart(buildOptions(batchMode, customPerRequest, limitEnabled, chapterLimit))}
            disabled={submitting || chapterCount === 0}
            className="hh-btn-primary"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {isRerun ? '重新抽取' : '开始抽取'}
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
    return (
      <div className="hh-subpanel px-4 py-3 text-xs text-content-tertiary">
        暂无法估算请求次数（不影响启动）。
      </div>
    )
  }
  const perBatch =
    plan.batch_count > 0 ? Math.ceil(plan.target_chapters / plan.batch_count) : 0
  const ctxLabel = plan.context_window > 0 ? `${Math.round(plan.context_window / 1000)}k 上下文` : '上下文未知'
  return (
    <div className={`hh-subpanel space-y-2 px-4 py-3 text-xs leading-5 text-content-secondary ${loading ? 'opacity-60' : ''}`}>
      <p className="text-sm text-content">
        目标 <span className="font-semibold">{plan.target_chapters}</span> 章 · {MODE_LABELS[plan.mode]}
        {plan.batch_count > 1 && <>（约 {perBatch} 章/批，共 {plan.batch_count} 批）</>}
        · 预计 <span className="font-semibold text-brand">≥ {plan.estimated_llm_calls}</span> 次 LLM 调用
      </p>
      <p className="text-content-tertiary">
        拆书卡 {plan.batch_count} 次
        {plan.dictionary_calls > 0 && ` + 字典分类 ${plan.dictionary_calls} 次`}
        {plan.arc_calls > 0
          ? ` + 情节单元 ${plan.arc_calls} 次（每轮约 ${plan.arc_window} 章）+ 骨架 / 人物谱 / 文风 ${plan.post_calls - plan.arc_calls} 次`
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
