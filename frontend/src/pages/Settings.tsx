import { useState, useEffect, useCallback, useRef } from 'react'
import { settingsApi } from '@/services/api'
import type { Settings as SettingsType, SettingsUpdate, ReasoningEffort } from '@/types'
import { UpdatePanel } from '@/components/settings/UpdatePanel'
import { ALL_EFFORTS, EFFORT_LEVELS, autoBudget } from '@/components/settings/aiParams'
import { Switch } from '@/components/ui/Switch'
import { toast } from 'sonner'
import {
  Eye,
  EyeOff,
  Loader2,
  CheckCircle2,
  XCircle,
  RotateCcw,
  Save,
  Wifi,
  RefreshCw,
  Plug,
  Cpu,
  Brain,
  SlidersHorizontal,
  Info,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
} from 'lucide-react'

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'custom', label: '自定义' },
]

const DEFAULT_BASE_URLS: Record<string, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
  custom: '',
}

// 左侧分区导航
const SECTIONS = [
  { id: 'api', label: 'API 配置', icon: Plug },
  { id: 'model', label: '模型配置', icon: Cpu },
  { id: 'reasoning', label: '思考强度', icon: Brain },
  { id: 'preferences', label: '偏好设置', icon: SlidersHorizontal },
  { id: 'about', label: '关于与更新', icon: Info },
] as const

export default function Settings() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<'success' | 'error' | null>(null)
  const [testMessage, setTestMessage] = useState('')
  const [settings, setSettings] = useState<SettingsType | null>(null)
  const [models, setModels] = useState<Array<{ value: string; label: string; description: string }>>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [activeSection, setActiveSection] = useState<string>('api')
  const [showAdvancedReasoning, setShowAdvancedReasoning] = useState(false)

  // 表单状态
  const [form, setForm] = useState<SettingsUpdate>({
    api_provider: 'openai',
    api_key: '',
    api_base_url: 'https://api.openai.com/v1',
    llm_model: '',
    temperature: 0.7,
    max_tokens: 4096,
    top_p: 0.95,
    frequency_penalty: 0.3,
    presence_penalty: 0.3,
    reasoning_enabled: false,
    reasoning_effort: 'medium',
    thinking_budget_tokens: null,
    preferences: '',
  })

  // 加载设置
  useEffect(() => {
    const load = async () => {
      try {
        const data = await settingsApi.getSettings()
        setSettings(data)
        setForm({
          api_provider: data.api_provider || 'openai',
          api_key: data.api_key || '',
          api_base_url: data.api_base_url || DEFAULT_BASE_URLS[data.api_provider || 'openai'] || '',
          llm_model: data.llm_model || '',
          temperature: data.temperature ?? 0.7,
          max_tokens: data.max_tokens ?? 4096,
          top_p: data.top_p ?? 0.95,
          frequency_penalty: data.frequency_penalty ?? 0.3,
          presence_penalty: data.presence_penalty ?? 0.3,
          reasoning_enabled: data.reasoning_enabled ?? false,
          reasoning_effort: data.reasoning_effort ?? 'medium',
          thinking_budget_tokens: data.thinking_budget_tokens ?? null,
          preferences: data.preferences || '',
        })
      } catch {
        // 首次使用，无设置记录
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  // 点击导航后的平滑滚动期间忽略观察器，避免高亮被中途经过的分区抢走
  const highlightLockUntil = useRef(0)

  // 滚动监听：高亮当前分区。root 为 main 滚动容器，判定区从吸顶栏（87px）下方开始，
  // 与 scroll-mt-24 / top-24 配套；维护"当前相交集合"而非只看本批变化的条目
  useEffect(() => {
    if (loading) return
    const visible = new Set<string>()
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => (e.isIntersecting ? visible.add(e.target.id) : visible.delete(e.target.id)))
        if (Date.now() < highlightLockUntil.current) return
        const first = SECTIONS.find((s) => visible.has(s.id))
        if (first) setActiveSection(first.id)
      },
      { root: document.querySelector('main'), rootMargin: '-88px 0px -65% 0px', threshold: 0 },
    )
    SECTIONS.forEach((s) => {
      const el = document.getElementById(s.id)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [loading])

  const scrollToSection = useCallback((id: string) => {
    const el = document.getElementById(id)
    if (el) {
      highlightLockUntil.current = Date.now() + 1000
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      setActiveSection(id)
    }
  }, [])

  // 更新表单字段
  const updateField = useCallback(<K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => {
    setForm(prev => ({ ...prev, [key]: value }))
    setTestResult(null)
  }, [])

  // 切换提供商时自动填充 base url
  const handleProviderChange = useCallback((provider: string) => {
    setForm(prev => ({
      ...prev,
      api_provider: provider,
      api_base_url: DEFAULT_BASE_URLS[provider] || '',
      llm_model: '',
    }))
    setModels([])
    setTestResult(null)
  }, [])

  // 获取可用模型
  const fetchModels = useCallback(async () => {
    if (!form.api_key || !form.api_base_url || !form.api_provider) {
      toast.error('请先填写 API 提供商、Base URL 和 API Key')
      return
    }
    setLoadingModels(true)
    try {
      const res = await settingsApi.getAvailableModels({
        api_key: form.api_key,
        api_base_url: form.api_base_url,
        provider: form.api_provider,
      })
      setModels(res.models || [])
      if (res.models?.length) {
        toast.success(`获取到 ${res.models.length} 个可用模型`)
      } else {
        toast.warning('未获取到可用模型')
      }
    } catch {
      toast.error('获取模型列表失败')
    } finally {
      setLoadingModels(false)
    }
  }, [form.api_key, form.api_base_url, form.api_provider])

  // 测试连接
  const handleTestConnection = useCallback(async () => {
    if (!form.api_key || !form.api_base_url || !form.api_provider) {
      toast.error('请先填写 API 配置')
      return
    }
    setTesting(true)
    setTestResult(null)
    setTestMessage('')
    try {
      const res = await settingsApi.testApiConnection({
        api_key: form.api_key,
        api_base_url: form.api_base_url,
        provider: form.api_provider,
        llm_model: form.llm_model || '',
        max_tokens: form.max_tokens,
      })
      if (res.success) {
        setTestResult('success')
        setTestMessage(res.message || '连接成功')
      } else {
        setTestResult('error')
        setTestMessage(res.error || res.message || '连接失败')
      }
    } catch {
      setTestResult('error')
      setTestMessage('连接测试失败，请检查配置')
    } finally {
      setTesting(false)
    }
  }, [form])

  // 保存设置
  const handleSave = useCallback(async () => {
    if (!form.api_key) {
      toast.error('请填写 API Key')
      return
    }
    setSaving(true)
    try {
      const data = await settingsApi.saveSettings(form)
      setSettings(data)
      toast.success('设置已保存，已全局生效')
    } catch {
      // api 拦截器已处理 toast
    } finally {
      setSaving(false)
    }
  }, [form])

  // 重置表单
  const handleReset = useCallback(() => {
    if (settings) {
      setForm({
        api_provider: settings.api_provider || 'openai',
        api_key: settings.api_key || '',
        api_base_url: settings.api_base_url || '',
        llm_model: settings.llm_model || '',
        temperature: settings.temperature ?? 0.7,
        max_tokens: settings.max_tokens ?? 4096,
        top_p: settings.top_p ?? 0.95,
        frequency_penalty: settings.frequency_penalty ?? 0.3,
        presence_penalty: settings.presence_penalty ?? 0.3,
        reasoning_enabled: settings.reasoning_enabled ?? false,
        reasoning_effort: settings.reasoning_effort ?? 'medium',
        thinking_budget_tokens: settings.thinking_budget_tokens ?? null,
        preferences: settings.preferences || '',
      })
    } else {
      setForm({
        api_provider: 'openai',
        api_key: '',
        api_base_url: 'https://api.openai.com/v1',
        llm_model: '',
        temperature: 0.7,
        max_tokens: 4096,
        top_p: 0.95,
        frequency_penalty: 0.3,
        presence_penalty: 0.3,
        reasoning_enabled: false,
        reasoning_effort: 'medium',
        thinking_budget_tokens: null,
        preferences: '',
      })
    }
    setTestResult(null)
    setTestMessage('')
    toast.info('已重置为上次保存的设置')
  }, [settings])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-brand" />
      </div>
    )
  }

  const inputClass =
    'w-full border border-surface-border rounded-btn px-3 py-2 text-sm focus:border-brand focus:ring-2 focus:ring-brand/20 outline-none transition-colors'
  const selectClass = inputClass + ' bg-white'
  const labelClass = 'block text-sm font-medium text-content mb-1.5'
  const cardClass = 'bg-white rounded-card shadow-card p-6 scroll-mt-24'

  const isAnthropic = form.api_provider === 'anthropic'
  const isOpenAICompat = form.api_provider === 'openai' || form.api_provider === 'custom'
  const effort = (form.reasoning_effort ?? 'medium') as ReasoningEffort
  const budgetPreview = autoBudget(effort, form.max_tokens ?? 4096)

  return (
    <div className="animate-fade-in">
      {/* 吸顶操作栏：标题 + 保存/重置 */}
      <div className="sticky top-0 z-20 mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-surface-border bg-surface/85 py-4 backdrop-blur-sm">
        <div>
          <h1 className="text-xl font-bold text-content md:text-2xl">设置</h1>
          <p className="mt-0.5 text-sm text-content-secondary">配置 AI 接口、模型参数与思考强度（保存后全局生效）</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-btn border border-surface-border bg-white hover:bg-surface-hover transition-colors"
            onClick={handleReset}
          >
            <RotateCcw className="w-4 h-4" />
            重置
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 px-5 py-2 text-sm font-medium rounded-btn bg-brand hover:bg-brand-600 text-white transition-colors disabled:opacity-50"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            保存设置
          </button>
        </div>
      </div>

      {/* 两栏：左侧分区导航 + 右侧内容 */}
      <div className="grid gap-6 lg:grid-cols-[212px_minmax(0,1fr)]">
        {/* 左侧导航（吸顶） */}
        <aside className="hidden lg:block">
          <nav className="sticky top-24 space-y-1">
            {SECTIONS.map((s) => {
              const Icon = s.icon
              const active = activeSection === s.id
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => scrollToSection(s.id)}
                  className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-sm transition-colors ${
                    active
                      ? 'bg-brand/10 font-medium text-brand'
                      : 'text-content-secondary hover:bg-surface-hover hover:text-content'
                  }`}
                >
                  <Icon className={`h-4 w-4 shrink-0 ${active ? 'text-brand' : 'text-content-tertiary'}`} />
                  {s.label}
                </button>
              )
            })}
          </nav>
        </aside>

        {/* 右侧内容 */}
        <div className="min-w-0 space-y-6 pb-12">
          {/* API 配置区 */}
          <section id="api" className={cardClass}>
            <h2 className="text-lg font-semibold text-content mb-4">API 配置</h2>
            <div className="space-y-4">
              {/* 提供商 */}
              <div>
                <label className={labelClass}>API 提供商</label>
                <select
                  className={selectClass}
                  value={form.api_provider}
                  onChange={e => handleProviderChange(e.target.value)}
                >
                  {PROVIDERS.map(p => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </div>

              {/* Base URL */}
              <div>
                <label className={labelClass}>API Base URL</label>
                <input
                  type="text"
                  className={inputClass}
                  placeholder="https://api.openai.com/v1"
                  value={form.api_base_url}
                  onChange={e => updateField('api_base_url', e.target.value)}
                />
              </div>

              {/* API Key */}
              <div>
                <label className={labelClass}>API Key</label>
                <div className="relative">
                  <input
                    type={showApiKey ? 'text' : 'password'}
                    className={inputClass + ' pr-10'}
                    placeholder="sk-..."
                    value={form.api_key}
                    onChange={e => updateField('api_key', e.target.value)}
                  />
                  <button
                    type="button"
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-secondary transition-colors"
                    onClick={() => setShowApiKey(v => !v)}
                    aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'}
                  >
                    {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* 测试连接 */}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-btn border border-surface-border hover:bg-surface-hover transition-colors disabled:opacity-50"
                  onClick={handleTestConnection}
                  disabled={testing}
                >
                  {testing ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Wifi className="w-4 h-4" />
                  )}
                  测试连接
                </button>
                {testResult && (
                  <span className={`inline-flex items-center gap-1 text-sm ${testResult === 'success' ? 'text-green-600' : 'text-red-500'}`}>
                    {testResult === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                    {testMessage}
                  </span>
                )}
              </div>
            </div>
          </section>

          {/* 模型配置区 */}
          <section id="model" className={cardClass}>
            <h2 className="text-lg font-semibold text-content mb-4">模型配置</h2>
            <div className="space-y-4">
              {/* LLM 模型 */}
              <div>
                <label className={labelClass}>LLM 模型</label>
                <div className="flex gap-2">
                  <select
                    className={selectClass + ' flex-1'}
                    value={form.llm_model}
                    onChange={e => updateField('llm_model', e.target.value)}
                  >
                    <option value="">请选择模型</option>
                    {models.map(m => (
                      <option key={m.value} value={m.value}>
                        {m.label}
                      </option>
                    ))}
                    {/* 如果当前值不在列表中，也显示 */}
                    {form.llm_model && !models.find(m => m.value === form.llm_model) && (
                      <option value={form.llm_model}>{form.llm_model}</option>
                    )}
                  </select>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 px-3 py-2 text-sm rounded-btn border border-surface-border hover:bg-surface-hover transition-colors disabled:opacity-50"
                    onClick={fetchModels}
                    disabled={loadingModels}
                    title="刷新模型列表"
                  >
                    {loadingModels ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <RefreshCw className="w-4 h-4" />
                    )}
                  </button>
                </div>
                {form.llm_model && models.find(m => m.value === form.llm_model)?.description && (
                  <p className="text-xs text-content-tertiary mt-1">
                    {models.find(m => m.value === form.llm_model)?.description}
                  </p>
                )}
              </div>

              {/* Temperature */}
              <div>
                <label className={labelClass}>
                  Temperature
                  <span className="ml-2 text-content-tertiary font-normal">{form.temperature}</span>
                </label>
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.1}
                  className="w-full accent-brand disabled:opacity-50"
                  value={form.temperature}
                  disabled={isAnthropic && !!form.reasoning_enabled}
                  onChange={e => updateField('temperature', parseFloat(e.target.value))}
                />
                <div className="flex justify-between text-xs text-content-tertiary mt-0.5">
                  <span>精确 (0)</span>
                  <span>创意 (2)</span>
                </div>
                {isAnthropic && form.reasoning_enabled && (
                  <p className="mt-1 text-xs text-amber-600">
                    Claude 启用思考时温度将由接口强制为默认值（1），此处设置暂不生效。
                  </p>
                )}
              </div>

              {/* Max Tokens */}
              <div>
                <label className={labelClass}>Max Tokens</label>
                <input
                  type="number"
                  className={inputClass}
                  min={1}
                  max={128000}
                  value={form.max_tokens}
                  onChange={e => updateField('max_tokens', parseInt(e.target.value) || 4096)}
                />
              </div>

              {/* 采样多样性（降低 AI 味） */}
              <div className="border-t border-surface-border pt-4">
                <h3 className="text-sm font-semibold text-content">采样多样性（降低「AI 味」）</h3>
                <p className="mt-1 text-xs text-content-tertiary">
                  提高用词与句式多样性、抑制重复套路句，可显著降低被 AI 检测器（如朱雀）判定的概率。
                  全局生效——对世界观 / 角色等 JSON 结构化生成也会应用，建议惩罚值保持温和（0.3~0.6）。
                  推荐正文创作：top_p≈0.9、frequency≈0.4、presence≈0.4。
                </p>
              </div>

              {/* Top P */}
              <div>
                <label className={labelClass}>
                  Top P（核采样）
                  <span className="ml-2 text-content-tertiary font-normal">{form.top_p}</span>
                </label>
                <input
                  type="range"
                  min={0.1}
                  max={1}
                  step={0.05}
                  className="w-full accent-brand"
                  value={form.top_p}
                  onChange={e => updateField('top_p', parseFloat(e.target.value))}
                />
                <div className="flex justify-between text-xs text-content-tertiary mt-0.5">
                  <span>收敛 (0.1)</span>
                  <span>不裁剪 (1)</span>
                </div>
                <p className="mt-1 text-xs text-content-tertiary">=1 时不做核采样。与 Temperature 一般只重点调其一。</p>
              </div>

              {/* Frequency Penalty */}
              <div>
                <label className={labelClass}>
                  Frequency Penalty（频率惩罚）
                  <span className="ml-2 text-content-tertiary font-normal">{form.frequency_penalty}</span>
                </label>
                <input
                  type="range"
                  min={-2}
                  max={2}
                  step={0.1}
                  className="w-full accent-brand"
                  value={form.frequency_penalty}
                  onChange={e => updateField('frequency_penalty', parseFloat(e.target.value))}
                />
                <div className="flex justify-between text-xs text-content-tertiary mt-0.5">
                  <span>允许重复 (-2)</span>
                  <span>强抑制重复 (2)</span>
                </div>
                <p className="mt-1 text-xs text-content-tertiary">越高越少重复用词。仅 OpenAI 兼容接口生效，Anthropic 忽略。</p>
              </div>

              {/* Presence Penalty */}
              <div>
                <label className={labelClass}>
                  Presence Penalty（存在惩罚）
                  <span className="ml-2 text-content-tertiary font-normal">{form.presence_penalty}</span>
                </label>
                <input
                  type="range"
                  min={-2}
                  max={2}
                  step={0.1}
                  className="w-full accent-brand"
                  value={form.presence_penalty}
                  onChange={e => updateField('presence_penalty', parseFloat(e.target.value))}
                />
                <div className="flex justify-between text-xs text-content-tertiary mt-0.5">
                  <span>不鼓励新词 (-2)</span>
                  <span>强鼓励新词 (2)</span>
                </div>
                <p className="mt-1 text-xs text-content-tertiary">越高越鼓励引入新词与话题。仅 OpenAI 兼容接口生效，Anthropic 忽略。</p>
              </div>
            </div>
          </section>

          {/* 思考强度区 */}
          <section id="reasoning" className={cardClass}>
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="flex items-center gap-2 text-lg font-semibold text-content">
                  <Brain className="h-5 w-5 text-brand" />
                  思考强度
                </h2>
                <p className="mt-1 text-sm text-content-secondary">
                  仅对支持推理的模型生效（OpenAI GPT-5 / o 系列、Claude 4 等）。开启后模型会先“思考”再作答，质量更高但更慢、更耗 token。
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2 pt-1">
                <span className="text-sm text-content-secondary">{form.reasoning_enabled ? '已启用' : '关闭'}</span>
                <Switch
                  checked={!!form.reasoning_enabled}
                  onChange={v => updateField('reasoning_enabled', v)}
                  label="启用思考/推理"
                />
              </div>
            </div>

            {form.reasoning_enabled && (
              <div className="mt-5 space-y-5 border-t border-surface-border pt-5">
                {/* 统一档位 */}
                <div>
                  <label className={labelClass}>强度档位</label>
                  <div className="grid grid-cols-3 gap-2">
                    {EFFORT_LEVELS.map((lvl) => {
                      const active = effort === lvl.value
                      return (
                        <button
                          key={lvl.value}
                          type="button"
                          onClick={() => updateField('reasoning_effort', lvl.value)}
                          className={`flex flex-col items-center gap-0.5 border px-3 py-2.5 text-sm transition-colors ${
                            active
                              ? 'border-brand bg-brand/10 text-brand font-medium'
                              : 'border-surface-border text-content-secondary hover:border-brand/40 hover:bg-surface-hover'
                          }`}
                        >
                          <span>{lvl.label}</span>
                          <span className={`text-[11px] ${active ? 'text-brand/80' : 'text-content-tertiary'}`}>{lvl.hint}</span>
                        </button>
                      )
                    })}
                  </div>
                  {!EFFORT_LEVELS.some((l) => l.value === effort) && (
                    <p className="mt-1.5 text-xs text-content-tertiary">
                      当前使用高级取值：<span className="font-medium text-content-secondary">{effort}</span>
                    </p>
                  )}
                </div>

                {/* 生效说明（按当前提供商） */}
                {isOpenAICompat && (
                  <p className="flex items-start gap-2 bg-surface px-3 py-2 text-xs text-content-secondary">
                    <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" />
                    OpenAI / 兼容网关：将以 <code className="font-mono">reasoning_effort={effort}</code> 发送。请确认所选模型为推理模型，否则接口可能报错。
                  </p>
                )}
                {isAnthropic && (
                  <p className="flex items-start gap-2 bg-surface px-3 py-2 text-xs text-content-secondary">
                    <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" />
                    Claude：将启用 extended thinking，思考预算{' '}
                    <span className="font-medium text-content">
                      {form.thinking_budget_tokens && form.thinking_budget_tokens > 0
                        ? `${form.thinking_budget_tokens} tokens（手动）`
                        : budgetPreview
                          ? `约 ${budgetPreview} tokens（按档位自动）`
                          : '无法启用（Max Tokens 太小）'}
                    </span>
                    ，且计入 Max Tokens。
                  </p>
                )}

                {/* 高级设置 */}
                <div>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 text-sm text-content-secondary hover:text-content"
                    onClick={() => setShowAdvancedReasoning(v => !v)}
                  >
                    {showAdvancedReasoning ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    高级设置（分提供商精确控制）
                  </button>

                  {showAdvancedReasoning && (
                    <div className="mt-3 space-y-4 border border-surface-border p-4">
                      {/* OpenAI 精确强度 */}
                      <div>
                        <label className={labelClass}>OpenAI reasoning_effort（精确取值）</label>
                        <select
                          className={selectClass}
                          value={effort}
                          onChange={e => updateField('reasoning_effort', e.target.value as ReasoningEffort)}
                        >
                          {ALL_EFFORTS.map(o => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                        <p className="mt-1 text-xs text-content-tertiary">
                          与上方档位联动；此处可选 minimal / xhigh / max 等更细粒度取值。
                        </p>
                      </div>

                      {/* Claude 思考预算 */}
                      <div>
                        <label className={labelClass}>Claude 思考预算 budget_tokens</label>
                        <input
                          type="number"
                          className={inputClass}
                          min={1024}
                          step={512}
                          placeholder={budgetPreview ? `留空则按档位自动（约 ${budgetPreview}）` : '按档位自动'}
                          value={form.thinking_budget_tokens ?? ''}
                          onChange={e => {
                            const v = e.target.value.trim()
                            updateField('thinking_budget_tokens', v === '' ? null : parseInt(v) || null)
                          }}
                        />
                        <p className="mt-1 text-xs text-content-tertiary">
                          须 ≥ 1024 且小于 Max Tokens（当前 {form.max_tokens}）；留空则按强度档位自动换算。超出会被自动夹取。
                        </p>
                        {(form.thinking_budget_tokens ?? 0) > 0 &&
                          (form.thinking_budget_tokens ?? 0) >= (form.max_tokens ?? 4096) && (
                            <p className="mt-1 flex items-start gap-1.5 text-xs text-amber-600">
                              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                              预算不小于 Max Tokens，实际会被夹取到 {(form.max_tokens ?? 4096) - 1}，可能导致正文过短。
                            </p>
                          )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>

          {/* 偏好设置区 */}
          <section id="preferences" className={cardClass}>
            <h2 className="text-lg font-semibold text-content mb-4">偏好设置</h2>
            <div>
              <label className={labelClass}>自定义偏好（JSON 或文本）</label>
              <textarea
                className={inputClass + ' min-h-[100px] resize-y'}
                placeholder='例如：{"language": "zh-CN", "style": "concise"}'
                value={form.preferences}
                onChange={e => updateField('preferences', e.target.value)}
              />
              <p className="text-xs text-content-tertiary mt-1">
                可填写自定义偏好参数，将在 AI 生成时作为额外上下文传入
              </p>
            </div>
          </section>

          {/* 关于与更新（独立于上面的表单，不受保存/重置影响） */}
          <div id="about" className="scroll-mt-24">
            <UpdatePanel />
          </div>
        </div>
      </div>
    </div>
  )
}
