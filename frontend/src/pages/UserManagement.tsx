import { useEffect, useState, useCallback, useMemo, type ReactNode } from 'react'
import { Plus, Pencil, Trash2, Shield, ShieldOff, KeyRound, Loader2, Users, UserCheck, UserX, Search, Copy, Check, LogOut, ChevronLeft, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import { adminApi } from '@/services/api'
import { LoginSettingsCard } from '@/components/admin/LoginSettingsCard'
import { AnnouncementSettingsCard } from '@/components/admin/AnnouncementSettingsCard'
import { AdminAuditLogCard } from '@/components/admin/AdminAuditLogCard'
import { Modal } from '@/components/ui/Modal'
import { Switch } from '@/components/ui/Switch'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { filterUsers, paginate, userSource, type RoleFilter, type StatusFilter } from '@/utils/userManagement'
import type { User } from '@/types'

const PAGE_SIZE = 20

const ROLE_TABS: { k: RoleFilter; label: string }[] = [
  { k: 'all', label: '全部角色' },
  { k: 'admin', label: '管理员' },
  { k: 'user', label: '普通用户' },
]
const STATUS_TABS: { k: StatusFilter; label: string }[] = [
  { k: 'all', label: '全部状态' },
  { k: 'active', label: '正常' },
  { k: 'disabled', label: '已禁用' },
]

const inputCls = 'hh-field'

interface ConfirmState {
  title: string
  message: ReactNode
  confirmText: string
  danger?: boolean
  onConfirm: () => Promise<void> | void
}

interface PwResult {
  title: string
  password: string
  note?: string
}

export default function UserManagement() {
  const self = useCurrentUser()
  const [users, setUsers] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  const [keyword, setKeyword] = useState('')
  const [role, setRole] = useState<RoleFilter>('all')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [page, setPage] = useState(1)

  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({ username: '', display_name: '', password: '', is_admin: false })

  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [editForm, setEditForm] = useState({ display_name: '', avatar_url: '', is_admin: false })

  const [togglingId, setTogglingId] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<ConfirmState | null>(null)
  const [confirmBusy, setConfirmBusy] = useState(false)
  const [pwResult, setPwResult] = useState<PwResult | null>(null)

  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true)
      const res = await adminApi.getUsers()
      setUsers(res.users)
      setTotal(res.total)
    } catch { /* api 层已 toast */ } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchUsers() }, [fetchUsers])

  const visible = useMemo(() => filterUsers(users, { keyword, role, status }), [users, keyword, role, status])
  const paged = useMemo(() => paginate(visible, page, PAGE_SIZE), [visible, page])
  // 筛选条件一变就回到第一页
  useEffect(() => { setPage(1) }, [keyword, role, status])

  const handleCreate = async () => {
    if (!createForm.username.trim() || !createForm.display_name.trim()) {
      toast.error('请填写用户名和显示名')
      return
    }
    try {
      const res = await adminApi.createUser({
        username: createForm.username,
        display_name: createForm.display_name,
        password: createForm.password || undefined,
        is_admin: createForm.is_admin,
      })
      setShowCreate(false)
      setCreateForm({ username: '', display_name: '', password: '', is_admin: false })
      if (res.default_password) {
        setPwResult({ title: '用户已创建', password: res.default_password, note: '这是系统生成的初始密码，请复制后交给用户，关闭后将无法再次查看。' })
      } else {
        toast.success('用户已创建')
      }
      fetchUsers()
    } catch { /* api 层已 toast */ }
  }

  const openEdit = (user: User) => {
    setEditingUser(user)
    setEditForm({ display_name: user.display_name, avatar_url: user.avatar_url || '', is_admin: user.is_admin })
  }

  const handleUpdate = async () => {
    if (!editingUser) return
    if (!editForm.display_name.trim()) { toast.error('显示名不能为空'); return }
    try {
      const res = await adminApi.updateUser(editingUser.user_id, {
        display_name: editForm.display_name,
        avatar_url: editForm.avatar_url || undefined,
        is_admin: editForm.is_admin,
      })
      setUsers(prev => prev.map(u => u.user_id === res.user.user_id ? res.user : u))
      toast.success('用户信息已更新')
      setEditingUser(null)
    } catch { /* api 层已 toast */ }
  }

  const askToggle = (user: User) => {
    const newActive = !(user.is_active !== false)
    const action = newActive ? '启用' : '禁用'
    setConfirm({
      title: `${action}用户`,
      message: <>确定{action}用户「<b>{user.display_name}</b>」？{newActive ? '' : '禁用后该用户将立即无法登录。'}</>,
      confirmText: action,
      danger: !newActive,
      onConfirm: async () => {
        try {
          setTogglingId(user.user_id)
          const res = await adminApi.toggleUserStatus(user.user_id, newActive)
          setUsers(prev => prev.map(u => u.user_id === user.user_id ? { ...u, is_active: res.is_active } : u))
          toast.success(res.message || `已${action}用户`)
        } catch { /* api 层已 toast */ } finally { setTogglingId(null) }
      },
    })
  }

  const askReset = (user: User) => {
    setConfirm({
      title: '重置密码',
      message: <>确定重置「<b>{user.display_name}</b>」的密码？将生成一个新的随机密码。</>,
      confirmText: '重置',
      onConfirm: async () => {
        const res = await adminApi.resetPassword(user.user_id)
        setPwResult({ title: '密码已重置', password: res.new_password, note: '请复制后交给用户，关闭后将无法再次查看。' })
      },
    })
  }

  const askRevoke = (user: User) => {
    setConfirm({
      title: '强制下线',
      message: <>确定让「<b>{user.display_name}</b>」在所有设备上下线？其当前的登录态会立即失效，需重新登录。</>,
      confirmText: '强制下线',
      danger: true,
      onConfirm: async () => {
        const res = await adminApi.revokeUserSessions(user.user_id)
        toast.success(res.message || '已强制下线')
      },
    })
  }

  const askDelete = (user: User) => {
    setConfirm({
      title: '删除用户',
      message: <>确定删除用户「<b>{user.display_name}</b>」？该操作不可恢复。</>,
      confirmText: '删除',
      danger: true,
      onConfirm: async () => {
        await adminApi.deleteUser(user.user_id)
        setUsers(prev => prev.filter(u => u.user_id !== user.user_id))
        setTotal(t => Math.max(0, t - 1))
        toast.success('用户已删除')
      },
    })
  }

  const runConfirm = async () => {
    if (!confirm) return
    try {
      setConfirmBusy(true)
      await confirm.onConfirm()
      setConfirm(null)
    } catch { /* api 层已 toast */ } finally { setConfirmBusy(false) }
  }

  return (
    <div className="space-y-6">
      <LoginSettingsCard />
      <AnnouncementSettingsCard />
      <AdminAuditLogCard />

      <div className="flex items-center justify-between">
        <h1 className="lj-page-title">用户管理 ({total})</h1>
        <button onClick={() => setShowCreate(true)} className="bg-brand hover:bg-brand-600 text-white rounded-btn px-4 py-2 text-sm font-medium transition-colors inline-flex items-center gap-1.5">
          <Plus className="w-4 h-4" />
          添加用户
        </button>
      </div>

      {/* 工具条：搜索 + 角色 / 状态筛选 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative max-w-xs w-full">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary" />
          <input
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            placeholder="搜索昵称 / 用户名 / 邮箱"
            className="hh-field !pl-9"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {ROLE_TABS.map(t => (
            <button key={t.k} type="button" onClick={() => setRole(t.k)} className={`hh-chip ${role === t.k ? 'hh-chip--active' : ''}`}>{t.label}</button>
          ))}
          <span className="mx-1 w-px self-stretch bg-surface-border" />
          {STATUS_TABS.map(t => (
            <button key={t.k} type="button" onClick={() => setStatus(t.k)} className={`hh-chip ${status === t.k ? 'hh-chip--active' : ''}`}>{t.label}</button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-content-secondary" /></div>
      ) : visible.length === 0 ? (
        <div className="text-center py-12 text-content-secondary text-sm">
          <Users className="w-8 h-8 mx-auto mb-2 opacity-40" />
          {users.length === 0 ? '暂无用户' : '没有符合条件的用户'}
        </div>
      ) : (
        <div className="bg-white border border-surface-border rounded-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border bg-surface-hover/50">
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">用户</th>
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">用户名</th>
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">来源</th>
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">角色</th>
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">状态</th>
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">最后登录</th>
                  <th className="text-right px-4 py-3 text-content-secondary font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {paged.items.map(user => {
                  const isActive = user.is_active !== false
                  const isSelf = user.user_id === self?.user_id
                  const src = userSource(user.user_id)
                  return (
                    <tr key={user.user_id} className={`border-b border-surface-border last:border-0 hover:bg-surface-hover/30 transition-colors ${!isActive ? 'opacity-60' : ''}`}>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          {user.avatar_url ? (
                            <img src={user.avatar_url} alt="" className="w-7 h-7 rounded-full" />
                          ) : (
                            <div className="w-7 h-7 rounded-full bg-brand/10 flex items-center justify-center text-xs text-brand font-medium">
                              {user.display_name[0]}
                            </div>
                          )}
                          <span className="text-content">{user.display_name}</span>
                          {isSelf && <span className="text-[10px] text-content-tertiary">（你自己）</span>}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-content-secondary">{user.username}</td>
                      <td className="px-4 py-3"><span className="hh-tag">{src.label}</span></td>
                      <td className="px-4 py-3">
                        {user.is_admin ? (
                          <span className="inline-flex items-center gap-1 text-xs text-brand"><Shield className="w-3 h-3" />管理员</span>
                        ) : (
                          <span className="text-xs text-content-secondary">普通用户</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {isActive ? (
                          <span className="inline-flex items-center gap-1 text-xs text-green-600"><UserCheck className="w-3 h-3" />正常</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs text-red-500"><UserX className="w-3 h-3" />已禁用</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-content-secondary text-xs">
                        {user.last_login ? new Date(user.last_login).toLocaleString('zh-CN') : '-'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          <button onClick={() => openEdit(user)} title="编辑" className="p-1.5 rounded hover:bg-surface-hover text-content-secondary transition-colors">
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => askToggle(user)}
                            disabled={togglingId === user.user_id || isSelf}
                            title={isSelf ? '不能禁用自己' : isActive ? '禁用用户' : '启用用户'}
                            className={`p-1.5 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${isActive ? 'hover:bg-orange-50 text-content-secondary hover:text-orange-500' : 'hover:bg-green-50 text-content-secondary hover:text-green-600'}`}
                          >
                            {togglingId === user.user_id ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : isActive ? (
                              <ShieldOff className="w-3.5 h-3.5" />
                            ) : (
                              <UserCheck className="w-3.5 h-3.5" />
                            )}
                          </button>
                          <button onClick={() => askReset(user)} title="重置密码" className="p-1.5 rounded hover:bg-surface-hover text-content-secondary transition-colors"><KeyRound className="w-3.5 h-3.5" /></button>
                          <button
                            onClick={() => askRevoke(user)}
                            disabled={isSelf}
                            title={isSelf ? '要下线自己请直接退出登录' : '强制下线'}
                            className="p-1.5 rounded hover:bg-orange-50 text-content-secondary hover:text-orange-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-content-secondary"
                          >
                            <LogOut className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => askDelete(user)}
                            disabled={isSelf}
                            title={isSelf ? '不能删除自己' : '删除'}
                            className="p-1.5 rounded hover:bg-red-50 text-content-secondary hover:text-red-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-content-secondary"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {paged.pageCount > 1 && (
            <div className="flex items-center justify-between border-t border-surface-border px-4 py-2 text-xs text-content-secondary">
              <span>共 {visible.length} 人 · 第 {paged.page} / {paged.pageCount} 页</span>
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => setPage(p => p - 1)} disabled={paged.page <= 1} className="p-1.5 rounded hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed" aria-label="上一页">
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button type="button" onClick={() => setPage(p => p + 1)} disabled={paged.page >= paged.pageCount} className="p-1.5 rounded hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed" aria-label="下一页">
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 创建用户 */}
      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="添加用户"
        size="md"
        footer={<>
          <button onClick={() => setShowCreate(false)} className="hh-btn-ghost">取消</button>
          <button onClick={handleCreate} className="hh-btn-primary">创建</button>
        </>}
      >
        <div className="space-y-3">
          <div>
            <label className="hh-label">用户名</label>
            <input value={createForm.username} onChange={e => setCreateForm(f => ({ ...f, username: e.target.value }))} className={inputCls} autoComplete="off" />
          </div>
          <div>
            <label className="hh-label">显示名</label>
            <input value={createForm.display_name} onChange={e => setCreateForm(f => ({ ...f, display_name: e.target.value }))} className={inputCls} />
          </div>
          <div>
            <label className="hh-label">密码（留空自动生成）</label>
            <input type="password" value={createForm.password} onChange={e => setCreateForm(f => ({ ...f, password: e.target.value }))} className={inputCls} autoComplete="new-password" />
          </div>
          <div className="flex items-center justify-between pt-1">
            <span className="text-sm text-content-secondary">设为管理员</span>
            <Switch checked={createForm.is_admin} onChange={v => setCreateForm(f => ({ ...f, is_admin: v }))} label="设为管理员" />
          </div>
        </div>
      </Modal>

      {/* 编辑用户 */}
      <Modal
        open={!!editingUser}
        onClose={() => setEditingUser(null)}
        title="编辑用户"
        size="md"
        footer={<>
          <button onClick={() => setEditingUser(null)} className="hh-btn-ghost">取消</button>
          <button onClick={handleUpdate} className="hh-btn-primary">保存</button>
        </>}
      >
        {editingUser && (
          <div className="space-y-3">
            <div>
              <label className="hh-label">用户名</label>
              <input value={editingUser.username} disabled className={`${inputCls} opacity-60 cursor-not-allowed`} />
            </div>
            <div>
              <label className="hh-label">显示名</label>
              <input value={editForm.display_name} onChange={e => setEditForm(f => ({ ...f, display_name: e.target.value }))} className={inputCls} />
            </div>
            <div>
              <label className="hh-label">头像 URL</label>
              <input value={editForm.avatar_url} onChange={e => setEditForm(f => ({ ...f, avatar_url: e.target.value }))} placeholder="https://..." className={inputCls} />
            </div>
            <div className="flex items-center justify-between pt-1">
              <div>
                <p className="text-sm text-content">管理员</p>
                <p className="text-xs text-content-tertiary">管理员可进入用户管理与系统设置</p>
              </div>
              <Switch checked={editForm.is_admin} onChange={v => setEditForm(f => ({ ...f, is_admin: v }))} label="管理员" />
            </div>
            <p className="text-xs text-content-tertiary border-t border-surface-border pt-3">
              信任等级 {editingUser.trust_level}（由账号来源系统决定，不在此处修改）
            </p>
          </div>
        )}
      </Modal>

      {/* 确认弹窗 */}
      <Modal
        open={!!confirm}
        onClose={() => !confirmBusy && setConfirm(null)}
        title={confirm?.title}
        size="sm"
        footer={<>
          <button onClick={() => setConfirm(null)} disabled={confirmBusy} className="hh-btn-ghost">取消</button>
          <button
            onClick={runConfirm}
            disabled={confirmBusy}
            className={confirm?.danger
              ? 'inline-flex items-center gap-1.5 rounded-btn bg-red-500 hover:bg-red-600 text-white px-4 py-2 text-sm font-medium transition-colors disabled:opacity-60'
              : 'hh-btn-primary'}
          >
            {confirmBusy && <Loader2 className="w-4 h-4 animate-spin" />}
            {confirm?.confirmText}
          </button>
        </>}
      >
        <p className="text-sm text-content-secondary leading-relaxed">{confirm?.message}</p>
      </Modal>

      {/* 密码结果（可复制） */}
      <Modal
        open={!!pwResult}
        onClose={() => setPwResult(null)}
        title={pwResult?.title}
        size="sm"
        footer={<button onClick={() => setPwResult(null)} className="hh-btn-primary">我已保存</button>}
      >
        {pwResult && (
          <div className="space-y-3">
            <CopyField value={pwResult.password} />
            {pwResult.note && <p className="text-xs text-content-tertiary leading-relaxed">{pwResult.note}</p>}
          </div>
        )}
      </Modal>
    </div>
  )
}

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error('复制失败，请手动选择复制')
    }
  }
  return (
    <div className="flex items-center gap-2 rounded-btn border border-surface-border bg-surface-hover/40 px-3 py-2">
      <code className="flex-1 min-w-0 break-all font-mono text-sm text-content">{value}</code>
      <button onClick={copy} title="复制" className="shrink-0 p-1.5 rounded hover:bg-white text-content-secondary transition-colors">
        {copied ? <Check className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
      </button>
    </div>
  )
}
