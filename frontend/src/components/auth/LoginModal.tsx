/**
 * 登录弹窗（首页上，地址带 ?login=1 时打开）：毛玻璃遮罩 + 居中卡片；Esc、点遮罩、右上角 × 都能关；打开时锁住页面滚动。
 * 卡片里是 LoginPanel，上面一句「登录后接着做什么」。
 */
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { BrandLogo } from '@/components/ui/BrandLogo'
import { LoginPanel } from './LoginPanel'

export function LoginModal({ open, next, onClose, onSuccess }: {
  open: boolean
  /** 登录后接着做的事（如「用灵感开新书」） */
  next: string
  onClose: () => void
  onSuccess: () => void
}) {
  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previous
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose, open])

  if (!open || typeof document === 'undefined') return null
  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center overflow-y-auto px-4 py-10">
      <div className="absolute inset-0 animate-fade-in bg-[#1d2420]/35 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="login-dialog-title"
        className="login-dialog relative w-full max-w-[400px] animate-scale-in overflow-hidden rounded-[20px] border border-white/60 bg-surface-paper px-7 pb-8 pt-9 shadow-[0_40px_90px_-30px_rgba(29,36,32,0.55)] md:px-9"
      >
        <div className="pointer-events-none absolute -top-24 left-1/2 h-48 w-72 -translate-x-1/2 rounded-full bg-brand/15 blur-3xl" aria-hidden />
        <button onClick={onClose} className="absolute right-3.5 top-3.5 flex h-9 w-9 items-center justify-center rounded-full text-content-tertiary transition-colors hover:bg-white hover:text-content" aria-label="关闭">
          <X className="h-[18px] w-[18px]" />
        </button>
        <div className="relative flex flex-col items-center text-center">
          <BrandLogo size="lg" />
          <h2 id="login-dialog-title" className="mt-4 font-serif text-[22px] font-semibold text-content">登录文澜 AI</h2>
          <p className="mt-1.5 text-[13px] text-content-secondary">登录后{next}</p>
        </div>
        <div className="relative">
          <LoginPanel onSuccess={onSuccess} />
        </div>
      </div>
    </div>,
    document.body,
  )
}
