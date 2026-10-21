import { useEffect, useState, useCallback, type ReactNode } from 'react'
import { Plus, Pencil, Trash2, Building, Loader2, Users, UserPlus, ChevronDown, ChevronUp, MapPin } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { organizationApi, characterApi } from '@/services/api'
import { Modal } from '@/components/ui/Modal'
import { useAssistantDataChange } from '@/hooks/useAssistantPage'
import type { AssistantDataChange } from '@/store/assistantStore'
import type { Character } from '@/types'

/* ------------------------------------------------------------------ */
/*  类型定义（对齐后端 schema）                                          */
/* ------------------------------------------------------------------ */

/** 对应后端 OrganizationDetailResponse */
interface Organization {
  id: string
  character_id: string
  name: string
  type?: string           // 来自 Character.organization_type
  purpose?: string        // 来自 Character.organization_purpose
  member_count: number
  power_level: number     // 0-100
  location?: string
  motto?: string
  color?: string
}

/** 对应后端 OrganizationMemberDetailResponse */
interface OrgMember {
  id: string
  character_id: string
  character_name: string
  position: string
  rank: number
  loyalty: number         // 0-100
  contribution: number    // 0-100
  status: string
  joined_at?: string
  left_at?: string
  notes?: string
}

/** 创建/编辑组织表单 — Character 字段 + Organization 字段 */
interface OrgForm {
  // Character 字段
  name: string
  organization_type: string
  description: string       // 存入 Character.personality
  purpose: string           // 存入 Character.organization_purpose
  // Organization 字段
  power_level: number
  location: string
  motto: string
  color: string
}

/** 添加/编辑成员表单 */
interface MemberForm {
  character_id: string
  position: string
  rank: number
  loyalty: number
}

const EMPTY_ORG_FORM: OrgForm = {
  name: '', organization_type: '', description: '', purpose: '',
  power_level: 50, location: '', motto: '', color: '',
}
const EMPTY_MEMBER_FORM: MemberForm = { character_id: '', position: '', rank: 0, loyalty: 50 }

const ORG_TYPES = ['门派', '帮会', '家族', '王朝', '商会', '军队', '宗教', '学院', '其他'] as const

/* ------------------------------------------------------------------ */
/*  主组件                                                              */
/* ------------------------------------------------------------------ */
export default function Organizations() {
  const { currentProject } = useStore()

  /* ---- 状态 ---- */
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [loading, setLoading] = useState(false)
  const [showOrgModal, setShowOrgModal] = useState(false)
  const [editingOrg, setEditingOrg] = useState<Organization | null>(null)
  const [orgForm, setOrgForm] = useState<OrgForm>(EMPTY_ORG_FORM)

  // 成员管理
  const [expandedOrgId, setExpandedOrgId] = useState<string | null>(null)
  const [members, setMembers] = useState<OrgMember[]>([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [showMemberModal, setShowMemberModal] = useState(false)
  const [editingMember, setEditingMember] = useState<OrgMember | null>(null)
  const [memberForm, setMemberForm] = useState<MemberForm>(EMPTY_MEMBER_FORM)
  const [characters, setCharacters] = useState<Character[]>([])

  /* ---- 数据获取 ---- */
  const fetchOrgs = useCallback(async () => {
    if (!currentProject?.id) return
    try {
      setLoading(true)
      const data = await organizationApi.getProjectOrganizations(currentProject.id)
      setOrgs((Array.isArray(data) ? data : []) as unknown as Organization[])
    } catch { /* api 层已 toast */ } finally { setLoading(false) }
  }, [currentProject?.id])

  const fetchMembers = useCallback(async (orgId: string) => {
    try {
      setMembersLoading(true)
      const data = await organizationApi.getMembers(orgId)
      setMembers((Array.isArray(data) ? data : []) as unknown as OrgMember[])
    } catch { /* api 层已 toast */ } finally { setMembersLoading(false) }
  }, [])

  const fetchCharacters = useCallback(async () => {
    if (!currentProject?.id) return
    try {
      const data = await characterApi.getCharacters(currentProject.id)
      setCharacters((Array.isArray(data) ? data : []).filter(c => !c.is_organization))
    } catch { /* ignore */ }
  }, [currentProject?.id])

  useEffect(() => { fetchOrgs() }, [fetchOrgs])

  // 智能助笔建了组织 / 改了组织详情：刷新列表
  const onAssistantData = useCallback((change: AssistantDataChange) => {
    if (change.entity === 'organization') void fetchOrgs()
  }, [fetchOrgs])
  useAssistantDataChange(onAssistantData)

  /* ---- 组织 CRUD ---- */
  const openCreateOrg = () => {
    setEditingOrg(null)
    setOrgForm(EMPTY_ORG_FORM)
    setShowOrgModal(true)
  }

  const openEditOrg = (org: Organization) => {
    setEditingOrg(org)
    setOrgForm({
      name: org.name,
      organization_type: org.type || '',
      description: '',  // Character.personality 不在列表响应中，留空
      purpose: org.purpose || '',
      power_level: org.power_level ?? 50,
      location: org.location || '',
      motto: org.motto || '',
      color: org.color || '',
    })
    setShowOrgModal(true)
  }

  const handleOrgSubmit = async () => {
    if (!currentProject?.id) return
    if (!orgForm.name.trim()) { toast.error('请填写组织名称'); return }
    try {
      if (editingOrg) {
        // 编辑模式：分别更新 Character 和 Organization
        // 1. 更新 Character 基本信息
        await characterApi.updateCharacter(editingOrg.character_id, {
          name: orgForm.name,
          organization_type: orgForm.organization_type || undefined,
          organization_purpose: orgForm.purpose || undefined,
          personality: orgForm.description || undefined,
        })
        // 2. 更新 Organization 额外属性
        await organizationApi.updateOrganization(editingOrg.id, {
          power_level: orgForm.power_level,
          location: orgForm.location || undefined,
          motto: orgForm.motto || undefined,
          color: orgForm.color || undefined,
        })
        toast.success('组织已更新')
        await fetchOrgs()
      } else {
        // 创建模式：两步操作
        // 第一步：创建 is_organization=true 的 Character
        const char = await characterApi.createCharacter({
          project_id: currentProject.id,
          name: orgForm.name,
          role_type: '组织',
          personality: orgForm.description || undefined,
          is_organization: true,
          organization_type: orgForm.organization_type || undefined,
          organization_purpose: orgForm.purpose || undefined,
        })
        // 第二步：用 character_id 创建 Organization 记录
        await organizationApi.createOrganization({
          character_id: char.id,
          project_id: currentProject.id,
          power_level: orgForm.power_level,
          location: orgForm.location || undefined,
          motto: orgForm.motto || undefined,
          color: orgForm.color || undefined,
        })
        toast.success('组织已创建')
        await fetchOrgs()
      }
      setShowOrgModal(false)
    } catch { /* api 层已 toast */ }
  }

  const handleDeleteOrg = async (org: Organization) => {
    if (!confirm(`确定删除「${org.name}」？此操作不可撤销。`)) return
    try {
      await organizationApi.deleteOrganization(org.id)
      setOrgs(prev => prev.filter(o => o.id !== org.id))
      if (expandedOrgId === org.id) { setExpandedOrgId(null); setMembers([]) }
      toast.success('组织已删除')
    } catch { /* api 层已 toast */ }
  }

  /* ---- 成员管理 ---- */
  const toggleMembers = async (orgId: string) => {
    if (expandedOrgId === orgId) {
      setExpandedOrgId(null)
      setMembers([])
      return
    }
    setExpandedOrgId(orgId)
    await fetchMembers(orgId)
  }

  const openAddMember = async () => {
    setEditingMember(null)
    setMemberForm(EMPTY_MEMBER_FORM)
    await fetchCharacters()
    setShowMemberModal(true)
  }

  const openEditMember = (m: OrgMember) => {
    setEditingMember(m)
    setMemberForm({
      character_id: m.character_id,
      position: m.position || '',
      rank: m.rank ?? 0,
      loyalty: m.loyalty ?? 50,
    })
    setShowMemberModal(true)
  }

  const handleMemberSubmit = async () => {
    if (!expandedOrgId) return
    try {
      if (editingMember) {
        // 编辑成员：不传 character_id
        const updated = await organizationApi.updateMember(editingMember.id, {
          position: memberForm.position || undefined,
          rank: memberForm.rank,
          loyalty: memberForm.loyalty,
        }) as unknown as OrgMember
        setMembers(prev => prev.map(m => m.id === updated.id ? updated : m))
        toast.success('成员信息已更新')
      } else {
        if (!memberForm.character_id) { toast.error('请选择角色'); return }
        if (!memberForm.position.trim()) { toast.error('请填写职位'); return }
        const created = await organizationApi.addMember(expandedOrgId, {
          character_id: memberForm.character_id,
          position: memberForm.position,
          rank: memberForm.rank,
          loyalty: memberForm.loyalty,
        }) as unknown as OrgMember
        setMembers(prev => [...prev, created])
        toast.success('成员已添加')
      }
      setShowMemberModal(false)
    } catch { /* api 层已 toast */ }
  }

  const handleRemoveMember = async (m: OrgMember) => {
    const name = m.character_name || '该成员'
    if (!confirm(`确定移除「${name}」？`)) return
    try {
      await organizationApi.removeMember(m.id)
      setMembers(prev => prev.filter(x => x.id !== m.id))
      toast.success('成员已移除')
    } catch { /* api 层已 toast */ }
  }

  const hasOrgs = orgs.length > 0
  const totalMembers = orgs.reduce((sum, o) => sum + (o.member_count ?? 0), 0)
  const avgPower = hasOrgs ? Math.round(orgs.reduce((sum, o) => sum + (o.power_level ?? 0), 0) / orgs.length) : 0
  const typeCount = new Set(orgs.map(o => o.type).filter(Boolean)).size

  /* ---- 渲染：标题区 + 卡片网格 ---- */
  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">组织管理</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            管理故事中的门派、家族、王朝等势力，维护它们的宗旨、势力等级与成员构成。
            {hasOrgs && `当前共 ${orgs.length} 个组织。`}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={openCreateOrg} className="hh-btn-primary">
            <Plus className="h-4 w-4" />
            创建组织
          </button>
        </div>
      </section>

      {hasOrgs && !loading && (
        <section className="hh-panel grid grid-cols-2 divide-surface-border/80 md:grid-cols-4 md:divide-x">
          <StatItem label="组织总数" value={orgs.length} />
          <StatItem label="成员总数" value={totalMembers} />
          <StatItem label="平均势力" value={avgPower} />
          <StatItem label="组织类型" value={typeCount} />
        </section>
      )}

      {loading ? (
        <section className="hh-panel flex items-center justify-center py-14">
          <Loader2 className="h-6 w-6 animate-spin text-brand" />
        </section>
      ) : !hasOrgs ? (
        <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <Building className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">还没有任何组织</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            点击右上角「创建组织」，为故事建立门派、家族或势力，再往里添加成员与职位。
          </p>
        </section>
      ) : (
        <section className="grid gap-4 lg:grid-cols-2">
          {orgs.map(org => {
            const expanded = expandedOrgId === org.id
            return (
              <article key={org.id} className="hh-panel flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-brand/10 text-brand">
                      <Building className="h-5 w-5" />
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="min-w-0 truncate text-[15px] font-semibold text-content">{org.name}</h3>
                        {org.type && <span className="hh-tag">{org.type}</span>}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-content-tertiary">
                        <span className="inline-flex items-center gap-1">
                          <Users className="h-3.5 w-3.5" />
                          {org.member_count ?? 0} 名成员
                        </span>
                        {org.location && (
                          <span className="inline-flex items-center gap-1">
                            <MapPin className="h-3.5 w-3.5" />
                            {org.location}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button onClick={() => openEditOrg(org)} className="hh-icon-btn-plain h-8 w-8" title="编辑" aria-label="编辑">
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button onClick={() => handleDeleteOrg(org)} className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="删除" aria-label="删除">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                {(org.purpose || org.motto) && (
                  <div className="mt-4 space-y-1.5">
                    {org.purpose && <p className="text-[13px] leading-6 text-content-secondary">目标：{org.purpose}</p>}
                    {org.motto && <p className="text-[13px] leading-6 text-content-tertiary">「{org.motto}」</p>}
                  </div>
                )}

                {org.power_level != null && (
                  <div className="mt-4">
                    <div className="flex items-center justify-between text-xs text-content-tertiary">
                      <span>势力等级</span>
                      <span className="font-medium text-content tabular-nums">{org.power_level}</span>
                    </div>
                    <div className="hh-progress mt-1.5">
                      <div className="hh-progress-bar" style={{ width: `${Math.min(Math.max(org.power_level, 0), 100)}%` }} />
                    </div>
                  </div>
                )}

                <div className="mt-4 border-t border-surface-border/80 pt-3">
                  <button
                    onClick={() => toggleMembers(org.id)}
                    className="flex w-full items-center justify-between gap-3 text-left text-[13px] font-medium text-content-secondary hover:text-brand"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Users className="h-4 w-4" />
                      {expanded ? '收起成员' : '查看成员'}
                    </span>
                    {expanded ? <ChevronUp className="h-4 w-4 shrink-0" /> : <ChevronDown className="h-4 w-4 shrink-0" />}
                  </button>

                  {expanded && (
                    <div className="hh-subpanel mt-3">
                      <div className="flex items-center justify-between gap-3 border-b border-surface-border/80 px-4 py-2.5">
                        <span className="text-xs font-medium text-content-secondary">成员列表</span>
                        <button onClick={openAddMember} className="hh-btn-ghost hh-btn-sm h-8 px-2.5 text-xs text-brand hover:text-brand-600">
                          <UserPlus className="h-3.5 w-3.5" />
                          添加成员
                        </button>
                      </div>

                      {membersLoading ? (
                        <div className="flex justify-center py-6">
                          <Loader2 className="h-4 w-4 animate-spin text-brand" />
                        </div>
                      ) : members.length === 0 ? (
                        <p className="px-4 py-6 text-center text-xs text-content-tertiary">暂无成员</p>
                      ) : (
                        <ul className="divide-y divide-surface-border/80">
                          {members.map(m => (
                            <li key={m.id} className="flex items-center justify-between gap-3 px-4 py-2.5 transition-colors hover:bg-brand/[0.04]">
                              <div className="min-w-0 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                                <span className="text-sm font-medium text-content">{m.character_name || '未知角色'}</span>
                                {(m.position || m.rank) && (
                                  <span className="text-xs text-content-secondary">
                                    {[m.position, m.rank ? `等级${m.rank}` : ''].filter(Boolean).join(' · ')}
                                  </span>
                                )}
                                {m.loyalty != null && (
                                  <span className="text-xs text-content-tertiary tabular-nums">
                                    忠诚 {m.loyalty}
                                  </span>
                                )}
                              </div>
                              <div className="flex shrink-0 items-center gap-0.5">
                                <button onClick={() => openEditMember(m)} className="hh-icon-btn-plain h-7 w-7" title="编辑" aria-label="编辑成员">
                                  <Pencil className="h-3.5 w-3.5" />
                                </button>
                                <button onClick={() => handleRemoveMember(m)} className="hh-icon-btn-plain h-7 w-7 hover:text-red-500" title="移除" aria-label="移除成员">
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              </article>
            )
          })}
        </section>
      )}

      {showOrgModal && (
        <Modal
          title={editingOrg ? '编辑组织' : '创建组织'}
          onClose={() => setShowOrgModal(false)}
          size="xl"
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowOrgModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleOrgSubmit} className="hh-btn-primary">{editingOrg ? '保存' : '创建'}</button>
            </>
          )}
        >
          <div className="space-y-5">
            <div>
              <label className="hh-label">名称 <span className="text-red-500">*</span></label>
              <input value={orgForm.name} onChange={e => setOrgForm(f => ({ ...f, name: e.target.value }))} placeholder="组织名称" className="hh-field" />
            </div>
            <div>
              <label className="hh-label">类型</label>
              <div className="flex flex-wrap gap-1.5">
                {ORG_TYPES.map(t => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setOrgForm(f => ({ ...f, organization_type: f.organization_type === t ? '' : t }))}
                    className={cn('hh-chip', orgForm.organization_type === t && 'hh-chip--active')}
                  >{t}</button>
                ))}
              </div>
            </div>
            <div>
              <label className="hh-label">描述</label>
              <textarea value={orgForm.description} onChange={e => setOrgForm(f => ({ ...f, description: e.target.value }))} rows={3} placeholder="组织的背景描述…" className="hh-textarea" />
            </div>
            <div>
              <label className="hh-label">目标/宗旨</label>
              <textarea value={orgForm.purpose} onChange={e => setOrgForm(f => ({ ...f, purpose: e.target.value }))} rows={2} placeholder="组织的核心目标…" className="hh-textarea" />
            </div>
            <div>
              <div className="mb-1.5 flex items-center justify-between gap-3">
                <label className="text-[13px] font-medium text-content">势力等级</label>
                <span className="text-xs text-content-tertiary tabular-nums">{orgForm.power_level}</span>
              </div>
              <input type="range" min={0} max={100} value={orgForm.power_level} onChange={e => setOrgForm(f => ({ ...f, power_level: Number(e.target.value) }))} className="w-full" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="hh-label">所在地</label>
                <input value={orgForm.location} onChange={e => setOrgForm(f => ({ ...f, location: e.target.value }))} placeholder="如：昆仑山、中原…" className="hh-field" />
              </div>
              <div>
                <label className="hh-label">座右铭</label>
                <input value={orgForm.motto} onChange={e => setOrgForm(f => ({ ...f, motto: e.target.value }))} placeholder="组织的座右铭…" className="hh-field" />
              </div>
            </div>
            <div>
              <label className="hh-label">代表颜色</label>
              <input type="color" value={orgForm.color || '#6366f1'} onChange={e => setOrgForm(f => ({ ...f, color: e.target.value }))} className="h-11 w-16 cursor-pointer border border-surface-border bg-white/65 p-1" />
            </div>
          </div>
        </Modal>
      )}

      {showMemberModal && (
        <Modal
          title={editingMember ? '编辑成员' : '添加成员'}
          onClose={() => setShowMemberModal(false)}
          size="lg"
          closeOnMaskClick={false}
          footer={(
            <>
              <button onClick={() => setShowMemberModal(false)} className="hh-btn-ghost">取消</button>
              <button onClick={handleMemberSubmit} className="hh-btn-primary">{editingMember ? '保存' : '添加'}</button>
            </>
          )}
        >
          <div className="space-y-5">
            {!editingMember && (
              <div>
                <label className="hh-label">选择角色 <span className="text-red-500">*</span></label>
                <select
                  value={memberForm.character_id}
                  onChange={e => setMemberForm(f => ({ ...f, character_id: e.target.value }))}
                  className="hh-field"
                >
                  <option value="">请选择角色…</option>
                  {characters
                    .filter(c => !members.some(m => m.character_id === c.id))
                    .map(c => <option key={c.id} value={c.id}>{c.name}{c.role_type ? ` (${c.role_type})` : ''}</option>)
                  }
                </select>
              </div>
            )}
            <div>
              <label className="hh-label">职位 <span className="text-red-500">*</span></label>
              <input value={memberForm.position} onChange={e => setMemberForm(f => ({ ...f, position: e.target.value }))} placeholder="如：掌门、长老、弟子…" className="hh-field" />
            </div>
            <div>
              <label className="hh-label">等级</label>
              <input type="number" min={0} value={memberForm.rank} onChange={e => setMemberForm(f => ({ ...f, rank: Number(e.target.value) }))} placeholder="职位等级（数字）" className="hh-field" />
            </div>
            <div>
              <div className="mb-1.5 flex items-center justify-between gap-3">
                <label className="text-[13px] font-medium text-content">忠诚度</label>
                <span className="text-xs text-content-tertiary tabular-nums">{memberForm.loyalty}</span>
              </div>
              <input type="range" min={0} max={100} value={memberForm.loyalty} onChange={e => setMemberForm(f => ({ ...f, loyalty: Number(e.target.value) }))} className="w-full" />
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

function StatItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="px-5 py-4 md:px-6">
      <p className="text-xs text-content-tertiary">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-content tabular-nums">{value}</p>
    </div>
  )
}
