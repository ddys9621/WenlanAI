/**
 * 全局顶栏（书架、拆书参考、知识库、设置等项目外页面，参考马良写作）：左边标志回首页，中间主导航，
 * 右边 新版本提示 · AI 任务 · 账户菜单。窄屏（< lg）主导航收进左侧抽屉（Sidebar），这里只留菜单按钮。
 */
import { Link, NavLink } from 'react-router-dom'
import { Menu } from 'lucide-react'
import { cn } from '@/lib/utils'
import { BrandLogo } from '@/components/ui/BrandLogo'
import { AIJobTray } from '@/components/ai-job/AIJobTray'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { AccountMenu } from './AccountMenu'
import { navGroupsFor, useVersionStatus } from './appNav'

export function Header({ onMenuClick }: { onMenuClick: () => void }) {
  const isAdmin = !!useCurrentUser()?.is_admin
  const { hasUpdate, updateLabel } = useVersionStatus()
  const items = navGroupsFor(isAdmin).flatMap((group) => group.items)

  return (
    <header className="relative z-30 h-14 shrink-0 border-b border-surface-border-light bg-surface-paper">
      <div className="mx-auto flex h-full w-full max-w-[1400px] items-center gap-4 px-4 md:px-8">
        <div className="flex min-w-0 flex-1 basis-0 items-center gap-1.5">
          <button
            type="button"
            onClick={onMenuClick}
            className="-ml-1.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-content-secondary hover:bg-white hover:text-content lg:hidden"
            aria-label="打开导航"
          >
            <Menu className="h-5 w-5" />
          </button>
          <Link to="/" className="group flex min-w-0 items-center gap-2.5" title="回到首页">
            <BrandLogo size="sm" className="shrink-0 transition-transform duration-300 group-hover:-rotate-6" />
            <span className="truncate font-serif text-[17px] font-semibold text-content">文澜 AI</span>
          </Link>
        </div>

        <nav className="hidden shrink-0 items-center gap-0.5 lg:flex" aria-label="主导航">
          {items.map((item) => (
            <NavLink key={item.path} to={item.path} className={({ isActive }) => cn('app-nav-link', isActive && 'app-nav-link--active')}>
              <span className="relative">
                <item.icon className="h-4 w-4" />
                {hasUpdate && item.path === '/settings' && (
                  <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-signal ring-2 ring-surface-paper" aria-label="有新版本可用" />
                )}
              </span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="flex min-w-max flex-1 basis-0 items-center justify-end gap-2">
          {updateLabel && (
            <Link
              to="/settings"
              title={`${updateLabel}，去设置页更新`}
              className="hidden h-8 items-center gap-1.5 rounded-full border border-signal/30 bg-signal-soft/60 px-3 text-[12px] font-medium text-cinnabar transition-colors hover:border-signal/50 xl:inline-flex"
            >
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-signal" aria-hidden />
              {updateLabel}
            </Link>
          )}
          <AIJobTray className="h-9 rounded-full" />
          <AccountMenu />
        </div>
      </div>
    </header>
  )
}
