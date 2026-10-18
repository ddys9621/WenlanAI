import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { CurrentUserContext } from '@/hooks/useCurrentUser'
import type { User } from '@/types'
import { AdminRoute } from './ProtectedRoute'

const user = (is_admin: boolean): User => ({
  user_id: 'u1', username: 'u1', display_name: 'U1', trust_level: 1, is_admin,
  linuxdo_id: '', created_at: '', last_login: '',
})

const renderAs = (current: User) =>
  renderToStaticMarkup(
    h(CurrentUserContext.Provider, { value: current },
      h(StaticRouter, { location: '/user-management' }, h(AdminRoute, null, h('p', null, '用户列表')))),
  )

/** 管理员路由：普通用户直接打开 /user-management 也拿不到管理页 */
describe('AdminRoute', () => {
  it('普通用户不渲染管理页，改为重定向', () => {
    // StaticRouter 里 <Navigate> 只发警告不跳转：借这条警告确认确实发起了重定向（跳到哪由实机验证）
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    try {
      expect(renderAs(user(false))).not.toContain('用户列表')
      expect(warn).toHaveBeenCalledWith(expect.stringContaining('<Navigate>'))
    } finally {
      warn.mockRestore()
    }
  })

  it('管理员正常进入', () => {
    expect(renderAs(user(true))).toContain('用户列表')
  })
})
