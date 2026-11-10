import { useState, useEffect, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { authApi } from '@/services/api'
import { AnnouncementGate } from '@/components/AnnouncementGate'
import { AIJobHost } from '@/components/ai-job/AIJobHost'
import { PageLoading } from '@/components/ui/PageLoading'
import { CurrentUserContext, useCurrentUser } from '@/hooks/useCurrentUser'
import { sessionManager } from '@/utils/sessionManager'
import { loginHref } from '@/utils/loginRoute'
import type { User } from '@/types'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [user, setUser] = useState<User | null>(null)
  const location = useLocation()

  useEffect(() => {
    let cancelled = false

    authApi.getCurrentUser()
      .then((current) => {
        if (cancelled) return
        sessionManager.start()
        setUser(current)
      })
      .catch(() => {
        if (cancelled) return
        sessionManager.stop()
        setUser(null)
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  if (loading) return <PageLoading />
  if (!user) {
    // 登录是首页上的弹窗；带上查询参数（如 /projects?panel=inspiration），登录完回到原样
    return <Navigate to={loginHref(location.pathname + location.search)} replace />
  }
  // 公告弹窗只在登录后出现；同一浏览器会话关过就不再弹（见 AnnouncementGate）
  // AI 任务弹窗 + 后台任务同步也放在登录确认之后：避免未登录时多打一次 401（会重复弹"未授权"提示）
  return (
    <CurrentUserContext.Provider value={user}>
      {children}
      <AnnouncementGate />
      <AIJobHost />
    </CurrentUserContext.Provider>
  )
}

/** 管理员页面：放在 ProtectedRoute 里面用；普通用户直接打开地址也回项目列表 */
export function AdminRoute({ children }: { children: ReactNode }) {
  return useCurrentUser()?.is_admin ? <>{children}</> : <Navigate to="/projects" replace />
}
