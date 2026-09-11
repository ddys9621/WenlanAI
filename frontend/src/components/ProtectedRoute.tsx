import { useState, useEffect, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { authApi } from '@/services/api'
import { AnnouncementGate } from '@/components/AnnouncementGate'
import { AIJobHost } from '@/components/ai-job/AIJobHost'
import { PageLoading } from '@/components/ui/PageLoading'
import { sessionManager } from '@/utils/sessionManager'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [authenticated, setAuthenticated] = useState(false)
  const location = useLocation()

  useEffect(() => {
    let cancelled = false

    authApi.getCurrentUser()
      .then(() => {
        if (cancelled) return
        sessionManager.start()
        setAuthenticated(true)
      })
      .catch(() => {
        if (cancelled) return
        sessionManager.stop()
        setAuthenticated(false)
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
  if (!authenticated) {
    return <Navigate to={`/login?redirect=${encodeURIComponent(location.pathname)}`} replace />
  }
  // 公告弹窗只在登录后出现；同一浏览器会话关过就不再弹（见 AnnouncementGate）
  // AI 任务弹窗 + 后台任务同步也放在登录确认之后：避免未登录时多打一次 401（会重复弹"未授权"提示）
  return (
    <>
      {children}
      <AnnouncementGate />
      <AIJobHost />
    </>
  )
}
