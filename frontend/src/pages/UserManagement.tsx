import { useEffect, useState, useCallback } from 'react'
import { Plus, Pencil, Trash2, Shield, ShieldOff, KeyRound, Loader2, Users, UserCheck, UserX, X } from 'lucide-react'
import { toast } from 'sonner'
import { adminApi } from '@/services/api'
import { LoginSettingsCard } from '@/components/admin/LoginSettingsCard'
import { AnnouncementSettingsCard } from '@/components/admin/AnnouncementSettingsCard'
import type { User } from '@/types'

export default function UserManagement() {
  const [users, setUsers] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [createForm, setCreateForm] = useState({ username: '', display_name: '', password: '', is_admin: false })

  // 编辑弹窗
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [editForm, setEditForm] = useState({ display_name: '', avatar_url: '', trust_level: 0 })

  // 状态切换 loading
  const [togglingId, setTogglingId] = useState<string | null>(null)

  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true)
      const res = await adminApi.getUsers()
      setUsers(res.users)
      setTotal(res.total)
    } catch { /* api 层已 toast */ } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchUsers() }, [fetchUsers])

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
      toast.success(res.default_password ? `用户已创建，默认密码：${res.default_password}` : '用户已创建')
      setShowCreateModal(false)
      setCreateForm({ username: '', display_name: '', password: '', is_admin: false })
      fetchUsers()
    } catch { /* api 层已 toast */ }
  }

  // 编辑用户
  const openEdit = (user: User) => {
    setEditingUser(user)
    setEditForm({
      display_name: user.display_name,
      avatar_url: user.avatar_url || '',
      trust_level: user.trust_level,
    })
    setShowEditModal(true)
  }

  const handleUpdate = async () => {
    if (!editingUser) return
    if (!editForm.display_name.trim()) { toast.error('显示名不能为空'); return }
    try {
      const res = await adminApi.updateUser(editingUser.user_id, {
        display_name: editForm.display_name,
        avatar_url: editForm.avatar_url || undefined,
        trust_level: editForm.trust_level,
      })
      setUsers(prev => prev.map(u => u.user_id === res.user.user_id ? res.user : u))
      toast.success('用户信息已更新')
      setShowEditModal(false)
      setEditingUser(null)
    } catch { /* api 层已 toast */ }
  }

  // 启用/禁用用户
  const handleToggleStatus = async (user: User) => {
    const newActive = !(user.is_active !== false)
    const action = newActive ? '启用' : '禁用'
    if (!confirm(`确定${action}用户「${user.display_name}」？`)) return
    try {
      setTogglingId(user.user_id)
      const res = await adminApi.toggleUserStatus(user.user_id, newActive)
      setUsers(prev => prev.map(u => u.user_id === user.user_id ? { ...u, is_active: res.is_active } : u))
      toast.success(res.message || `已${action}用户`)
    } catch { /* api 层已 toast */ } finally { setTogglingId(null) }
  }

  const handleResetPassword = async (user: User) => {
    if (!confirm(`确定重置「${user.display_name}」的密码？`)) return
    try {
      const res = await adminApi.resetPassword(user.user_id)
      toast.success(`密码已重置为：${res.new_password}`)
    } catch { /* api 层已 toast */ }
  }

  const handleDelete = async (user: User) => {
    if (!confirm(`确定删除用户「${user.display_name}」？此操作不可恢复。`)) return
    try {
      await adminApi.deleteUser(user.user_id)
      setUsers(prev => prev.filter(u => u.user_id !== user.user_id))
      toast.success('用户已删除')
    } catch { /* api 层已 toast */ }
  }

  const inputCls = 'w-full border border-surface-border rounded-btn px-3 py-2 text-sm focus:border-brand focus:ring-2 focus:ring-brand/20 outline-none transition-colors'

  return (
    <div className="space-y-6">
      <LoginSettingsCard />
      <AnnouncementSettingsCard />

      <div className="flex items-center justify-between">
        <h1 className="lj-page-title">用户管理 ({total})</h1>
        <button onClick={() => setShowCreateModal(true)} className="bg-brand hover:bg-brand-600 text-white rounded-btn px-4 py-2 text-sm font-medium transition-colors inline-flex items-center gap-1.5">
          <Plus className="w-4 h-4" />
          添加用户
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-content-secondary" /></div>
      ) : users.length === 0 ? (
        <div className="text-center py-12 text-content-secondary text-sm">
          <Users className="w-8 h-8 mx-auto mb-2 opacity-40" />
          暂无用户
        </div>
      ) : (
        <div className="bg-white border border-surface-border rounded-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border bg-surface-hover/50">
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">用户</th>
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">用户名</th>
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">信任等级</th>
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">角色</th>
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">状态</th>
                  <th className="text-left px-4 py-3 text-content-secondary font-medium">最后登录</th>
                  <th className="text-right px-4 py-3 text-content-secondary font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map(user => {
                  const isActive = user.is_active !== false
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
                        </div>
                      </td>
                      <td className="px-4 py-3 text-content-secondary">{user.username}</td>
                      <td className="px-4 py-3 text-content-secondary">{user.trust_level}</td>
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
                          <button
                            onClick={() => openEdit(user)}
                            title="编辑"
                            className="p-1.5 rounded hover:bg-surface-hover text-content-secondary transition-colors"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => handleToggleStatus(user)}
                            disabled={togglingId === user.user_id}
                            title={isActive ? '禁用用户' : '启用用户'}
                            className={`p-1.5 rounded transition-colors disabled:opacity-50 ${isActive ? 'hover:bg-orange-50 text-content-secondary hover:text-orange-500' : 'hover:bg-green-50 text-content-secondary hover:text-green-600'}`}
                          >
                            {togglingId === user.user_id ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : isActive ? (
                              <ShieldOff className="w-3.5 h-3.5" />
                            ) : (
                              <UserCheck className="w-3.5 h-3.5" />
                            )}
                          </button>
                          <button onClick={() => handleResetPassword(user)} title="重置密码" className="p-1.5 rounded hover:bg-surface-hover text-content-secondary transition-colors"><KeyRound className="w-3.5 h-3.5" /></button>
                          <button onClick={() => handleDelete(user)} title="删除" className="p-1.5 rounded hover:bg-red-50 text-content-secondary hover:text-red-500 transition-colors"><Trash2 className="w-3.5 h-3.5" /></button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 创建用户弹窗 */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowCreateModal(false)}>
          <div className="bg-white rounded-modal shadow-xl p-6 w-full max-w-md mx-4 space-y-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-content">添加用户</h2>
              <button onClick={() => setShowCreateModal(false)} className="p-1 rounded hover:bg-surface-hover text-content-secondary"><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-sm text-content-secondary mb-1">用户名</label>
                <input value={createForm.username} onChange={e => setCreateForm(f => ({ ...f, username: e.target.value }))} className={inputCls} />
              </div>
              <div>
                <label className="block text-sm text-content-secondary mb-1">显示名</label>
                <input value={createForm.display_name} onChange={e => setCreateForm(f => ({ ...f, display_name: e.target.value }))} className={inputCls} />
              </div>
              <div>
                <label className="block text-sm text-content-secondary mb-1">密码（留空自动生成）</label>
                <input type="password" value={createForm.password} onChange={e => setCreateForm(f => ({ ...f, password: e.target.value }))} className={inputCls} />
              </div>
              <label className="flex items-center gap-2 text-sm text-content-secondary cursor-pointer">
                <input type="checkbox" checked={createForm.is_admin} onChange={e => setCreateForm(f => ({ ...f, is_admin: e.target.checked }))} className="rounded" />
                设为管理员
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setShowCreateModal(false)} className="border border-surface-border text-content-secondary hover:bg-surface-hover rounded-btn px-4 py-2 text-sm">取消</button>
              <button onClick={handleCreate} className="bg-brand hover:bg-brand-600 text-white rounded-btn px-4 py-2 text-sm font-medium transition-colors">创建</button>
            </div>
          </div>
        </div>
      )}

      {/* 编辑用户弹窗 */}
      {showEditModal && editingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => { setShowEditModal(false); setEditingUser(null) }}>
          <div className="bg-white rounded-modal shadow-xl p-6 w-full max-w-md mx-4 space-y-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-content">编辑用户</h2>
              <button onClick={() => { setShowEditModal(false); setEditingUser(null) }} className="p-1 rounded hover:bg-surface-hover text-content-secondary"><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-sm text-content-secondary mb-1">用户名</label>
                <input value={editingUser.username} disabled className={`${inputCls} bg-surface-hover/50 cursor-not-allowed`} />
              </div>
              <div>
                <label className="block text-sm text-content-secondary mb-1">显示名</label>
                <input value={editForm.display_name} onChange={e => setEditForm(f => ({ ...f, display_name: e.target.value }))} className={inputCls} />
              </div>
              <div>
                <label className="block text-sm text-content-secondary mb-1">头像 URL</label>
                <input value={editForm.avatar_url} onChange={e => setEditForm(f => ({ ...f, avatar_url: e.target.value }))} placeholder="https://..." className={inputCls} />
              </div>
              <div>
                <label className="block text-sm text-content-secondary mb-1">信任等级</label>
                <input type="number" min={0} max={10} value={editForm.trust_level} onChange={e => setEditForm(f => ({ ...f, trust_level: parseInt(e.target.value) || 0 }))} className={inputCls} />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => { setShowEditModal(false); setEditingUser(null) }} className="border border-surface-border text-content-secondary hover:bg-surface-hover rounded-btn px-4 py-2 text-sm">取消</button>
              <button onClick={handleUpdate} className="bg-brand hover:bg-brand-600 text-white rounded-btn px-4 py-2 text-sm font-medium transition-colors">保存</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
