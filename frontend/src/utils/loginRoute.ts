/**
 * 登录是首页上的弹窗，不再单独一页：凡是要登录的地方（受保护页面、会话过期、首页的入口）都跳到「首页 + ?login=1」，
 * 登录完去 redirect。旧的 /login 地址（书签、后端 OAuth 失败的 302）由 pages/Login 转过来。
 */

/** 后端 OAuth 回调失败时 302 到 /login?error=<code> */
export const LOGIN_ERROR_MESSAGES: Record<string, string> = {
  linuxdo_disabled: 'Linux.do 登录未开启',
  oauth_denied: 'Linux.do 授权被取消或失败',
  invalid_state: '授权已失效，请重新发起登录',
  token_failed: 'Linux.do 授权失败（获取令牌失败），请重试',
  userinfo_failed: 'Linux.do 授权失败（获取用户信息失败），请重试',
  register_disabled: '当前未开放 Linux.do 注册，请联系管理员',
  user_disabled: '账号已被禁用，请联系管理员',
}

/** 打开登录弹窗的地址：首页带 login=1，登录完去 redirect（首页本身不当目的地，不带） */
export function loginHref(redirect?: string | null, extra?: Record<string, string>): string {
  const params = new URLSearchParams({ login: '1' })
  const target = redirect ? safeRedirect(redirect, '') : ''
  if (target) params.set('redirect', target)
  for (const [key, value] of Object.entries(extra ?? {})) params.set(key, value)
  return `/?${params.toString()}`
}

/** 现在是不是在登录弹窗上（或旧的 /login 地址，马上会转过去）：这时的 401 是正常结果，不再跳转 */
export function onLoginScreen(loc: { pathname: string; search: string }): boolean {
  return loc.pathname === '/login' || (loc.pathname === '/' && new URLSearchParams(loc.search).get('login') === '1')
}

/** 登录完要去的地方：只认站内路径（防 //外站、http://），首页和登录地址本身不算，退回 fallback */
export function safeRedirect(raw: string | null | undefined, fallback = '/projects'): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return fallback
  if (raw === '/' || raw.startsWith('/?') || raw.startsWith('/#') || raw === '/login' || raw.startsWith('/login?')) return fallback
  return raw
}

/** 登录弹窗上说一句「登录后接着做什么」 */
export function redirectLabel(path: string): string {
  if (path.startsWith('/projects?') && path.includes('panel=inspiration')) return '用灵感开新书'
  if (path.startsWith('/project/')) return '回到你的作品'
  if (path.startsWith('/book-dissect')) return '拆书参考'
  if (path.startsWith('/knowledge')) return '打开知识库'
  if (path.startsWith('/settings')) return '打开设置'
  return '进入书架'
}
