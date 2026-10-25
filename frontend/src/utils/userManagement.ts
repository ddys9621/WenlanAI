import type { User } from '@/types'

export type UserSourceKey = 'linuxdo' | 'email' | 'admin_created' | 'local'

const SOURCE_LABELS: Record<UserSourceKey, string> = {
  linuxdo: 'Linux.do',
  email: '邮箱注册',
  admin_created: '管理员创建',
  local: '本地账号',
}

/** 按 user_id 前缀判断账号来源（linuxdo_ / email_ / admin_created_ / 其余为本地）。 */
export function userSource(userId: string): { key: UserSourceKey; label: string } {
  let key: UserSourceKey = 'local'
  if (userId.startsWith('linuxdo_')) key = 'linuxdo'
  else if (userId.startsWith('email_')) key = 'email'
  else if (userId.startsWith('admin_created_')) key = 'admin_created'
  return { key, label: SOURCE_LABELS[key] }
}

export type RoleFilter = 'all' | 'admin' | 'user'
export type StatusFilter = 'all' | 'active' | 'disabled'

export interface UserFilter {
  keyword?: string
  role?: RoleFilter
  status?: StatusFilter
}

export interface Page<T> {
  items: T[]
  page: number
  pageCount: number
}

/** 前端分页：页码越界夹到 [1, pageCount]，空列表也算一页。 */
export function paginate<T>(items: T[], page: number, pageSize: number): Page<T> {
  const size = Math.max(1, pageSize)
  const pageCount = Math.max(1, Math.ceil(items.length / size))
  const current = Math.min(Math.max(1, Math.floor(page) || 1), pageCount)
  const start = (current - 1) * size
  return { items: items.slice(start, start + size), page: current, pageCount }
}

const AUDIT_ACTION_LABELS: Record<string, string> = {
  'user.create': '创建用户',
  'user.update': '编辑资料',
  'user.disable': '禁用用户',
  'user.enable': '启用用户',
  'user.reset_password': '重置密码',
  'user.revoke_sessions': '强制下线',
  'user.delete': '删除用户',
}

/** 审计动作的中文；未登记的原样返回。 */
export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action] ?? action
}

/** 按关键字（昵称 / 用户名 / 邮箱）、角色、状态筛选用户列表。 */
export function filterUsers(users: User[], opts: UserFilter): User[] {
  const kw = (opts.keyword ?? '').trim().toLowerCase()
  const role = opts.role ?? 'all'
  const status = opts.status ?? 'all'
  return users.filter((user) => {
    if (kw) {
      const hay = `${user.display_name} ${user.username} ${user.email ?? ''}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    if (role === 'admin' && !user.is_admin) return false
    if (role === 'user' && user.is_admin) return false
    const active = user.is_active !== false
    if (status === 'active' && !active) return false
    if (status === 'disabled' && active) return false
    return true
  })
}
