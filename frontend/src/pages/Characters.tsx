import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Plus, Sparkles, Pencil, Trash2, X, Loader2, Building, Users, UserPlus, UserMinus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { useStore } from '@/store';
import { useCharacterSync } from '@/store/hooks';
import { useAIJobsStore, useRunningAIJobs } from '@/store/aiJobsStore';
import { characterApi, organizationApi } from '@/services/api';
import { AIJobBanner } from '@/components/ai-job/AIJobBanner';
import { MCPSelector } from '@/components/MCPSelector';
import {
  ReferencePackSelector,
  DEFAULT_SELECTOR_VALUE,
  type ReferencePackSelectorValue,
} from '@/components/ReferencePackSelector';
import type { Character, GenerateCharacterRequest } from '@/types';
import { ROLE_OPTIONS, getRoleDisplayName, normalizeRoleType } from '@/utils/characterRole';

interface FormData {
  name: string;
  role_type: string;
  personality: string;
  background: string;
  is_organization: boolean;
  organization_type: string;
  organization_purpose: string;
  reason: string;
}

const EMPTY_FORM: FormData = { name: '', role_type: 'protagonist', personality: '', background: '', is_organization: false, organization_type: '', organization_purpose: '', reason: '' };

export default function Characters() {
  const { currentProject, characters } = useStore();
  const { refreshCharacters, deleteCharacter } = useCharacterSync();

  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const startJob = useAIJobsStore((s) => s.start);
  // 本项目是否有角色生成任务在跑（按钮禁用态由 store 派生，刷新后仍正确）
  const generating = useRunningAIJobs(currentProject?.id, ['character_generate']).length > 0;
  const [showGenModal, setShowGenModal] = useState(false);
  const [genForm, setGenForm] = useState({ name: '', role_type: 'supporting', background: '', requirements: '' });
  const [enableMcp, setEnableMcp] = useState(false);
  const [selectedPlugins, setSelectedPlugins] = useState<string[]>([]);
  // R8：拆书参考包选择器
  const [genRefPack, setGenRefPack] = useState<ReferencePackSelectorValue>(DEFAULT_SELECTOR_VALUE);
  const [filter, setFilter] = useState<'all' | 'character' | 'organization'>('all');
  const [orgMembers, setOrgMembers] = useState<Array<Record<string, unknown>>>([]);
  const [orgId, setOrgId] = useState<string | null>(null);
  const [addMemberId, setAddMemberId] = useState('');
  const [addMemberPos, setAddMemberPos] = useState('成员');
  const [showGenOrgModal, setShowGenOrgModal] = useState(false);
  const [genOrgForm, setGenOrgForm] = useState({ name: '', requirements: '' });
  const [generatingOrg, setGeneratingOrg] = useState(false);

  const filteredCharacters = characters.filter(c => {
    if (filter === 'character') return !c.is_organization;
    if (filter === 'organization') return c.is_organization;
    return true;
  });
  const charCount = characters.filter(c => !c.is_organization).length;
  const orgCount = characters.filter(c => c.is_organization).length;

  useEffect(() => {
    if (currentProject?.id) refreshCharacters();
  }, [currentProject?.id, refreshCharacters]);

  const openAdd = useCallback(() => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setShowModal(true);
  }, []);

  const openAddOrg = useCallback(() => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM, is_organization: true, role_type: 'supporting' });
    setShowModal(true);
  }, []);

  const loadOrgMembers = useCallback(async (characterId: string) => {
    try {
      const orgs = currentProject?.id
        ? await organizationApi.getProjectOrganizations(currentProject.id) as Array<Record<string, unknown>>
        : [];
      const org = orgs.find((o) => o.character_id === characterId);
      if (org && org.id) {
        setOrgId(org.id as string);
        const members = await organizationApi.getMembers(org.id as string);
        setOrgMembers(members);
      } else {
        setOrgId(null);
        setOrgMembers([]);
      }
    } catch {
      setOrgMembers([]);
    }
  }, [currentProject?.id]);

  const handleAddMember = async () => {
    if (!orgId || !addMemberId) return;
    try {
      await organizationApi.addMember(orgId, { character_id: addMemberId, position: addMemberPos || '成员' });
      toast.success('成员已添加');
      setAddMemberId('');
      setAddMemberPos('成员');
      await loadOrgMembers(editingId!);
      await refreshCharacters(); // 卡片的成员名按成员关系派生，需同步刷新
    } catch {
      toast.error('添加成员失败');
    }
  };

  const handleRemoveMember = async (memberId: string) => {
    try {
      await organizationApi.removeMember(memberId);
      toast.success('成员已移除');
      if (editingId) await loadOrgMembers(editingId);
      await refreshCharacters();
    } catch {
      toast.error('移除失败');
    }
  };

  const openEdit = useCallback((c: Character) => {
    setEditingId(c.id);
    setForm({
      name: c.name,
      role_type: normalizeRoleType(c.role_type, c.is_organization ? 'supporting' : 'protagonist'),
      personality: c.personality || '',
      background: c.background || '',
      is_organization: c.is_organization,
      organization_type: c.organization_type || '',
      organization_purpose: c.organization_purpose || '',
      reason: '',
    });
    setOrgMembers([]);
    setOrgId(null);
    setAddMemberId('');
    setAddMemberPos('成员');
    if (c.is_organization) {
      loadOrgMembers(c.id);
    }
    setShowModal(true);
  }, [loadOrgMembers]);

  const handleSubmit = async () => {
    if (!currentProject || !form.name.trim()) return;
    setSubmitting(true);
    try {
      let bg = form.background;
      if (form.reason.trim()) {
        const prefix = editingId ? '[手动编辑]' : '[手动添加]';
        const reasonLine = `${prefix} ${form.reason.trim()}`;
        bg = bg.trim() ? `${bg.trim()}\n${reasonLine}` : reasonLine;
      }
      const payload: Record<string, unknown> = {
        name: form.name,
        role_type: normalizeRoleType(form.role_type, 'supporting'),
        personality: form.personality,
        background: bg,
      };
      if (form.is_organization) {
        payload.is_organization = true;
        payload.organization_type = form.organization_type;
        payload.organization_purpose = form.organization_purpose;
      }
      if (editingId) {
        await characterApi.updateCharacter(editingId, payload);
        toast.success(form.is_organization ? '组织已更新' : '角色已更新');
      } else {
        await characterApi.createCharacter({ project_id: currentProject.id, name: form.name, ...payload });
        toast.success(form.is_organization ? '组织已创建' : '角色已创建');
      }
      await refreshCharacters();
      setShowModal(false);
    } catch {
      toast.error(editingId ? '更新失败' : '创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string, name: string, isOrg: boolean) => {
    const label = isOrg ? '组织' : '角色';
    const reason = prompt(`确定删除${label}「${name}」吗？\n\n请填写删除原因（AI 后续会参考此信息）：`);
    if (reason === null) return;
    try {
      if (reason.trim()) {
        await characterApi.updateCharacter(id, {
          background: `[已删除] ${reason.trim()}`,
        });
      }
      await deleteCharacter(id);
      toast.success(`${label}已删除`);
    } catch {
      toast.error('删除失败');
    }
  };

  const handleGenerateOrg = async () => {
    if (!currentProject) return;
    setGeneratingOrg(true);
    try {
      await organizationApi.generateOrganization({
        project_id: currentProject.id,
        requirements: genOrgForm.requirements.trim() || undefined,
      });
      toast.success('AI 组织已生成');
      await refreshCharacters();
      setShowGenOrgModal(false);
      setGenOrgForm({ name: '', requirements: '' });
    } catch {
      toast.error('AI 生成组织失败');
    } finally {
      setGeneratingOrg(false);
    }
  };

  /** AI 生成角色：交给通用后台任务（弹窗展示阶段 / 工具 / 参考；可最小化、可停止、刷新后可重连） */
  const handleGenerate = async () => {
    if (!currentProject) return;
    const name = genForm.name.trim();
    const payload: GenerateCharacterRequest = {
      project_id: currentProject.id,
      name: name || undefined,
      role_type: genForm.role_type || undefined,
      background: genForm.background.trim() || undefined,
      requirements: genForm.requirements.trim() || undefined,
      enable_mcp: enableMcp,
      selected_plugins: selectedPlugins,
      // R8：仅 enabled 时透传拆书参考包参数
      ...(genRefPack.enabled ? {
        pack_ids: genRefPack.packIds.length > 0 ? genRefPack.packIds : undefined,
        dimensions: genRefPack.dimensions.length > 0 ? genRefPack.dimensions : undefined,
        strength: genRefPack.strength,
      } : {}),
    };
    setShowGenModal(false);
    try {
      await startJob({
        kind: 'character_generate',
        title: name ? `AI 生成角色「${name}」` : 'AI 生成角色',
        projectId: currentProject.id,
        connect: (options) => characterApi.generateCharacterStream(payload, options),
        onSettled: (job) => {
          if (job.status !== 'done') return;
          toast.success('AI 角色已生成');
          void refreshCharacters();
          setGenForm({ name: '', role_type: 'supporting', background: '', requirements: '' });
        },
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'AI 生成失败');
    }
  };

  const EmptyIcon = filter === 'organization' ? Building : Users;
  const emptyTitle = filter === 'organization' ? '还没有组织' : filter === 'character' ? '还没有人物' : '还没有角色与组织';
  const emptyHint =
    filter === 'organization'
      ? '点击右上角「添加组织」手动创建，或用「AI 生成组织」让 AI 根据世界观设计一个势力。'
      : '点击右上角「添加角色」手动创建，或用「AI 生成角色」让 AI 根据项目设定生成人物。';

  return (
    <div className="animate-fade-in space-y-6">
      <section className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <h1 className="text-[28px] font-semibold tracking-tight text-content md:text-[32px]">角色与组织</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            管理故事中的人物与势力，这些设定会作为 AI 续写时的上下文。共 {charCount} 个人物 · {orgCount} 个组织。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={() => setShowGenOrgModal(true)} disabled={generatingOrg} className="hh-btn-ghost">
            {generatingOrg ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            AI 生成组织
          </button>
          <button onClick={openAddOrg} className="hh-btn-ghost">
            <Building className="h-4 w-4" />
            添加组织
          </button>
          <button onClick={() => setShowGenModal(true)} disabled={generating} className="hh-btn-secondary">
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4 text-brand" />}
            AI 生成角色
          </button>
          <button onClick={openAdd} className="hh-btn-primary">
            <Plus className="h-4 w-4" />
            添加角色
          </button>
        </div>
      </section>

      {/* 后台 AI 任务横幅：通用弹窗最小化后在这里看进度 / 重新打开 / 停止 */}
      <AIJobBanner projectId={currentProject?.id} />

      <div className="inline-flex border border-surface-border bg-white/60 p-1">
        {([
          { key: 'all', label: '全部', count: characters.length, icon: null },
          { key: 'character', label: '人物', count: charCount, icon: Users },
          { key: 'organization', label: '组织', count: orgCount, icon: Building },
        ] as const).map(tab => {
          const selected = filter === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={cn(
                'inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium transition-colors',
                selected ? 'bg-brand text-white' : 'text-content-secondary hover:text-content'
              )}
            >
              {tab.icon && <tab.icon className="h-3.5 w-3.5" />}
              {tab.label}
              <span className={cn('tabular-nums', selected ? 'text-white/75' : 'text-content-tertiary')}>{tab.count}</span>
            </button>
          );
        })}
      </div>

      {filteredCharacters.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredCharacters.map((c) => {
            const roleLabel = getRoleDisplayName(c.role_type, c.is_organization ? '组织' : '路人');
            return (
              <article key={c.id} className="hh-panel flex flex-col p-5">
                <div className="flex flex-1 items-start gap-3.5">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-brand/10 text-base font-semibold text-brand">
                    {c.is_organization ? <Building className="h-5 w-5" /> : c.name.charAt(0)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="min-w-0 max-w-full truncate text-[15px] font-semibold text-content">{c.name}</h3>
                      {c.role_type && (
                        <span
                          className={cn(
                            'shrink-0 px-2 py-0.5 text-[11px] font-medium',
                            roleLabel === '主角' ? 'bg-brand/10 text-brand' : 'bg-surface-hover text-content-secondary'
                          )}
                        >
                          {roleLabel}
                        </span>
                      )}
                    </div>
                    {c.is_organization ? (
                      <div className="mt-1 space-y-1">
                        {c.organization_type && <p className="text-xs text-content-tertiary">{c.organization_type}</p>}
                        <p className="line-clamp-2 text-[13px] leading-[1.375rem] text-content-secondary">
                          {c.organization_purpose || c.background || '暂无描述'}
                        </p>
                        {c.member_names && c.member_names.length > 0 && (
                          <p className="text-[11px] text-content-tertiary">成员: {c.member_names.slice(0, 5).join('、')}{c.member_names.length > 5 ? ` 等${c.member_names.length}人` : ''}</p>
                        )}
                      </div>
                    ) : (
                      <p className="mt-1 line-clamp-2 text-[13px] leading-[1.375rem] text-content-secondary">
                        {c.personality || c.background || '暂无简介'}
                      </p>
                    )}
                  </div>
                </div>
                <div className="mt-4 flex items-center justify-end gap-1 border-t border-surface-border/80 pt-3">
                  <button onClick={() => openEdit(c)} className="hh-btn-ghost hh-btn-sm">
                    <Pencil className="h-3.5 w-3.5" />
                    编辑
                  </button>
                  <button
                    onClick={() => handleDelete(c.id, c.name, c.is_organization)}
                    className="hh-btn-ghost hh-btn-sm hover:bg-red-50 hover:text-red-600"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    删除
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <EmptyIcon className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">{emptyTitle}</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">{emptyHint}</p>
        </section>
      )}

      {showGenModal && createPortal(
        <div className="hh-modal-mask">
          <div className="hh-modal max-w-[560px]" role="dialog" aria-modal="true">
            <div className="hh-modal-head">
              <div className="min-w-0">
                <p className="hh-eyebrow">AI 生成</p>
                <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">AI 生成角色</h2>
                <p className="mt-1 text-sm leading-6 text-content-secondary">留空的项会由 AI 根据世界观与已有角色自动补全。</p>
              </div>
              <button onClick={() => setShowGenModal(false)} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="hh-modal-body space-y-4">
              <div>
                <label className="hh-label">角色名称（可选）</label>
                <input
                  value={genForm.name}
                  onChange={e => setGenForm(p => ({ ...p, name: e.target.value }))}
                  placeholder="留空由 AI 自动取名"
                  className="hh-field"
                />
              </div>
              <div>
                <label className="hh-label">角色定位</label>
                <select
                  value={genForm.role_type}
                  onChange={e => setGenForm(p => ({ ...p, role_type: e.target.value }))}
                  className="hh-field"
                >
                  <option value="protagonist">主角</option>
                  <option value="supporting">配角</option>
                  <option value="antagonist">反派</option>
                </select>
              </div>
              <div>
                <label className="hh-label">背景设定（可选）</label>
                <textarea
                  value={genForm.background}
                  onChange={e => setGenForm(p => ({ ...p, background: e.target.value }))}
                  placeholder="对角色背景的描述或要求..."
                  rows={2}
                  className="hh-textarea"
                />
              </div>
              <div>
                <label className="hh-label">额外要求（可选）</label>
                <textarea
                  value={genForm.requirements}
                  onChange={e => setGenForm(p => ({ ...p, requirements: e.target.value }))}
                  placeholder="如：需要有修仙背景、性格冷酷..."
                  rows={2}
                  className="hh-textarea"
                />
              </div>
              <MCPSelector
                value={{ enable: enableMcp, selected: selectedPlugins }}
                onChange={({ enable, selected }) => {
                  setEnableMcp(enable);
                  setSelectedPlugins(selected);
                }}
              />
              {currentProject?.id && (
                <ReferencePackSelector
                  projectId={currentProject.id}
                  value={genRefPack}
                  onChange={setGenRefPack}
                  hint="让本次角色生成参考拆书的角色塑造手法"
                  disabledTitle="使用拆书参考包作为对标"
                />
              )}
            </div>
            <div className="hh-modal-foot">
              <button onClick={() => setShowGenModal(false)} className="hh-btn-ghost">
                取消
              </button>
              <button onClick={handleGenerate} disabled={generating} className="hh-btn-primary">
                {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {generating ? '生成中...' : '开始生成'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {showGenOrgModal && createPortal(
        <div className="hh-modal-mask">
          <div className="hh-modal max-w-[520px]" role="dialog" aria-modal="true">
            <div className="hh-modal-head">
              <div className="min-w-0">
                <p className="hh-eyebrow">AI 生成</p>
                <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">AI 生成组织</h2>
                <p className="mt-1 text-sm leading-6 text-content-secondary">描述你想要的势力，AI 会结合世界观生成组织的类型、宗旨与背景。</p>
              </div>
              <button onClick={() => setShowGenOrgModal(false)} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="hh-modal-body space-y-4">
              <div>
                <label className="hh-label">组织名称（可选）</label>
                <input
                  value={genOrgForm.name}
                  onChange={e => setGenOrgForm(p => ({ ...p, name: e.target.value }))}
                  placeholder="留空由 AI 自动命名"
                  className="hh-field"
                />
              </div>
              <div>
                <label className="hh-label">组织要求描述</label>
                <textarea
                  value={genOrgForm.requirements}
                  onChange={e => setGenOrgForm(p => ({ ...p, requirements: e.target.value }))}
                  placeholder="如：一个修仙宗门、纪律森严、位于北方雪山..."
                  rows={4}
                  className="hh-textarea"
                />
              </div>
            </div>
            <div className="hh-modal-foot">
              <button onClick={() => setShowGenOrgModal(false)} className="hh-btn-ghost">
                取消
              </button>
              <button onClick={handleGenerateOrg} disabled={generatingOrg} className="hh-btn-primary">
                {generatingOrg ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {generatingOrg ? '生成中...' : '开始生成'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {showModal && createPortal(
        <div className="hh-modal-mask">
          <div className="hh-modal max-w-[640px]" role="dialog" aria-modal="true">
            <div className="hh-modal-head">
              <div className="min-w-0">
                <p className="hh-eyebrow">{form.is_organization ? '组织' : '角色'}</p>
                <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">
                  {editingId ? (form.is_organization ? '编辑组织' : '编辑角色') : form.is_organization ? '添加组织' : '添加角色'}
                </h2>
                <p className="mt-1 text-sm leading-6 text-content-secondary">
                  {form.is_organization
                    ? '记录组织的类型、宗旨、风格与背景，保存后可在这里维护在籍成员。'
                    : '记录角色的定位、性格与背景故事，AI 生成章节时会参考这些设定。'}
                </p>
              </div>
              <button onClick={() => setShowModal(false)} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="hh-modal-body space-y-4">
              <div>
                <label className="hh-label">名称</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                  placeholder={form.is_organization ? '组织名称' : '角色名字'}
                  className="hh-field"
                />
              </div>

              {form.is_organization ? (
                <>
                  <div>
                    <label className="hh-label">组织类型</label>
                    <input
                      value={form.organization_type}
                      onChange={(e) => setForm((p) => ({ ...p, organization_type: e.target.value }))}
                      placeholder="如：宗门、家族、商会、势力"
                      className="hh-field"
                    />
                  </div>
                  <div>
                    <label className="hh-label">组织宗旨</label>
                    <textarea
                      value={form.organization_purpose}
                      onChange={(e) => setForm((p) => ({ ...p, organization_purpose: e.target.value }))}
                      placeholder="组织的宗旨或核心目标…"
                      rows={2}
                      className="hh-textarea"
                    />
                  </div>
                  <div>
                    <label className="hh-label">组织风格/氛围</label>
                    <textarea
                      value={form.personality}
                      onChange={(e) => setForm((p) => ({ ...p, personality: e.target.value }))}
                      placeholder="如：纪律严明、唯利是图…"
                      rows={2}
                      className="hh-textarea"
                    />
                  </div>
                  <div>
                    <label className="hh-label">背景描述</label>
                    <textarea
                      value={form.background}
                      onChange={(e) => setForm((p) => ({ ...p, background: e.target.value }))}
                      placeholder="组织的历史、势力范围等…"
                      rows={3}
                      className="hh-textarea"
                    />
                  </div>

                  {editingId && (
                    <div className="hh-subpanel space-y-3 p-4">
                      <div className="flex items-center gap-2">
                        <Users className="h-4 w-4 text-content-secondary" />
                        <span className="text-sm font-medium text-content">组织成员</span>
                        <span className="text-xs text-content-tertiary tabular-nums">({orgMembers.length}人)</span>
                      </div>

                      {orgMembers.length > 0 ? (
                        <ul className="max-h-40 divide-y divide-surface-border/80 overflow-y-auto border border-surface-border/80 bg-white/70">
                          {orgMembers.map((m) => (
                            <li key={String(m.id)} className="flex items-center justify-between gap-2 px-3 py-2">
                              <div className="min-w-0 flex-1">
                                <span className="text-xs font-medium text-content">{String(m.character_name || '未知')}</span>
                                <span className="ml-1.5 text-[11px] text-content-tertiary">{String(m.position || '成员')}</span>
                                {Boolean(m.status) && m.status !== 'active' && <span className="ml-1 text-[10px] text-red-500">({String(m.status)})</span>}
                              </div>
                              <button
                                onClick={() => handleRemoveMember(String(m.id))}
                                className="hh-icon-btn-plain h-7 w-7 hover:text-red-500"
                                title="移除成员"
                                aria-label="移除成员"
                              >
                                <UserMinus className="h-3.5 w-3.5" />
                              </button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="py-2 text-center text-xs text-content-tertiary">暂无成员</p>
                      )}

                      <div className="flex items-end gap-2">
                        <div className="min-w-0 flex-1">
                          <label className="hh-label">选择角色</label>
                          <select
                            value={addMemberId}
                            onChange={(e) => setAddMemberId(e.target.value)}
                            className="hh-field"
                          >
                            <option value="">选择角色加入…</option>
                            {characters
                              .filter(c => !c.is_organization && !orgMembers.some(m => m.character_id === c.id))
                              .map(c => <option key={c.id} value={c.id}>{c.name}</option>)
                            }
                          </select>
                        </div>
                        <div className="w-28 shrink-0">
                          <label className="hh-label">职位</label>
                          <input
                            value={addMemberPos}
                            onChange={(e) => setAddMemberPos(e.target.value)}
                            placeholder="成员"
                            className="hh-field"
                          />
                        </div>
                        <button onClick={handleAddMember} disabled={!addMemberId} className="hh-btn-secondary shrink-0">
                          <UserPlus className="h-4 w-4" />
                          添加
                        </button>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div>
                    <label className="hh-label">角色类型</label>
                    <select
                      value={form.role_type}
                      onChange={(e) => setForm((p) => ({ ...p, role_type: e.target.value }))}
                      className="hh-field"
                    >
                      {ROLE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="hh-label">性格特点</label>
                    <textarea
                      value={form.personality}
                      onChange={(e) => setForm((p) => ({ ...p, personality: e.target.value }))}
                      placeholder="描述角色的性格特点…"
                      rows={3}
                      className="hh-textarea"
                    />
                  </div>
                  <div>
                    <label className="hh-label">背景故事</label>
                    <textarea
                      value={form.background}
                      onChange={(e) => setForm((p) => ({ ...p, background: e.target.value }))}
                      placeholder="描述角色的背景故事…"
                      rows={3}
                      className="hh-textarea"
                    />
                  </div>
                </>
              )}

              <div className="border border-brand/25 bg-brand/5 p-4">
                <label className="hh-label">
                  {editingId ? '修改原因' : '添加原因'}
                  <span className="ml-1.5 text-xs font-normal text-content-tertiary">AI 生成时会参考此信息</span>
                </label>
                <input
                  value={form.reason}
                  onChange={(e) => setForm((p) => ({ ...p, reason: e.target.value }))}
                  placeholder={editingId ? '如：修正角色设定、补充信息…' : '如：剧情需要新增此角色…'}
                  className="hh-field"
                />
              </div>
            </div>
            <div className="hh-modal-foot">
              <button onClick={() => setShowModal(false)} className="hh-btn-ghost">
                取消
              </button>
              <button onClick={handleSubmit} disabled={submitting || !form.name.trim()} className="hh-btn-primary">
                {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
                {submitting ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
