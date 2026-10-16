import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutGrid,
  Settings,
  Puzzle,
  Users,
  PanelLeftClose,
  PanelLeft,
  BookOpen,
  BookMarked,
  ScrollText,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { BrandLogo } from '@/components/ui/BrandLogo'
import { useUpdateStore } from '@/store/updateStore'
import { useDesktopApi } from '@/hooks/useDesktopApi'

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
      { icon: BookMarked, label: '知识库', path: '/knowledge' },
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

/** 全局墨绿图标栏（参考岚笺 activity bar）：选中项左侧朱砂条 + 右上切角。 */
export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  // 根路径 `/` 也渲染项目列表，需让「我的项目」保持高亮
  const isRootProjects = useLocation().pathname === '/'
  // 有新版本时「设置」入口出红点（检查逻辑在 useUpdateAutoCheck / 设置页）；检查更新仅管理员可见
  const info = useUpdateStore((s) => s.info)
  const hasUpdate = useUpdateStore((s) => s.hasUpdate) && !!info?.can_manage
  const result = useUpdateStore((s) => s.result)
  const currentVersion = info?.current_version ?? result?.current_version ?? null
  // 桌面版（exe 窗口）才有：打开后台运行日志小窗口
  const desktop = useDesktopApi()
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
        'fixed left-0 top-0 z-40 h-screen overflow-hidden transition-[width] duration-200',
        collapsed ? 'w-16' : 'w-56',
      )}
    >
      <div className="lj-rail">
        <div className={cn('flex h-12 shrink-0 items-center gap-2.5 border-b border-sidebar-border px-3', collapsed && 'justify-center px-0')}>
          <BrandLogo size="sm" />
          {!collapsed && (
            <div className="min-w-0">
              <p className="truncate font-serif text-[15px] font-semibold text-sidebar-text-active">文澜</p>
              <p className="truncate text-[10px] tracking-[0.12em] text-sidebar-text/70">长篇小说创作台</p>
            </div>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-2">
          {navGroups.map((group) => (
            <div key={group.label} className="mb-2">
              {!collapsed && <p className="lj-rail-caption">{group.label}</p>}
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const forceActive = isRootProjects && item.path === '/projects'
                  return (
                    <li key={item.path}>
                      <NavLink
                        to={item.path}
                        title={collapsed ? item.label : undefined}
                        className={({ isActive }) =>
                          cn('lj-rail-item group', collapsed && 'justify-center px-0', (isActive || forceActive) && 'lj-rail-item--active')
                        }
                      >
                        <span className="relative shrink-0">
                          <item.icon className="h-[18px] w-[18px]" />
                          {hasUpdate && item.path === '/settings' && (
                            <span
                              className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-signal ring-2 ring-sidebar"
                              title="有新版本可用"
                              aria-label="有新版本可用"
                            />
                          )}
                        </span>
                        {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
                        {!collapsed && hasUpdate && item.path === '/settings' && (
                          <span className="shrink-0 rounded-sm bg-signal/20 px-1.5 py-0.5 text-[10px] font-medium text-[#f3b6a6]">新版本</span>
                        )}
                      </NavLink>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="shrink-0 border-t border-sidebar-border p-2">
          {/* 版本行：常驻显示当前版本；有新版本时整行变为可点的提示，进入设置页更新 */}
          {currentVersion && (
            <NavLink
              to="/settings"
              title={updateLabel ? `${updateLabel}，点击前往更新` : `当前版本 v${currentVersion}`}
              className={cn(
                'mb-1 flex items-center gap-2 rounded-sm px-3 py-1.5 text-[11px] hover:bg-sidebar-hover',
                collapsed && 'justify-center px-0',
                updateLabel ? 'text-[#f3b6a6]' : 'text-sidebar-text/70',
              )}
            >
              <span className="relative inline-flex shrink-0">
                <span className="tabular-nums">v{currentVersion}</span>
                {updateLabel && collapsed && (
                  <span className="absolute -right-2 top-0 h-1.5 w-1.5 rounded-full bg-signal" aria-hidden />
                )}
              </span>
              {!collapsed && (
                updateLabel ? (
                  <span className="flex min-w-0 flex-1 items-center gap-1.5">
                    <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-signal" aria-hidden />
                    <span className="truncate font-medium">{updateLabel}</span>
                  </span>
                ) : (
                  <span className="truncate">{info?.run_mode === 'source' ? '源码运行' : info?.run_mode === 'docker' ? 'Docker' : info?.run_mode === 'exe' ? '安装版' : ''}</span>
                )
              )}
            </NavLink>
          )}
          {desktop && (
            <button
              onClick={() => void desktop.open_logs()}
              className={cn('lj-rail-item', collapsed && 'justify-center px-0')}
              title={collapsed ? '运行日志' : undefined}
            >
              <ScrollText className="h-[18px] w-[18px] shrink-0" />
              {!collapsed && <span>运行日志</span>}
            </button>
          )}
          <button
            onClick={onToggle}
            className={cn('lj-rail-item', collapsed && 'justify-center px-0')}
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
      </div>
    </aside>
  )
}
