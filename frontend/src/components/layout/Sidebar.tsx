/**
 * 窄屏（< lg）的导航抽屉：顶栏放不下主导航时，点左上角菜单从左边滑出；
 * 点链接、点遮罩、按 Esc 都会收起（换页时 AppLayout 也会收起）。宽屏不渲染，导航在顶栏中间。
 */
import { useEffect } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { BrandLogo } from '@/components/ui/BrandLogo'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { navGroupsFor, useVersionStatus } from './appNav'

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const isAdmin = !!useCurrentUser()?.is_admin
  const { hasUpdate } = useVersionStatus()

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div className="absolute inset-0 bg-content/30 animate-fade-in" onClick={onClose} aria-hidden />
      <aside className="app-drawer absolute inset-y-0 left-0 flex w-64 max-w-[84vw] flex-col border-r border-surface-border bg-surface-paper shadow-xl" aria-label="导航">
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-surface-border-light px-4">
          <Link to="/" onClick={onClose} className="flex min-w-0 flex-1 items-center gap-2.5">
            <BrandLogo size="sm" className="shrink-0" />
            <span className="truncate font-serif text-[17px] font-semibold text-content">文澜 AI</span>
          </Link>
          <button type="button" onClick={onClose} className="hh-icon-btn-plain rounded-full" aria-label="收起导航">
            <X className="h-4 w-4" />
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-2" aria-label="主导航">
          {navGroupsFor(isAdmin).map((group) => (
            <div key={group.label} className="mb-2">
              <p className="px-3 pb-1.5 pt-3 text-[11px] font-medium tracking-[0.16em] text-content-tertiary">{group.label}</p>
              <ul className="space-y-0.5">
                {group.items.map((item) => (
                  <li key={item.path}>
                    <NavLink
                      to={item.path}
                      onClick={onClose}
                      className={({ isActive }) => cn(
                        'flex h-10 items-center gap-3 rounded-lg px-3 text-[14px] text-content-secondary hover:bg-white hover:text-content',
                        isActive && 'bg-white font-medium text-content shadow-xs',
                      )}
                    >
                      <item.icon className="h-[18px] w-[18px] shrink-0" />
                      <span className="flex-1 truncate">{item.label}</span>
                      {hasUpdate && item.path === '/settings' && (
                        <span className="shrink-0 rounded-full bg-signal-soft px-1.5 py-0.5 text-[10px] font-medium text-cinnabar">新版本</span>
                      )}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </aside>
    </div>
  )
}
