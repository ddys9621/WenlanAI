/**
 * 顶栏右上角的账户菜单（参考马良写作）：头像按钮，点开一块面板——头像、名字、账号；版本卡片（有新版本时朱砂字，点了去设置页）；
 * 设置 / 修改密码 / 运行日志（桌面版）/ 退出登录。修改密码的弹窗也在这里。
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, KeyRound, LogOut, ScrollText, Settings, Shield, X, type LucideIcon } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { authApi } from '@/services/api'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { useDesktopApi } from '@/hooks/useDesktopApi'
import { useDismiss } from '@/hooks/useDismiss'
import type { User } from '@/types'
import { useVersionStatus } from './appNav'

function Avatar({ user, size }: { user: User | null; size: 'sm' | 'md' }) {
  const box = size === 'sm' ? 'h-8 w-8 text-[14px]' : 'h-10 w-10 text-[16px]'
  if (user?.avatar_url) return <img src={user.avatar_url} alt="" className={cn('shrink-0 rounded-full object-cover', box)} />
  const initial = Array.from((user?.display_name || user?.username || '').trim())[0]?.toUpperCase() || '文'
  return (
    <span className={cn('flex shrink-0 items-center justify-center rounded-full bg-brand-100 font-serif font-semibold text-brand-600', box)} aria-hidden>
      {initial}
    </span>
  )
}

const rowClass = 'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-content hover:bg-surface-hover'

function Row({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <>
      <Icon className="h-4 w-4 text-content-secondary" />
      <span className="flex-1">{children}</span>
    </>
  )
}

export function AccountMenu() {
  const user = useCurrentUser()
  const navigate = useNavigate()
  const desktop = useDesktopApi()
  const { currentVersion, hasUpdate, updateLabel, runMode, upToDate } = useVersionStatus()
  const [open, setOpen] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useDismiss(ref, open, () => setOpen(false))
  const name = user?.display_name || user?.username || '用户'

  const handleLogout = async () => {
    setOpen(false)
    try {
      await authApi.logout()
      toast.success('已退出登录')
      navigate('/')
    } catch {
      toast.error('退出失败，请重试')
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="账户菜单"
        title={name}
        className={cn('relative flex rounded-full p-0.5 ring-1 ring-surface-border transition-shadow hover:ring-brand/40', open && 'ring-2 ring-brand/40')}
      >
        <Avatar user={user} size="sm" />
        {hasUpdate && <span className="absolute right-0 top-0 h-2.5 w-2.5 rounded-full bg-signal ring-2 ring-surface-paper" title="有新版本可用" />}
      </button>

      {open && (
        <div role="menu" aria-label="账户" className="absolute right-0 top-full z-40 mt-2 w-72 rounded-2xl border border-surface-border-light bg-white p-2 shadow-lg animate-scale-in">
          <div className="flex items-center gap-3 px-2 pb-3 pt-1.5">
            <Avatar user={user} size="md" />
            <div className="min-w-0 flex-1">
              <p className="flex min-w-0 items-center gap-1.5">
                <span className="truncate text-sm font-semibold text-content">{name}</span>
                {user?.is_admin && (
                  <span className="hh-tag shrink-0 px-1.5 py-0.5 text-[10px]">
                    <Shield className="h-3 w-3" />
                    管理员
                  </span>
                )}
              </p>
              <p className="truncate text-xs text-content-tertiary">{user?.username || '未命名用户'}</p>
            </div>
          </div>

          {currentVersion && (
            <Link
              to="/settings"
              role="menuitem"
              onClick={() => setOpen(false)}
              title={updateLabel ? `${updateLabel}，去设置页更新` : '去设置页查看版本与更新'}
              className="mx-0.5 mb-1 block rounded-xl border border-surface-border-light bg-surface-paper px-3.5 py-3 transition-colors hover:border-brand/30"
            >
              <span className="flex items-center justify-between text-[11px] text-content-tertiary">
                <span>文澜 AI{runMode && ` · ${runMode}`}</span>
                {upToDate && <span>已是最新</span>}
              </span>
              <span className="mt-1.5 flex items-center justify-between gap-2">
                <span className="font-serif text-[20px] font-semibold leading-none text-content tabular-nums">v{currentVersion}</span>
                {updateLabel && (
                  <span className="inline-flex min-w-0 items-center gap-1 text-[12px] font-medium text-cinnabar">
                    <i className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-signal" aria-hidden />
                    <span className="truncate">{updateLabel}</span>
                  </span>
                )}
              </span>
            </Link>
          )}

          <div className="my-1 h-px bg-surface-border-light" role="separator" />
          <Link to="/settings" role="menuitem" onClick={() => setOpen(false)} className={rowClass}>
            <Row icon={Settings}>设置</Row>
          </Link>
          <button type="button" role="menuitem" onClick={() => { setOpen(false); setPasswordOpen(true) }} className={rowClass}>
            <Row icon={KeyRound}>修改密码</Row>
          </button>
          {desktop && (
            <button type="button" role="menuitem" onClick={() => { setOpen(false); void desktop.open_logs() }} className={rowClass}>
              <Row icon={ScrollText}>运行日志</Row>
            </button>
          )}
          <div className="my-1 h-px bg-surface-border-light" role="separator" />
          <button type="button" role="menuitem" onClick={handleLogout} className={cn(rowClass, 'text-cinnabar hover:bg-cinnabar-wash')}>
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      )}

      {passwordOpen && <PasswordModal onClose={() => setPasswordOpen(false)} />}
    </div>
  )
}

function PasswordModal({ onClose }: { onClose: () => void }) {
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(true)
  const [hasPassword, setHasPassword] = useState(false)

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)

  useEffect(() => {
    authApi.getPasswordStatus()
      .then((res) => setHasPassword(res.has_custom_password))
      .catch(() => toast.error('获取密码状态失败'))
      .finally(() => setChecking(false))
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (newPassword.length < 6) {
      toast.error('新密码至少 6 个字符')
      return
    }
    if (newPassword !== confirmPassword) {
      toast.error('两次输入的密码不一致')
      return
    }

    setLoading(true)
    try {
      await authApi.setPassword(newPassword)
      toast.success('密码修改成功')
      onClose()
    } catch {
      toast.error('密码修改失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  return createPortal(
    <div className="hh-modal-mask" onClick={onClose}>
      <div className="hh-modal max-w-[420px]" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div>
            <p className="hh-eyebrow">账号安全</p>
            <h3 className="mt-2 text-xl font-semibold tracking-tight text-content">{hasPassword ? '修改密码' : '设置密码'}</h3>
            <p className="mt-1 text-sm text-content-secondary">为你的创作账号设置更安全的访问方式。</p>
          </div>
          <button onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>

        {checking ? (
          <div className="px-7 py-12 text-center text-sm text-content-secondary">正在检查密码状态...</div>
        ) : (
          <form onSubmit={handleSubmit} className="flex min-h-0 flex-col">
            <div className="hh-modal-body space-y-4">
              <PasswordField
                label="新密码"
                value={newPassword}
                onChange={setNewPassword}
                visible={showNew}
                onToggle={() => setShowNew((v) => !v)}
                placeholder="至少 6 个字符"
              />
              <PasswordField
                label="确认密码"
                value={confirmPassword}
                onChange={setConfirmPassword}
                visible={showConfirm}
                onToggle={() => setShowConfirm((v) => !v)}
                placeholder="再次输入新密码"
              />
            </div>

            <div className="hh-modal-foot">
              <button type="button" onClick={onClose} className="hh-btn-ghost">
                取消
              </button>
              <button type="submit" disabled={loading} className="hh-btn-primary">
                {loading ? '提交中...' : '确认保存'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>,
    document.body,
  )
}

function PasswordField({
  label,
  value,
  onChange,
  visible,
  onToggle,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  visible: boolean
  onToggle: () => void
  placeholder?: string
}) {
  return (
    <div>
      <label className="hh-label">{label}</label>
      <div className="relative">
        <input
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          required
          className="hh-field pr-11"
        />
        <button
          type="button"
          onClick={onToggle}
          className="absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center text-content-tertiary hover:text-content-secondary"
          aria-label={visible ? '隐藏密码' : '显示密码'}
        >
          {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </div>
  )
}
