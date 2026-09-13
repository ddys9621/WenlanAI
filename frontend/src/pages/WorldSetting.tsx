import { useState, useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import {
  Pencil,
  Save,
  X,
  Globe,
  MapPin,
  Cloud,
  ScrollText,
  RefreshCw,
  Trash2,
  Loader2,
  BookOpenText,
  type LucideIcon,
} from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useStore } from '@/store';
import { useProjectSync } from '@/store/hooks';
import { wizardStreamApi } from '@/services/api';
import type { C3HookStyle } from '@/types';
import { MCPSelector } from '@/components/MCPSelector';
import {
  ReferencePackSelector,
  DEFAULT_SELECTOR_VALUE,
  type ReferencePackSelectorValue,
} from '@/components/ReferencePackSelector';

interface WorldBlock {
  key: 'world_time_period' | 'world_location' | 'world_atmosphere' | 'world_rules';
  label: string;
  icon: LucideIcon;
  placeholder: string;
  description: string;
}

interface WorldSettingForm {
  title: string;
  theme: string;
  genre: string;
  generation_prompt: string;
  c3_hook_style: C3HookStyle;
  world_time_period: string;
  world_location: string;
  world_atmosphere: string;
  world_rules: string;
}

const C3_HOOK_OPTIONS: { value: C3HookStyle; label: string; description: string }[] = [
  { value: 'none', label: '不留钩子（默认）', description: '兑现章爽完即收，靠爽感把读者带进下一章；适合付费连载。' },
  { value: 'soft', label: '收束 + 半钩', description: '收束场景后再落一个不解释的小异样（≤2 句）；适合免费平台，每章末都要钩子。' },
];

const BLOCKS: WorldBlock[] = [
  {
    key: 'world_time_period',
    label: '时代背景',
    icon: Globe,
    placeholder: '描述故事发生的时代背景…',
    description: '时代演进、社会结构与故事发生前的历史惯性。',
  },
  {
    key: 'world_location',
    label: '地点设定',
    icon: MapPin,
    placeholder: '描述故事发生的主要地点…',
    description: '核心舞台、地理关系与关键势力的空间分布。',
  },
  {
    key: 'world_atmosphere',
    label: '氛围基调',
    icon: Cloud,
    placeholder: '描述故事的整体氛围和基调…',
    description: '读者进入这个世界时最先感受到的情绪温度与质地。',
  },
  {
    key: 'world_rules',
    label: '世界规则',
    icon: ScrollText,
    placeholder: '描述世界中的特殊规则或设定…',
    description: '这个世界的底层运作方式、禁忌、约束与代价。',
  },
];

export default function WorldSetting() {
  const { currentProject } = useStore();
  const { updateProject } = useProjectSync();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [showRegenModal, setShowRegenModal] = useState(false);
  const [regenEnableMcp, setRegenEnableMcp] = useState(false);
  const [regenPlugins, setRegenPlugins] = useState<string[]>([]);
  // R8：拆书参考包选择器
  const [regenRefPack, setRegenRefPack] = useState<ReferencePackSelectorValue>(DEFAULT_SELECTOR_VALUE);
  const [form, setForm] = useState<WorldSettingForm>({
    title: '',
    theme: '',
    genre: '',
    generation_prompt: '',
    c3_hook_style: 'none',
    world_time_period: '',
    world_location: '',
    world_atmosphere: '',
    world_rules: '',
  });

  useEffect(() => {
    if (currentProject) {
      setForm({
        title: currentProject.title || '',
        theme: currentProject.theme || '',
        genre: currentProject.genre || '',
        generation_prompt: currentProject.generation_prompt || '',
        c3_hook_style: currentProject.c3_hook_style === 'soft' ? 'soft' : 'none',
        world_time_period: currentProject.world_time_period || '',
        world_location: currentProject.world_location || '',
        world_atmosphere: currentProject.world_atmosphere || '',
        world_rules: currentProject.world_rules || '',
      });
    }
  }, [currentProject]);

  const handleRegenerate = async () => {
    if (!currentProject) return;
    setRegenerating(true);
    setShowRegenModal(false);
    try {
      await wizardStreamApi.regenerateWorldBuildingStream(
        currentProject.id,
        {
          enable_mcp: regenEnableMcp,
          selected_plugins: regenPlugins,
          title: form.title.trim(),
          theme: form.theme,
          genre: form.genre,
          generation_prompt: form.generation_prompt,
          // R8：仅 enabled 时透传拆书参考包参数
          ...(regenRefPack.enabled ? {
            pack_ids: regenRefPack.packIds.length > 0 ? regenRefPack.packIds : undefined,
            dimensions: regenRefPack.dimensions.length > 0 ? regenRefPack.dimensions : undefined,
            strength: regenRefPack.strength,
          } : {}),
        },
        {
          onProgress: (msg) => toast.info(msg, { id: 'regen-world' }),
          onResult: () => {
            toast.success('世界设定重新生成完成', { id: 'regen-world' });
            window.location.reload();
          },
          onError: (err) => toast.error(`重新生成失败: ${err}`, { id: 'regen-world' }),
        }
      );
    } catch {
      toast.error('重新生成失败');
    } finally {
      setRegenerating(false);
    }
  };

  const handleCleanup = async () => {
    if (!currentProject) return;
    if (!confirm('清理将删除向导生成的角色、大纲等数据，确定继续？')) return;
    setCleaning(true);
    try {
      await wizardStreamApi.cleanupWizardDataStream(currentProject.id, {
        onResult: (data) => {
          const d = data as { deleted?: { characters?: number; outlines?: number; chapters?: number } };
          toast.success(
            `清理完成：角色 ${d.deleted?.characters ?? 0}、大纲 ${d.deleted?.outlines ?? 0}、章节 ${d.deleted?.chapters ?? 0}`
          );
        },
        onError: (err) => toast.error(`清理失败: ${err}`),
      });
    } catch {
      toast.error('清理失败');
    } finally {
      setCleaning(false);
    }
  };

  const handleSave = async () => {
    if (!currentProject) return;
    if (!form.title.trim()) {
      toast.error('书名不能为空');
      return;
    }
    setSaving(true);
    try {
      await updateProject(currentProject.id, {
        ...form,
        title: form.title.trim(),
      });
      toast.success('世界设定已保存');
      setEditing(false);
    } catch {
      toast.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (currentProject) {
      setForm({
        title: currentProject.title || '',
        theme: currentProject.theme || '',
        genre: currentProject.genre || '',
        generation_prompt: currentProject.generation_prompt || '',
        c3_hook_style: currentProject.c3_hook_style === 'soft' ? 'soft' : 'none',
        world_time_period: currentProject.world_time_period || '',
        world_location: currentProject.world_location || '',
        world_atmosphere: currentProject.world_atmosphere || '',
        world_rules: currentProject.world_rules || '',
      });
    }
    setEditing(false);
  };

  const filledBlocks = BLOCKS.filter((block) => form[block.key].trim()).length;
  const totalChars = BLOCKS.reduce((sum, block) => sum + form[block.key].trim().length, 0);
  const promptChars = form.generation_prompt.trim().length;
  const hasContent = filledBlocks > 0;

  return (
    <div className="animate-fade-in space-y-6">
      <section className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <h1 className="text-[28px] font-semibold tracking-tight text-content md:text-[32px]">世界设定</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            把时代、地点、氛围与规则分开整理，先立好框架，再往里填充细节。
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          {!editing ? (
            <>
              <button
                onClick={handleCleanup}
                disabled={cleaning}
                className="hh-btn-ghost text-red-500 hover:bg-red-50 hover:text-red-600"
                title="删除向导生成的角色、大纲等数据"
              >
                {cleaning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                清理向导数据
              </button>
              <button onClick={() => setShowRegenModal(true)} disabled={regenerating} className="hh-btn-secondary">
                {regenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                重新生成
              </button>
              <button onClick={() => setEditing(true)} className="hh-btn-primary">
                <Pencil className="h-4 w-4" />
                编辑内容
              </button>
            </>
          ) : (
            <>
              <button onClick={handleCancel} className="hh-btn-ghost">
                <X className="h-4 w-4" />
                取消
              </button>
              <button onClick={handleSave} disabled={saving} className="hh-btn-primary">
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {saving ? '保存中…' : '保存修改'}
              </button>
            </>
          )}
        </div>
      </section>

      <section className="hh-panel grid grid-cols-2 divide-surface-border/80 md:grid-cols-4 md:divide-x">
        <StatItem
          label="完成模块"
          value={`${filledBlocks}/${BLOCKS.length}`}
          hint={filledBlocks === BLOCKS.length ? '结构完整' : '仍可补充'}
        />
        <StatItem label="内容字数" value={totalChars} hint={totalChars > 0 ? '当前已录入' : '尚未填写'} />
        <StatItem
          label="当前状态"
          value={editing ? '编辑中' : hasContent ? '已成稿' : '空白'}
          hint={editing ? '可直接修改' : '支持 AI 重生成'}
        />
        <StatItem label="最终提示词" value={`${promptChars} 字`} hint={promptChars > 0 ? '已启用微调' : '未填写'} />
      </section>

      <section className="hh-panel p-6">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-content">项目信息与最终提示词</h2>
            <p className="mt-1 text-sm leading-6 text-content-secondary">
              这里会影响后续提交给 AI 的项目上下文。最终提示词会追加到章节、场景、剧情和世界观重生成的 prompt 末尾。
            </p>
          </div>
          <span className="hh-tag shrink-0">项目级微调</span>
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-3">
          <ProjectField
            label="书名"
            value={form.title}
            editing={editing}
            placeholder="输入书名"
            onChange={(value) => setForm((prev) => ({ ...prev, title: value }))}
          />
          <ProjectField
            label="主题"
            value={form.theme}
            editing={editing}
            placeholder="输入主题"
            onChange={(value) => setForm((prev) => ({ ...prev, theme: value }))}
          />
          <ProjectField
            label="类型"
            value={form.genre}
            editing={editing}
            placeholder="如：都市、玄幻、悬疑"
            onChange={(value) => setForm((prev) => ({ ...prev, genre: value }))}
          />
        </div>

        <div className="mt-5">
          <div className="mb-1.5 flex items-center justify-between gap-3">
            <label className="text-[13px] font-medium text-content">最终提示词微调</label>
            <span className="text-xs text-content-tertiary tabular-nums">{promptChars} 字</span>
          </div>
          {editing ? (
            <textarea
              value={form.generation_prompt}
              onChange={(e) => setForm((prev) => ({ ...prev, generation_prompt: e.target.value }))}
              placeholder="写会影响最终提交 prompt 的补充要求，例如：节奏更快、减少解释、对白更口语、每场戏必须有冲突。"
              rows={6}
              className="hh-textarea min-h-[160px] leading-7"
            />
          ) : (
            <div className="hh-subpanel min-h-[120px] p-4">
              <p className={cn('whitespace-pre-wrap text-sm leading-7', form.generation_prompt.trim() ? 'text-content' : 'text-content-tertiary')}>
                {form.generation_prompt.trim() || '未填写。'}
              </p>
            </div>
          )}
        </div>

        <div className="mt-5">
          <label className="mb-1.5 block text-[13px] font-medium text-content">桥段兑现章（C3）末尾</label>
          {editing ? (
            <select
              value={form.c3_hook_style}
              onChange={(e) => setForm((prev) => ({ ...prev, c3_hook_style: e.target.value as C3HookStyle }))}
              className="hh-field"
            >
              {C3_HOOK_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          ) : (
            <p className="text-sm leading-6 text-content">
              {C3_HOOK_OPTIONS.find((opt) => opt.value === form.c3_hook_style)?.label}
            </p>
          )}
          <p className="mt-1 text-xs leading-5 text-content-tertiary">
            {C3_HOOK_OPTIONS.find((opt) => opt.value === form.c3_hook_style)?.description}
            影响桥段填充、章纲展开与正文写作三处 prompt；已填充的桥段需重新填充才会生效。
          </p>
        </div>
      </section>

      {!hasContent && !editing ? (
        <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <BookOpenText className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">还没有任何世界设定</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            点击右上角「编辑内容」手动填写，或用「重新生成」让 AI 根据项目资料生成初稿，再回来细修。
          </p>
        </section>
      ) : (
        <section className="grid gap-4 xl:grid-cols-2">
          {BLOCKS.map((block) => {
            const Icon = block.icon;
            const value = form[block.key];
            const filled = value.trim().length > 0;
            const wordCount = value.trim().length;

            return (
              <article key={block.key} className="hh-panel flex flex-col p-6">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-brand/10 text-brand">
                      <Icon className="h-5 w-5" />
                    </span>
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-base font-semibold text-content">{block.label}</h3>
                        <span
                          className={cn(
                            'px-2 py-0.5 text-[11px] font-medium',
                            filled ? 'bg-emerald-50 text-emerald-600' : 'bg-surface-hover text-content-secondary',
                          )}
                        >
                          {filled ? '已设定' : '待补充'}
                        </span>
                      </div>
                      <p className="mt-1 text-[13px] leading-6 text-content-secondary">{block.description}</p>
                    </div>
                  </div>
                  <span className="shrink-0 text-xs text-content-tertiary tabular-nums">{wordCount} 字</span>
                </div>

                <div className="mt-5 flex-1">
                  {editing ? (
                    <textarea
                      value={value}
                      onChange={(e) => setForm((prev) => ({ ...prev, [block.key]: e.target.value }))}
                      placeholder={block.placeholder}
                      rows={8}
                      className="hh-textarea min-h-[220px] leading-7"
                    />
                  ) : (
                    <div className="hh-subpanel min-h-[220px] p-4">
                      <p className={cn('whitespace-pre-wrap text-[15px] leading-8', filled ? 'text-content' : 'text-content-tertiary')}>
                        {filled ? value : '暂未设定'}
                      </p>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </section>
      )}

      {showRegenModal && createPortal(
        <div className="hh-modal-mask" onClick={() => setShowRegenModal(false)}>
          <div className="hh-modal max-w-[520px]" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
            <div className="hh-modal-head">
              <div>
                <p className="hh-eyebrow">AI 重生成</p>
                <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">重新生成世界设定</h2>
                <p className="mt-1 text-sm leading-6 text-content-secondary">
                  系统会基于项目已有信息生成新版本，当前四个模块的内容会被覆盖。确认前建议先保存重要文本。
                </p>
              </div>
              <button onClick={() => setShowRegenModal(false)} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="hh-modal-body space-y-3">
              <MCPSelector
                value={{ enable: regenEnableMcp, selected: regenPlugins }}
                onChange={({ enable, selected }) => {
                  setRegenEnableMcp(enable);
                  setRegenPlugins(selected);
                }}
              />
              {currentProject?.id && (
                <ReferencePackSelector
                  projectId={currentProject.id}
                  value={regenRefPack}
                  onChange={setRegenRefPack}
                  hint="让本次重生成参考拆书的世界观建模手法"
                  disabledTitle="使用拆书参考包作为对标"
                />
              )}
            </div>

            <div className="hh-modal-foot">
              <button onClick={() => setShowRegenModal(false)} className="hh-btn-ghost">
                取消
              </button>
              <button onClick={handleRegenerate} disabled={regenerating} className="hh-btn-primary">
                {regenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                确认重新生成
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

function StatItem({ label, value, hint }: { label: string; value: ReactNode; hint: string }) {
  return (
    <div className="px-5 py-4 md:px-6">
      <p className="text-xs text-content-tertiary">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-content tabular-nums">{value}</p>
      <p className="mt-0.5 text-xs text-content-tertiary">{hint}</p>
    </div>
  );
}

function ProjectField({
  label,
  value,
  editing,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  editing: boolean;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label className="hh-label">{label}</label>
      {editing ? (
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="hh-field" />
      ) : (
        <div className={cn('hh-subpanel flex min-h-11 items-center px-4 text-sm', value.trim() ? 'text-content' : 'text-content-tertiary')}>
          {value.trim() || '未填写'}
        </div>
      )}
    </div>
  );
}
