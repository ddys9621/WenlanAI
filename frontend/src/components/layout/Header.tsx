import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  User as UserIcon,
  LogOut,
  KeyRound,
  Shield,
  X,
  Eye,
  EyeOff,
  Menu,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import { toast } from 'sonner'
import { authApi } from '@/services/api'
import { AIJobTray } from '@/components/ai-job/AIJobTray'
import type { User } from '@/types'

interface HeaderProps {
  onMenuClick?: () => void
}

const ROUTE_META: Array<{ match: RegExp; title: string }> = [
  { match: /^\/(projects?)?$/, title: '我的项目' },
  { match: /^\/book-dissect/, title: '拆书参考' },
  { match: /^\/reference-packs/, title: '参考库' },
  { match: /^\/settings$/, title: '设置' },
  { match: /^\/mcp-plugins$/, title: 'MCP 插件' },
  { match: /^\/user-management$/, title: '用户管理' },
]

export function Header({ onMenuClick }: HeaderProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [user, setUser] = useState<User | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [passwordModalOpen, setPasswordModalOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    authApi.getCurrentUser()
      .then(setUser)
      .catch(() => { /* 静默处理，未登录时不显示用户信息 */ })
  }, [])

  useEffect(() => {
    if (!menuOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [menuOpen])

  const handleLogout = useCallback(async () => {
    try {
      await authApi.logout()
      toast.success('已退出登录')
      navigate('/login')
    } catch {
      toast.error('退出失败，请重试')
    }
  }, [navigate])

  const openPasswordModal = () => {
    setMenuOpen(false)
    setPasswordModalOpen(true)
  }

  const pageTitle = useMemo(
    () => ROUTE_META.find((item) => item.match.test(location.pathname))?.title ?? '创作工作台',
    [location.pathname],
  )

  return (
    <header className="relative z-20 flex h-16 shrink-0 items-center justify-between gap-4 border-b border-white/80 bg-white/45 px-4 backdrop-blur-xl md:px-8">
      <div className="flex min-w-0 items-center gap-3">
        <button
          onClick={onMenuClick}
          className="hh-icon-btn md:hidden"
          aria-label="切换侧栏"
        >
          <Menu className="h-5 w-5" />
        </button>

        <nav className="flex min-w-0 items-center gap-1.5 text-sm" aria-label="面包屑">
          <span className="hidden text-content-tertiary sm:inline">创作台</span>
          <ChevronRight className="hidden h-3.5 w-3.5 text-content-tertiary sm:inline" />
          <span className="truncate font-medium text-content">{pageTitle}</span>
        </nav>
      </div>

      <div className="flex shrink-0 items-center gap-2">
      <AIJobTray />
      <div className="relative" ref={menuRef}>
        <button
          onClick={() => setMenuOpen((prev) => !prev)}
          className="flex items-center gap-2.5 border border-transparent py-1 pl-1 pr-2 hover:border-surface-border hover:bg-white/70"
        >
          {user?.avatar_url ? (
            <img src={user.avatar_url} alt="" className="h-8 w-8 object-cover" />
          ) : (
            <span className="flex h-8 w-8 items-center justify-center bg-brand/10 text-brand">
              <UserIcon className="h-4 w-4" />
            </span>
          )}
          <span className="hidden max-w-[140px] truncate text-sm font-medium text-content md:inline">
            {user?.display_name || '用户'}
          </span>
          <ChevronDown className="h-4 w-4 text-content-tertiary" />
        </button>

        {menuOpen && (
          <div className="hh-menu absolute right-0 top-full mt-2 w-[240px]">
            <div className="flex items-center gap-3 px-3 py-3">
              {user?.avatar_url ? (
                <img src={user.avatar_url} alt="" className="h-10 w-10 object-cover" />
              ) : (
                <span className="flex h-10 w-10 items-center justify-center bg-brand/10 text-brand">
                  <UserIcon className="h-5 w-5" />
                </span>
              )}
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <p className="truncate text-sm font-semibold text-content">{user?.display_name || '用户'}</p>
                  {user?.is_admin && (
                    <span className="hh-tag px-1.5 py-0.5 text-[10px]">
                      <Shield className="h-3 w-3" />
                      管理员
                    </span>
                  )}
                </div>
                <p className="truncate text-xs text-content-tertiary">{user?.username || '未命名用户'}</p>
              </div>
            </div>

            <div className="my-1 h-px bg-surface-border/80" />

            <button onClick={openPasswordModal} className="hh-menu-item">
              <KeyRound className="h-4 w-4 text-content-secondary" />
              修改密码
            </button>
            <button onClick={handleLogout} className="hh-menu-item text-red-500 hover:bg-red-50">
              <LogOut className="h-4 w-4" />
              退出登录
            </button>
          </div>
        )}
      </div>
      </div>

      {passwordModalOpen && (
        <PasswordModal onClose={() => setPasswordModalOpen(false)} />
      )}
    </header>
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
