/**
 * 登录表单（登录弹窗里用）：按后台开着的登录方式出切换条——账号登录 / 邮箱登录（可注册）/ Linux.do 授权。
 * 登录成功调 onSuccess，由外面决定去哪；Linux.do 是整页跳去授权，回调由后端设 Cookie 后 302 到书架。
 */
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { ExternalLink, Loader2, Lock, User } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { authApi } from '@/services/api'
import { EmailAuthForm } from '@/components/auth/EmailAuthForm'
import type { AuthConfig } from '@/types'

const FIELD_ICON_CLASS =
  'pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary transition-colors peer-focus:text-brand'

type Method = 'local' | 'email' | 'linuxdo'

const METHOD_LABELS: Record<Method, string> = {
  local: '账号登录',
  email: '邮箱登录',
  linuxdo: 'Linux.do',
}

function availableMethods(config: AuthConfig | null): Method[] {
  if (!config) return []
  const methods: Method[] = []
  if (config.local_auth_enabled) methods.push('local')
  if (config.email_login_enabled) methods.push('email')
  if (config.linuxdo_login_enabled) methods.push('linuxdo')
  return methods
}

export function LoginPanel({ onSuccess }: { onSuccess: () => void }) {
  const [loading, setLoading] = useState(true)
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [method, setMethod] = useState<Method>('local')
  const methods = useMemo(() => availableMethods(config), [config])

  useEffect(() => {
    let cancelled = false
    authApi.getAuthConfig()
      .then((cfg) => {
        if (cancelled) return
        setConfig(cfg)
        setMethod(availableMethods(cfg)[0] ?? 'local')
      })
      .catch(() => { if (!cancelled) toast.error('获取认证配置失败') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  if (loading) {
    return (
      <div className="flex flex-col items-center gap-3 py-10 text-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand" />
        <p className="text-sm text-content-secondary">正在读取登录方式…</p>
      </div>
    )
  }

  return (
    <div>
      {methods.length > 1 && (
        <div className="mt-6 grid gap-1 rounded-full border border-surface-border bg-surface-paper p-1" style={{ gridTemplateColumns: `repeat(${methods.length}, minmax(0, 1fr))` }} role="tablist" aria-label="登录方式">
          {methods.map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={method === m}
              onClick={() => setMethod(m)}
              className={cn(
                'h-9 rounded-full text-sm font-medium transition-colors',
                method === m ? 'bg-brand text-white shadow-xs' : 'text-content-secondary hover:bg-white hover:text-content',
              )}
            >
              {METHOD_LABELS[m]}
            </button>
          ))}
        </div>
      )}

      {methods.length === 0 ? (
        <p className="hh-subpanel mt-6 px-4 py-3 text-center text-sm text-content-secondary">暂未开启任何登录方式，请联系管理员</p>
      ) : method === 'local' ? (
        <LocalLoginForm compact={methods.length > 1} onSuccess={onSuccess} />
      ) : method === 'email' ? (
        <EmailAuthForm compact={methods.length > 1} registerEnabled={config?.email_register_enabled ?? false} onSuccess={onSuccess} />
      ) : (
        <LinuxDOLogin compact={methods.length > 1} registerEnabled={config?.linuxdo_register_enabled ?? false} />
      )}
    </div>
  )
}

function LocalLoginForm({ compact, onSuccess }: { compact: boolean; onSuccess: () => void }) {
  const [loading, setLoading] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) {
      toast.error('请输入用户名和密码')
      return
    }
    setLoading(true)
    try {
      const res = await authApi.localLogin(username, password)
      if (res.success) {
        toast.success('登录成功')
        onSuccess()
      }
    } catch {
      // api 拦截器已处理 toast
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className={compact ? 'mt-5' : 'mt-7'}>
      <div className="space-y-3">
        <div className="relative">
          <label htmlFor="login-username" className="sr-only">用户名</label>
          <input
            id="login-username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="用户名"
            autoComplete="username"
            autoFocus
            className="hh-field peer h-12 pl-11"
          />
          <User className={FIELD_ICON_CLASS} />
        </div>
        <div className="relative">
          <label htmlFor="login-password" className="sr-only">密码</label>
          <input
            id="login-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="密码"
            autoComplete="current-password"
            className="hh-field peer h-12 pl-11"
          />
          <Lock className={FIELD_ICON_CLASS} />
        </div>
      </div>
      <button type="submit" disabled={loading} className="hh-btn-primary mt-6 h-12 w-full rounded-full text-[15px]">
        {loading ? <><Loader2 className="h-4 w-4 animate-spin" />登录中…</> : '登录'}
      </button>
      <p className="mt-4 text-center text-xs text-content-tertiary">首次登录将自动创建账号</p>
    </form>
  )
}

function LinuxDOLogin({ compact, registerEnabled }: { compact: boolean; registerEnabled: boolean }) {
  const [loading, setLoading] = useState(false)

  const handleLogin = async () => {
    setLoading(true)
    try {
      const res = await authApi.getLinuxDOAuthUrl()
      window.location.href = res.auth_url
    } catch {
      // api 拦截器已处理 toast
      setLoading(false)
    }
  }

  return (
    <div className={compact ? 'mt-5' : 'mt-7'}>
      <button type="button" onClick={handleLogin} disabled={loading} className="hh-btn-primary h-12 w-full rounded-full text-[15px]">
        {loading ? <><Loader2 className="h-4 w-4 animate-spin" />跳转中…</> : <><ExternalLink className="h-4 w-4" />使用 Linux.do 登录</>}
      </button>
      <p className="mt-4 text-center text-xs text-content-tertiary">
        {registerEnabled ? '将跳转到 Linux.do 授权，首次授权自动创建账号' : '将跳转到 Linux.do 授权；当前未开放注册，仅已有账号可登录'}
      </p>
    </div>
  )
}
