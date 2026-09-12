import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutGrid,
  Settings,
  Puzzle,
  Users,
  PanelLeftClose,
  PanelLeft,
  BookOpen,
  Library,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { BrandLogo } from '@/components/ui/BrandLogo'
import { useUpdateStore } from '@/store/updateStore'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

const navGroups = [
  {
    label: '创作台',
    items: [
      { icon: LayoutGrid, label: '我的项目', path: '/projects' },
      { icon: BookOpen, label: '拆书参考', path: '/book-dissect' },
      { icon: Library, label: '参考库', path: '/reference-packs' },
      { icon: Settings, label: '设置', path: '/settings' },
      { icon: Puzzle, label: 'MCP 插件', path: '/mcp-plugins' },
    ],
  },
  {
    label: '管理台',
    items: [
      { icon: Users, label: '用户管理', path: '/user-management' },
    ],
  },
]

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  // 根路径 `/` 也渲染项目列表，需让「我的项目」保持高亮
  const isRootProjects = useLocation().pathname === '/'
  // 有新版本时「设置」入口出红点（检查逻辑在 useUpdateAutoCheck / 设置页）；检查更新仅管理员可见
  const info = useUpdateStore((s) => s.info)
  const hasUpdate = useUpdateStore((s) => s.hasUpdate) && !!info?.can_manage
  const result = useUpdateStore((s) => s.result)
  const currentVersion = info?.current_version ?? result?.current_version ?? null
  // 底部版本行的"新版本"文案：exe/docker 看 Release 版本，源码看落后提交数
  const updateLabel = !hasUpdate || !result
    ? null
    : result.run_mode === 'source'
      ? `远端有 ${result.git?.behind ?? 0} 个新提交`
      : result.latest
        ? `新版本 v${result.latest.version}`
        : '有新版本'

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 flex h-screen flex-col overflow-hidden border-r border-white/80 bg-white/55 backdrop-blur-2xl backdrop-saturate-150 shadow-[0_0_0_1px_rgba(15,43,96,0.04),20px_0_60px_-44px_rgba(15,43,96,0.35)] transition-all duration-200',
        collapsed ? 'w-16' : 'w-60'
      )}
    >
      <div className={cn('flex h-16 shrink-0 items-center gap-3 border-b border-surface-border/80 px-4', collapsed && 'justify-center px-0')}>
        <BrandLogo size="sm" />
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold tracking-tight text-content">文澜 AI</p>
            <p className="truncate text-[11px] text-content-tertiary">专业小说创作平台</p>
          </div>
        )}
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-2.5 py-5">
        {navGroups.map((group) => (
          <div key={group.label}>
            {!collapsed && (
              <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.22em] text-content-tertiary">
                {group.label}
              </p>
            )}
            <ul className="space-y-1">
              {group.items.map((item) => {
                const forceActive = isRootProjects && item.path === '/projects'
                return (
                <li key={item.path}>
                  <NavLink
                    to={item.path}
                    className={({ isActive }) =>
                      cn(
                        'group relative flex items-center gap-3 px-3 py-2.5 text-sm transition-all',
                        collapsed && 'justify-center px-0',
                        isActive || forceActive
                          ? 'bg-brand/10 font-medium text-brand'
                          : 'text-content-secondary hover:bg-white/70 hover:text-content'
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {(isActive || forceActive) && <span className="absolute inset-y-2 left-0 w-[3px] bg-brand" aria-hidden />}
                        <span className="relative shrink-0">
                          <item.icon className="h-[18px] w-[18px]" />
                          {hasUpdate && item.path === '/settings' && (
                            <span
                              className="absolute -right-1 -top-1 h-2 w-2 bg-red-500 ring-2 ring-white"
                              title="有新版本可用"
                              aria-label="有新版本可用"
                            />
                          )}
                        </span>
                        {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
                        {!collapsed && hasUpdate && item.path === '/settings' && (
                          <span className="shrink-0 bg-red-500/10 px-1.5 py-0.5 text-[10px] font-medium text-red-600">新版本</span>
                        )}
                        {collapsed && (
                          <span className="hh-glass pointer-events-none absolute left-full ml-3 hidden whitespace-nowrap px-2.5 py-1.5 text-xs text-content group-hover:block">
                            {item.label}
                          </span>
                        )}
                      </>
                    )}
                  </NavLink>
                </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-surface-border/80 p-2.5">
        {/* 版本行：常驻显示当前版本；有新版本时整行变为可点的提示，进入设置页更新 */}
        {currentVersion && (
          <NavLink
            to="/settings"
            title={updateLabel ? `${updateLabel}，点击前往更新` : `当前版本 v${currentVersion}`}
            className={cn(
              'mb-1 flex items-center gap-2 px-3 py-1.5 text-[11px] transition-colors hover:bg-white/70',
              collapsed && 'justify-center px-0',
              updateLabel ? 'text-red-600' : 'text-content-tertiary'
            )}
          >
            <span className="relative inline-flex shrink-0">
              <span className="tabular-nums">v{currentVersion}</span>
              {updateLabel && collapsed && (
                <span className="absolute -right-2 top-0 h-1.5 w-1.5 bg-red-500" aria-hidden />
              )}
            </span>
            {!collapsed && (
              updateLabel ? (
                <span className="flex min-w-0 flex-1 items-center gap-1.5">
                  <span className="h-1.5 w-1.5 shrink-0 animate-pulse bg-red-500" aria-hidden />
                  <span className="truncate font-medium">{updateLabel}</span>
                </span>
              ) : (
                <span className="truncate">{info?.run_mode === 'source' ? '源码运行' : info?.run_mode === 'docker' ? 'Docker' : info?.run_mode === 'exe' ? '安装版' : ''}</span>
              )
            )}
          </NavLink>
        )}
        <button
          onClick={onToggle}
          className={cn(
            'flex w-full items-center gap-3 px-3 py-2.5 text-sm text-content-secondary transition-colors hover:bg-white/70 hover:text-content',
            collapsed && 'justify-center px-0'
          )}
          title={collapsed ? '展开侧栏' : '收起侧栏'}
        >
          {collapsed ? (
            <PanelLeft className="h-[18px] w-[18px] shrink-0" />
          ) : (
            <>
              <PanelLeftClose className="h-[18px] w-[18px] shrink-0" />
              <span>收起侧栏</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
