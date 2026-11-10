/**
 * 首页（公开页，不用登录）：顶栏 · 首屏（一句话开新书 + 九步创作流程的工作台预览）·
 * 长篇难点 · AI 创作团队 · 你来拍板 · 规划链与拆书参考 · 模型与部署 · 题材 · 姊妹项目（星绘 Studio）· 常见问题 · 收尾 · 页脚 · 回到顶部。
 * 各区块在 components/home/ 下；登录态只是探测（authApi.probeCurrentUser，没登录不跳走、不弹提示），
 * 登录了入口变成「进入书架」。
 * 登录是这里的弹窗：地址带 ?login=1 就打开（受保护页面、会话过期、首页入口都跳到这儿，见 utils/loginRoute），
 * 登录完去 redirect；已经登录的直接去；带 error（OAuth 失败）先提示一句。
 */
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { authApi } from '@/services/api'
import { LoginModal } from '@/components/auth/LoginModal'
import { BackToTop } from '@/components/home/HomeEffects'
import { HomeHero } from '@/components/home/HomeHero'
import { HomeNav } from '@/components/home/HomeNav'
import {
  ClosingSection, ControlSection, FaqSection, FeaturesSection, GenresSection, HomeFooter, ModelsDeploySection,
  PlanningSection, SisterProjectSection, TeamSection,
} from '@/components/home/HomeSections'
import { LOGIN_ERROR_MESSAGES, redirectLabel, safeRedirect } from '@/utils/loginRoute'
import type { User } from '@/types'

export default function Home() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  // undefined = 还在探测；null = 没登录
  const [user, setUser] = useState<User | null | undefined>(undefined)
  const loginOpen = params.get('login') === '1'
  const redirect = safeRedirect(params.get('redirect'))

  useEffect(() => {
    document.title = '文澜 AI · 长篇小说创作工作台'
    let cancelled = false
    authApi.probeCurrentUser()
      .then((u) => { if (!cancelled) setUser(u) })
      .catch(() => { if (!cancelled) setUser(null) })
    return () => { cancelled = true }
  }, [])

  // OAuth 回调带回来的错误码只提示一次，然后从地址栏清掉（弹窗照样开着）
  useEffect(() => {
    const error = params.get('error')
    if (!error) return
    toast.error(LOGIN_ERROR_MESSAGES[error] ?? '登录失败，请重试')
    const next = new URLSearchParams(params)
    next.delete('error')
    setParams(next, { replace: true })
  }, [params, setParams])

  // 已经登录了还被叫去登录（比如书签里的旧地址）：直接去要去的地方
  useEffect(() => {
    if (loginOpen && user) navigate(redirect, { replace: true })
  }, [loginOpen, navigate, redirect, user])

  const closeLogin = useCallback(() => {
    const next = new URLSearchParams(params)
    next.delete('login')
    next.delete('redirect')
    setParams(next, { replace: true })
  }, [params, setParams])

  return (
    <div className="min-h-dvh overflow-x-clip bg-surface-paper text-content selection:bg-brand/15">
      <HomeNav user={user} />
      <main>
        <HomeHero user={user} />
        <FeaturesSection />
        <TeamSection />
        <ControlSection />
        <PlanningSection />
        <ModelsDeploySection user={user} />
        <GenresSection />
        <SisterProjectSection />
        <FaqSection />
        <ClosingSection user={user} />
      </main>
      <HomeFooter user={user} />
      <BackToTop />
      <LoginModal
        open={loginOpen && user === null}
        next={redirectLabel(redirect)}
        onClose={closeLogin}
        onSuccess={() => navigate(redirect, { replace: true })}
      />
    </div>
  )
}
