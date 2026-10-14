import { useState, useCallback } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { cn } from '@/lib/utils'
import { useUpdateAutoCheck } from '@/hooks/useUpdateAutoCheck'

/** 全局外壳：左侧墨绿图标栏 + 纸色顶栏 + 纸色画布（参考岚笺）。 */
export function AppLayout() {
  useUpdateAutoCheck()
  const [collapsed, setCollapsed] = useState(() => {
    return localStorage.getItem('sidebar-collapsed') === 'true'
  })

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev
      localStorage.setItem('sidebar-collapsed', String(next))
      return next
    })
  }, [])

  return (
    <div className="relative flex h-screen overflow-clip bg-surface">
      {!collapsed && (
        <div
          className="fixed inset-0 z-30 bg-content/30 md:hidden"
          onClick={toggle}
        />
      )}

      <Sidebar collapsed={collapsed} onToggle={toggle} />

      <div
        className={cn(
          'relative flex min-w-0 flex-1 flex-col transition-[margin] duration-200',
          collapsed ? 'ml-16' : 'ml-56',
          'max-md:ml-0'
        )}
      >
        <Header onMenuClick={toggle} />
        {/* 纵向内边距放在内层容器而不是 main：sticky 的 top 以滚动容器的 content-box 为基准，
            main 若带 pt 会让页面内 sticky top-0 悬在顶部下方 pt 的距离，露出滚动内容 */}
        <main className="flex-1 overflow-y-auto px-4 md:px-8">
          <div className="mx-auto w-full max-w-[1400px] pb-8 pt-6 md:pt-7">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
