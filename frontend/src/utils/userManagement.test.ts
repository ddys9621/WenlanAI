import { describe, expect, it } from 'vitest'
import type { User } from '@/types'
import { auditActionLabel, filterUsers, paginate, userSource } from './userManagement'

const u = (over: Partial<User> & { user_id: string }): User => ({
  username: 'u',
  display_name: 'U',
  trust_level: 0,
  is_admin: false,
  linuxdo_id: over.user_id,
  email: null,
  created_at: '',
  last_login: '',
  ...over,
})

describe('userSource：按 user_id 前缀判断账号来源', () => {
  it('四种来源各自识别', () => {
    expect(userSource('linuxdo_123').key).toBe('linuxdo')
    expect(userSource('email_abc').key).toBe('email')
    expect(userSource('admin_created_abc').key).toBe('admin_created')
    expect(userSource('local_abc').key).toBe('local')
  })

  it('每种来源都有中文标签', () => {
    expect(userSource('linuxdo_1').label).toBe('Linux.do')
    expect(userSource('email_1').label).toBe('邮箱注册')
    expect(userSource('admin_created_1').label).toBe('管理员创建')
    expect(userSource('local_1').label).toBe('本地账号')
  })
})

describe('filterUsers：搜索 + 角色 + 状态筛选', () => {
  const users: User[] = [
    u({ user_id: 'local_a', username: 'alice', display_name: '爱丽丝', is_admin: true }),
    u({ user_id: 'email_b', username: 'bob@x.com', display_name: 'Bob', email: 'bob@x.com' }),
    u({ user_id: 'linuxdo_c', username: 'carol', display_name: 'Carol', is_active: false }),
  ]

  it('关键字匹配昵称 / 用户名 / 邮箱，大小写不敏感', () => {
    expect(filterUsers(users, { keyword: '爱丽丝' }).map((x) => x.user_id)).toEqual(['local_a'])
    expect(filterUsers(users, { keyword: 'BOB@X' }).map((x) => x.user_id)).toEqual(['email_b'])
    expect(filterUsers(users, { keyword: 'carol' }).map((x) => x.user_id)).toEqual(['linuxdo_c'])
    expect(filterUsers(users, { keyword: 'zzz' })).toHaveLength(0)
  })

  it('角色筛选', () => {
    expect(filterUsers(users, { role: 'admin' }).map((x) => x.user_id)).toEqual(['local_a'])
    expect(filterUsers(users, { role: 'user' }).map((x) => x.user_id)).toEqual(['email_b', 'linuxdo_c'])
  })

  it('状态筛选：is_active !== false 为正常', () => {
    expect(filterUsers(users, { status: 'active' }).map((x) => x.user_id)).toEqual(['local_a', 'email_b'])
    expect(filterUsers(users, { status: 'disabled' }).map((x) => x.user_id)).toEqual(['linuxdo_c'])
  })

  it('多条件组合', () => {
    expect(filterUsers(users, { role: 'user', status: 'active' }).map((x) => x.user_id)).toEqual(['email_b'])
  })

  it('无条件返回全部', () => {
    expect(filterUsers(users, {})).toHaveLength(3)
  })
})

describe('paginate：前端分页', () => {
  const items = Array.from({ length: 45 }, (_, i) => i + 1)

  it('按页切片并给出总页数', () => {
    const p1 = paginate(items, 1, 20)
    expect(p1.items).toEqual(items.slice(0, 20))
    expect(p1.pageCount).toBe(3)
    expect(p1.page).toBe(1)
    expect(paginate(items, 3, 20).items).toEqual([41, 42, 43, 44, 45])
  })

  it('页码越界时夹到合法范围', () => {
    expect(paginate(items, 0, 20).page).toBe(1)
    expect(paginate(items, 99, 20).page).toBe(3)
    expect(paginate(items, 99, 20).items).toEqual([41, 42, 43, 44, 45])
  })

  it('空列表至少一页', () => {
    const p = paginate([], 1, 20)
    expect(p.pageCount).toBe(1)
    expect(p.items).toEqual([])
  })
})

describe('auditActionLabel：审计动作的中文', () => {
  it('已知动作有中文', () => {
    expect(auditActionLabel('user.create')).toBe('创建用户')
    expect(auditActionLabel('user.disable')).toBe('禁用用户')
    expect(auditActionLabel('user.revoke_sessions')).toBe('强制下线')
    expect(auditActionLabel('user.reset_password')).toBe('重置密码')
  })

  it('未知动作原样返回', () => {
    expect(auditActionLabel('something.new')).toBe('something.new')
  })
})
