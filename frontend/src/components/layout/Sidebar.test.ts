import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { CurrentUserContext } from '@/hooks/useCurrentUser'
import type { User } from '@/types'
import { Sidebar } from './Sidebar'

const user = (is_admin: boolean): User => ({
  user_id: 'u1', username: 'u1', display_name: 'U1', trust_level: 1, is_admin,
  linuxdo_id: '', created_at: '', last_login: '',
})

const renderAs = (current: User) =>
  renderToStaticMarkup(
    h(CurrentUserContext.Provider, { value: current },
      h(StaticRouter, { location: '/projects' }, h(Sidebar, { collapsed: false, onToggle: () => undefined }))),
  )

/** 侧栏「管理台」只给管理员：普通用户连分组标题都不出 */
describe('Sidebar 管理台入口', () => {
  // useDesktopApi 首帧读 window.pywebview；node 环境没有 window
  beforeAll(() => { vi.stubGlobal('window', {}) })
  afterAll(() => { vi.unstubAllGlobals() })

  it('普通用户看不到用户管理', () => {
    const html = renderAs(user(false))
    expect(html).toContain('我的项目')
    expect(html).not.toContain('用户管理')
    expect(html).not.toContain('管理台')
  })

  it('管理员看得到用户管理', () => {
    const html = renderAs(user(true))
    expect(html).toContain('管理台')
    expect(html).toContain('href="/user-management"')
  })
})
