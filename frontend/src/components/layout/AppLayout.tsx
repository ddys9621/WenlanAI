import { useState, useCallback } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { cn } from '@/lib/utils'
import { useUpdateAutoCheck } from '@/hooks/useUpdateAutoCheck'

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

  // 外壳用 overflow-clip 而不是 overflow-hidden：hidden 仍是滚动容器，光斑（-bottom-48）溢出的 192px
  // 会让 scrollIntoView / focus() 把整个外壳连顶栏一起滚上去且无法滚回；clip 不可滚动
  return (
    <div className="relative flex h-screen overflow-clip">
      <div className="hh-orb -left-40 -top-40 h-[520px] w-[520px] bg-brand/15 animate-float-soft" />
      <div className="hh-orb -bottom-48 right-[-120px] h-[560px] w-[560px] bg-brand-400/15" />

      {!collapsed && (
        <div
          className="fixed inset-0 z-30 bg-content/25 backdrop-blur-sm md:hidden"
          onClick={toggle}
        />
      )}

      <Sidebar collapsed={collapsed} onToggle={toggle} />

      <div
        className={cn(
          'relative flex flex-1 flex-col transition-all duration-200',
          collapsed ? 'ml-16' : 'ml-60',
          'max-md:ml-0'
        )}
      >
        <Header onMenuClick={toggle} />
        {/* 纵向内边距放在内层容器而不是 main：sticky 的 top 以滚动容器的 content-box 为基准，
            main 若带 pt 会让页面内 sticky top-0 悬在顶部下方 pt 的距离，露出滚动内容 */}
        <main className="flex-1 overflow-y-auto px-4 md:px-8">
          <div className="mx-auto w-full max-w-[1400px] pb-8 pt-6 md:pt-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
