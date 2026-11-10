/**
 * 旧的登录地址（书签、后端 OAuth 失败时 302 到 /login?error=…）：登录已改成首页上的弹窗，原样带上 redirect / error 转过去。
 */
import { Navigate, useSearchParams } from 'react-router-dom'
import { loginHref } from '@/utils/loginRoute'

export default function Login() {
  const [params] = useSearchParams()
  const error = params.get('error')
  return <Navigate to={loginHref(params.get('redirect'), error ? { error } : undefined)} replace />
}
