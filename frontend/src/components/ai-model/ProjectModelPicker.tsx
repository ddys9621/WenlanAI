import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, ChevronUp, Cpu, Loader2, RotateCcw, Save, X } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { projectAIPreferenceApi, settingsApi } from '@/services/api'
import type { AIModelOption, EffectiveAIConfig, ProjectAIOverrides, ProjectAIPreference, ReasoningEffort } from '@/types'
import { countActiveOverrides, modelChipLabel, normalizeOverrides } from '@/utils/projectAIOverrides'
import { ALL_EFFORTS, EFFORT_LEVELS, autoBudget } from '@/components/settings/aiParams'
import { Switch } from '@/components/ui/Switch'
import { ModelListPicker } from '@/components/ai-model/ModelListPicker'

/**
 * 项目顶栏的「模型」chip：显示本项目实际生效的模型；点开可在设置页那套接口下为本项目覆盖模型与参数。
 * 保存后本项目内所有 AI 生成（向导 / 角色 / 大纲 / 桥段 / 正文 / 分析 / 仿写…）立即按覆盖值走
 * （请求带 X-Project-Id，后端 get_user_ai_service 合并）。
 */
export function ProjectModelPicker({ projectId }: { projectId: string }) {
  const [pref, setPref] = useState<ProjectAIPreference | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    setPref(null)
    projectAIPreferenceApi
      .get(projectId)
      .then((p) => {
        if (!cancelled) setPref(p)
      })
      .catch(() => {
        /* 拦截器已 toast */
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  const active = countActiveOverrides(pref?.overrides)

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={!pref}
        className={cn('hh-chip max-w-[260px]', active > 0 && 'hh-chip--active')}
        title="本项目使用的 AI 模型与参数（接口复用「设置」页配置）"
      >
        <Cpu className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{pref ? modelChipLabel(pref.effective) : '模型…'}</span>
        {active > 0 && <span className="shrink-0 bg-white/25 px-1.5 text-[10px]">覆盖 {active}</span>}
      </button>
      {open && pref && (
        <ProjectModelDialog
          projectId={projectId}
          pref={pref}
          onClose={() => setOpen(false)}
          onSaved={(p) => {
            setPref(p)
            setOpen(false)
          }}
        />
      )}
    </>
  )
}

type SliderKey = 'temperature' | 'top_p' | 'frequency_penalty' | 'presence_penalty'

const SLIDERS: { key: SliderKey; label: string; min: number; max: number; step: number; hint: string }[] = [
  { key: 'temperature', label: 'Temperature', min: 0, max: 2, step: 0.1, hint: '越高越有创意，越低越稳定。' },
  { key: 'top_p', label: 'Top P（核采样）', min: 0.1, max: 1, step: 0.05, hint: '=1 不裁剪；与 Temperature 一般只重点调其一。' },
  { key: 'frequency_penalty', label: 'Frequency Penalty', min: -2, max: 2, step: 0.1, hint: '越高越少重复用词。仅 OpenAI 兼容接口生效。' },
  { key: 'presence_penalty', label: 'Presence Penalty', min: -2, max: 2, step: 0.1, hint: '越高越鼓励新词与话题。仅 OpenAI 兼容接口生效。' },
]

function fmt(v: number | boolean | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '未设置'
  if (typeof v === 'boolean') return v ? '开启' : '关闭'
  return String(v)
}

/** 一个可「跟随全局」的覆盖项：勾上 = 该字段为 null，用设置页的值 */
function OverrideField({
  label,
  following,
  globalText,
  onToggle,
  hint,
  children,
}: {
  label: string
  following: boolean
  globalText: string
  onToggle: (follow: boolean) => void
  hint?: string
  children: ReactNode
}) {
  return (
    <div className={cn('border p-3', following ? 'border-surface-border bg-white/40' : 'border-brand/40 bg-white/70')}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-content">{label}</span>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-content-secondary">
          <input type="checkbox" className="accent-brand" checked={following} onChange={(e) => onToggle(e.target.checked)} />
          跟随全局{following ? `（${globalText}）` : ''}
        </label>
      </div>
      {!following && <div className="mt-2.5">{children}</div>}
      {hint && <p className="mt-1.5 text-xs text-content-tertiary">{hint}</p>}
    </div>
  )
}

type SetOverride = <K extends keyof ProjectAIOverrides>(key: K, value: ProjectAIOverrides[K]) => void

function ProjectModelDialog({
  projectId,
  pref,
  onClose,
  onSaved,
}: {
  projectId: string
  pref: ProjectAIPreference
  onClose: () => void
  onSaved: (p: ProjectAIPreference) => void
}) {
  const g: EffectiveAIConfig = pref.global_defaults
  const [form, setForm] = useState<ProjectAIOverrides>({ ...pref.overrides })
  const [models, setModels] = useState<AIModelOption[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)

  const set: SetOverride = useCallback((key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }, [])

  const fetchModels = useCallback(async () => {
    setLoadingModels(true)
    try {
      const res = await settingsApi.getSavedModels()
      setModels(res.models || [])
    } catch {
      /* 拦截器已 toast；仍可手动输入模型名 */
    } finally {
      setLoadingModels(false)
    }
  }, [])

  useEffect(() => {
    void fetchModels()
  }, [fetchModels])

  const handleSave = async () => {
    setSaving(true)
    try {
      const saved = await projectAIPreferenceApi.save(projectId, normalizeOverrides(form))
      toast.success('已保存：本项目内所有 AI 生成将使用该模型与参数')
      onSaved(saved)
    } catch {
      /* 拦截器已 toast */
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    setResetting(true)
    try {
      const saved = await projectAIPreferenceApi.reset(projectId)
      toast.success('已恢复为跟随全局设置')
      onSaved(saved)
    } catch {
      /* 拦截器已 toast */
    } finally {
      setResetting(false)
    }
  }

  const isAnthropic = g.api_provider === 'anthropic'
  const effectiveMaxTokens = form.max_tokens ?? g.max_tokens ?? 4096
  const effort = (form.reasoning_effort ?? g.reasoning_effort ?? 'medium') as ReasoningEffort
  const reasoningOn = form.reasoning_enabled ?? g.reasoning_enabled ?? false
  const budgetAuto = autoBudget(effort, effectiveMaxTokens)

  return createPortal(
    <div className="hh-modal-mask" onClick={onClose}>
      <div className="hh-modal max-w-[640px]" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div className="min-w-0">
            <p className="hh-eyebrow">
              <Cpu className="h-3.5 w-3.5" />
              本项目 AI 模型
            </p>
            <h3 className="mt-2 text-xl font-semibold tracking-tight text-content">模型与参数</h3>
            <p className="mt-1 text-sm text-content-secondary">
              接口复用「设置」页：<span className="font-medium text-content">{g.api_provider ?? '—'}</span>
              {g.api_base_url ? ` · ${g.api_base_url}` : ''}。此处的覆盖只对本项目内的 AI 生成生效；勾选「跟随全局」的项使用设置页的值。
            </p>
          </div>
          <button onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="hh-modal-body space-y-3">
          {/* 模型 */}
          <OverrideField
            label="模型"
            following={form.llm_model === null}
            globalText={fmt(g.llm_model)}
            onToggle={(follow) => set('llm_model', follow ? null : (g.llm_model ?? ''))}
            hint="从已保存接口拉取的列表里选，或直接输入模型名（部分网关不提供列表）。"
          >
            <ModelListPicker
              value={form.llm_model ?? ''}
              onChange={(v) => set('llm_model', v)}
              models={models}
              loading={loadingModels}
              onRefresh={fetchModels}
            />
          </OverrideField>

          {/* Temperature */}
          {SLIDERS.slice(0, 1).map((s) => (
            <SliderField key={s.key} s={s} value={form[s.key]} globalValue={g[s.key]} set={set} />
          ))}

          {/* Max Tokens */}
          <OverrideField
            label="Max Tokens"
            following={form.max_tokens === null}
            globalText={fmt(g.max_tokens)}
            onToggle={(follow) => set('max_tokens', follow ? null : (g.max_tokens ?? 4096))}
            hint="清空即回到跟随全局。"
          >
            <input
              type="number"
              min={1}
              max={128000}
              className="hh-field border border-surface-border bg-white"
              value={form.max_tokens ?? ''}
              onChange={(e) => set('max_tokens', parseInt(e.target.value) || null)}
            />
          </OverrideField>

          {/* Top P / 惩罚 */}
          {SLIDERS.slice(1).map((s) => (
            <SliderField key={s.key} s={s} value={form[s.key]} globalValue={g[s.key]} set={set} />
          ))}

          {/* 思考 / 推理 */}
          <OverrideField
            label="思考 / 推理"
            following={form.reasoning_enabled === null}
            globalText={fmt(g.reasoning_enabled)}
            onToggle={(follow) => set('reasoning_enabled', follow ? null : (g.reasoning_enabled ?? false))}
            hint="仅推理模型生效（OpenAI GPT-5 / o 系列、Claude 4 等）。本项目关闭时，下方强度 / 预算不生效。"
          >
            <div className="flex items-center gap-3">
              <Switch checked={reasoningOn} onChange={(v) => set('reasoning_enabled', v)} label="本项目启用思考" />
              <span className="text-sm text-content-secondary">{reasoningOn ? '已启用' : '关闭'}</span>
            </div>
          </OverrideField>

          {reasoningOn && (
            <OverrideField
              label="思考强度"
              following={form.reasoning_effort === null}
              globalText={fmt(g.reasoning_effort)}
              onToggle={(follow) => set('reasoning_effort', follow ? null : (g.reasoning_effort ?? 'medium'))}
            >
              <div className="grid grid-cols-3 gap-2">
                {EFFORT_LEVELS.map((lvl) => {
                  const on = effort === lvl.value
                  return (
                    <button
                      key={lvl.value}
                      type="button"
                      onClick={() => set('reasoning_effort', lvl.value)}
                      className={cn(
                        'flex flex-col items-center gap-0.5 border px-3 py-2 text-sm transition-colors',
                        on ? 'border-brand bg-brand/10 font-medium text-brand' : 'border-surface-border text-content-secondary hover:border-brand/40',
                      )}
                    >
                      <span>{lvl.label}</span>
                      <span className={cn('text-[11px]', on ? 'text-brand/80' : 'text-content-tertiary')}>{lvl.hint}</span>
                    </button>
                  )
                })}
              </div>
              <button
                type="button"
                className="mt-2 inline-flex items-center gap-1 text-xs text-content-secondary hover:text-content"
                onClick={() => setShowAdvanced((v) => !v)}
              >
                {showAdvanced ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                精确取值（OpenAI reasoning_effort）
              </button>
              {showAdvanced && (
                <select
                  className="hh-field mt-2 border border-surface-border bg-white"
                  value={effort}
                  onChange={(e) => set('reasoning_effort', e.target.value as ReasoningEffort)}
                >
                  {ALL_EFFORTS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              )}
            </OverrideField>
          )}

          {reasoningOn && isAnthropic && (
            <OverrideField
              label="Claude 思考预算 budget_tokens"
              following={form.thinking_budget_tokens === null}
              globalText={g.thinking_budget_tokens ? String(g.thinking_budget_tokens) : `按档位自动，约 ${budgetAuto ?? '—'}`}
              onToggle={(follow) => set('thinking_budget_tokens', follow ? null : (g.thinking_budget_tokens ?? budgetAuto ?? 1024))}
              hint={`须 ≥ 1024 且小于 Max Tokens（当前生效 ${effectiveMaxTokens}）；超出会被后端自动夹取。清空即回到跟随全局。`}
            >
              <input
                type="number"
                min={1024}
                step={512}
                className="hh-field border border-surface-border bg-white"
                value={form.thinking_budget_tokens ?? ''}
                onChange={(e) => set('thinking_budget_tokens', parseInt(e.target.value) || null)}
              />
            </OverrideField>
          )}
        </div>

        <div className="hh-modal-foot">
          <button
            type="button"
            onClick={handleReset}
            disabled={resetting || saving}
            className="hh-btn-ghost mr-auto text-red-500 hover:bg-red-50 hover:text-red-600"
          >
            {resetting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
            全部恢复跟随全局
          </button>
          <button type="button" onClick={onClose} className="hh-btn-ghost">
            取消
          </button>
          <button type="button" onClick={handleSave} disabled={saving || resetting} className="hh-btn-primary">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            保存
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function SliderField({
  s,
  value,
  globalValue,
  set,
}: {
  s: (typeof SLIDERS)[number]
  value: number | null
  globalValue: number | null
  set: SetOverride
}) {
  return (
    <OverrideField
      label={s.label}
      following={value === null}
      globalText={fmt(globalValue)}
      onToggle={(follow) => set(s.key, follow ? null : (globalValue ?? s.min))}
      hint={s.hint}
    >
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={s.min}
          max={s.max}
          step={s.step}
          className="flex-1 accent-brand"
          value={value ?? s.min}
          onChange={(e) => set(s.key, parseFloat(e.target.value))}
        />
        <span className="w-12 text-right text-sm tabular-nums text-content">{value ?? s.min}</span>
      </div>
    </OverrideField>
  )
}
