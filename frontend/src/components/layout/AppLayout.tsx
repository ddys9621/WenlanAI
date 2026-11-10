import { useCallback, useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { useUpdateAutoCheck } from '@/hooks/useUpdateAutoCheck'

/** 项目外页面的外壳（参考马良写作）：纸色顶栏（标志 · 主导航 · AI 任务 · 账户）+ 画布；窄屏主导航收进左侧抽屉。 */
export function AppLayout() {
  useUpdateAutoCheck()
  const [navOpen, setNavOpen] = useState(false)
  const closeNav = useCallback(() => setNavOpen(false), [])
  const { pathname } = useLocation()

  // 换页（含浏览器后退）就收起抽屉
  useEffect(() => {
    setNavOpen(false)
  }, [pathname])

  return (
    // 高度跟着可见视口走（dvh）：手机浏览器地址栏露出来时 100vh 比可见区高，页面底部会被挡住
    <div className="relative flex h-screen flex-col overflow-clip bg-surface supports-[height:100dvh]:h-dvh">
      <Header onMenuClick={() => setNavOpen(true)} />
      <Sidebar open={navOpen} onClose={closeNav} />
      {/* 纵向内边距放在内层容器而不是 main：sticky 的 top 以滚动容器的 content-box 为基准，
          main 若带 pt 会让页面内 sticky top-0 悬在顶部下方 pt 的距离，露出滚动内容 */}
      <main className="min-h-0 flex-1 overflow-y-auto px-4 md:px-8">
        <div className="mx-auto w-full max-w-[1400px] pb-10 pt-6 md:pt-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
