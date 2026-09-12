import { useState, useEffect, useMemo, type FormEvent, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { User, Lock, Loader2, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { authApi } from '@/services/api'
import { BrandLogo } from '@/components/ui/BrandLogo'
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

// 后端 OAuth 回调失败时 302 到 /login?error=<code>
const LOGIN_ERROR_MESSAGES: Record<string, string> = {
  linuxdo_disabled: 'Linux.do 登录未开启',
  oauth_denied: 'Linux.do 授权被取消或失败',
  invalid_state: '授权已失效，请重新发起登录',
  token_failed: 'Linux.do 授权失败（获取令牌失败），请重试',
  userinfo_failed: 'Linux.do 授权失败（获取用户信息失败），请重试',
  register_disabled: '当前未开放 Linux.do 注册，请联系管理员',
  user_disabled: '账号已被禁用，请联系管理员',
}

function LoginShell({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4 py-10">
      <div className="hh-orb left-[calc(50%-460px)] top-[calc(50%-460px)] h-[520px] w-[520px] bg-brand/20 animate-float-soft" />
      <div className="hh-orb left-[calc(50%-60px)] top-[calc(50%-40px)] h-[560px] w-[560px] bg-brand-400/25" />

      <div className="hh-glass z-10 w-full max-w-[400px] px-8 py-10 md:px-10">{children}</div>
    </div>
  )
}

function availableMethods(config: AuthConfig | null): Method[] {
  if (!config) return []
  const methods: Method[] = []
  if (config.local_auth_enabled) methods.push('local')
  if (config.email_login_enabled) methods.push('email')
  if (config.linuxdo_login_enabled) methods.push('linuxdo')
  return methods
}

export default function Login() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const redirectTo = searchParams.get('redirect') || '/'

  const [checking, setChecking] = useState(true)
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [method, setMethod] = useState<Method>('local')

  const methods = useMemo(() => availableMethods(config), [config])

  // OAuth 回调带回来的错误码只提示一次，然后从地址栏清掉
  useEffect(() => {
    const error = searchParams.get('error')
    if (!error) return
    toast.error(LOGIN_ERROR_MESSAGES[error] ?? '登录失败，请重试')
    const next = new URLSearchParams(searchParams)
    next.delete('error')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  useEffect(() => {
    const init = async () => {
      try {
        await authApi.getCurrentUser()
        navigate(redirectTo, { replace: true })
        return
      } catch {
        // 未登录，继续
      }

      try {
        const cfg = await authApi.getAuthConfig()
        setConfig(cfg)
        setMethod(availableMethods(cfg)[0] ?? 'local')
      } catch {
        toast.error('获取认证配置失败')
      } finally {
        setChecking(false)
      }
    }

    init()
  }, [navigate, redirectTo])

  const goHome = () => navigate(redirectTo, { replace: true })

  if (checking) {
    return (
      <LoginShell>
        <div className="flex flex-col items-center gap-4 py-4 text-center">
          <Loader2 className="h-6 w-6 animate-spin text-brand" />
          <p className="text-sm text-content-secondary">正在校验登录状态…</p>
        </div>
      </LoginShell>
    )
  }

  return (
    <LoginShell>
      <div className="flex flex-col items-center text-center">
        <BrandLogo size="lg" />
        <h1 className="mt-5 text-2xl font-semibold tracking-tight text-content">文澜 AI</h1>
        <p className="mt-1.5 text-sm text-content-secondary">登录以继续创作</p>
      </div>

      {methods.length > 1 && (
        <div className="mt-8 grid gap-1 border border-surface-border bg-white/60 p-1" style={{ gridTemplateColumns: `repeat(${methods.length}, minmax(0, 1fr))` }}>
          {methods.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMethod(m)}
              className={`h-9 text-sm font-medium transition-colors ${
                method === m ? 'bg-brand text-white' : 'text-content-secondary hover:bg-brand/5 hover:text-content'
              }`}
            >
              {METHOD_LABELS[m]}
            </button>
          ))}
        </div>
      )}

      {methods.length === 0 ? (
        <p className="hh-subpanel mt-8 px-4 py-3 text-center text-sm text-content-secondary">
          暂未开启任何登录方式，请联系管理员
        </p>
      ) : method === 'local' ? (
        <LocalLoginForm compact={methods.length > 1} onSuccess={goHome} />
      ) : method === 'email' ? (
        <EmailAuthForm compact={methods.length > 1} registerEnabled={config?.email_register_enabled ?? false} onSuccess={goHome} />
      ) : (
        <LinuxDOLogin compact={methods.length > 1} registerEnabled={config?.linuxdo_register_enabled ?? false} />
      )}
    </LoginShell>
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
    <form onSubmit={handleSubmit} className={compact ? 'mt-5' : 'mt-8'}>
      <div className="space-y-3">
        <div className="relative">
          <label htmlFor="username" className="sr-only">
            用户名
          </label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="用户名"
            autoComplete="username"
            className="hh-field peer h-12 pl-11"
          />
          <User className={FIELD_ICON_CLASS} />
        </div>

        <div className="relative">
          <label htmlFor="password" className="sr-only">
            密码
          </label>
          <input
            id="password"
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

      <button type="submit" disabled={loading} className="hh-btn-primary mt-6 h-12 w-full text-[15px]">
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            登录中…
          </>
        ) : (
          '登录'
        )}
      </button>

      <p className="mt-5 text-center text-xs text-content-tertiary">首次登录将自动创建账号</p>
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
    <div className={compact ? 'mt-5' : 'mt-8'}>
      <button type="button" onClick={handleLogin} disabled={loading} className="hh-btn-primary h-12 w-full text-[15px]">
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            跳转中…
          </>
        ) : (
          <>
            <ExternalLink className="h-4 w-4" />
            使用 Linux.do 登录
          </>
        )}
      </button>

      <p className="mt-5 text-center text-xs text-content-tertiary">
        {registerEnabled ? '将跳转到 Linux.do 授权，首次授权自动创建账号' : '将跳转到 Linux.do 授权；当前未开放注册，仅已有账号可登录'}
      </p>
    </div>
  )
}
