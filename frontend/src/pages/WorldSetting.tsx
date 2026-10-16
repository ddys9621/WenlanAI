import { useState, useEffect, useRef, type ReactNode } from 'react';
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
  BookMarked,
  SlidersHorizontal,
  Sparkles,
  type LucideIcon,
} from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useStore } from '@/store';
import { useProjectSync } from '@/store/hooks';
import { wizardStreamApi } from '@/services/api';
import type { PlatformPreset, Project } from '@/types';
import { mergeUntouched } from '@/utils/draftMerge';
import { MCPSelector } from '@/components/MCPSelector';
import { KbReferenceHint } from '@/components/knowledge/KbReferenceHint';
import { useProjectKbLink } from '@/hooks/useProjectKbLink';

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
  platform_preset: PlatformPreset | '';
  world_time_period: string;
  world_location: string;
  world_atmosphere: string;
  world_rules: string;
}

const PLATFORM_OPTIONS: { value: PlatformPreset | ''; label: string; description: string }[] = [
  { value: '', label: '通用', description: '不套平台写法，单章字数按章纲。' },
  { value: 'qidian', label: '起点（付费连载）', description: '单章 3000-4000 字，设定自洽、断章拉订阅。' },
  { value: 'fanqie', label: '番茄（免费阅读）', description: '单章 2000-2500 字，开头三行进冲突，每章末都留钩子。' },
  { value: 'jinjiang', label: '晋江（女频）', description: '情感线为主，人物关系与潜台词，章末停在情绪变化点。' },
  { value: 'qimao', label: '七猫（免费阅读）', description: '单章 2000-3000 字，节奏快、爽点直给、章末必留钩子。' },
];

const longformFromProject = (p: { platform_preset?: PlatformPreset | null }) => ({
  platform_preset: (p.platform_preset ?? '') as PlatformPreset | '',
});

const formFromProject = (p: Project): WorldSettingForm => ({
  title: p.title || '',
  theme: p.theme || '',
  genre: p.genre || '',
  generation_prompt: p.generation_prompt || '',
  ...longformFromProject(p),
  world_time_period: p.world_time_period || '',
  world_location: p.world_location || '',
  world_atmosphere: p.world_atmosphere || '',
  world_rules: p.world_rules || '',
});

const TEXTAREA = 'hh-textarea px-4 py-3 leading-7 [field-sizing:content]';

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
  const kbLink = useProjectKbLink(currentProject?.id);
  const [form, setForm] = useState<WorldSettingForm>({
    title: '',
    theme: '',
    genre: '',
    generation_prompt: '',
    platform_preset: '',
    world_time_period: '',
    world_location: '',
    world_atmosphere: '',
    world_rules: '',
  });

  // 项目数据刷新（如智能助笔应用了修改）：只更新作者没动过的字段，正在编辑的内容不会被冲掉
  const baseRef = useRef<WorldSettingForm | null>(null);
  useEffect(() => {
    if (!currentProject) return;
    const next = formFromProject(currentProject);
    const base = baseRef.current;
    baseRef.current = next;
    setForm((prev) => (base ? mergeUntouched(prev, base, next) : next));
  }, [currentProject]);

  const setField = <K extends keyof WorldSettingForm>(key: K, value: WorldSettingForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

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
        platform_preset: form.platform_preset || null,
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
    if (currentProject) setForm(formFromProject(currentProject));
    setEditing(false);
  };

  const filledBlocks = BLOCKS.filter((block) => form[block.key].trim()).length;
  const totalChars = BLOCKS.reduce((sum, block) => sum + form[block.key].trim().length, 0);
  const promptChars = form.generation_prompt.trim().length;
  const hasContent = filledBlocks > 0;
  const platform = PLATFORM_OPTIONS.find((opt) => opt.value === form.platform_preset) ?? PLATFORM_OPTIONS[0];
  const status = editing
    ? { value: '编辑中', hint: '修改后记得保存' }
    : filledBlocks === BLOCKS.length
      ? { value: '已成稿', hint: '可随时 AI 重生成' }
      : hasContent
        ? { value: '待完善', hint: `还有 ${BLOCKS.length - filledBlocks} 个模块待补充` }
        : { value: '空白', hint: '手动填写或 AI 生成' };

  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">世界设定</h1>
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
          value={filledBlocks}
          unit={`/ ${BLOCKS.length}`}
          hint={filledBlocks === BLOCKS.length ? '结构完整' : '仍可补充'}
        />
        <StatItem label="设定字数" value={totalChars} unit="字" hint={totalChars > 0 ? '四个模块合计' : '尚未填写'} />
        <StatItem label="当前状态" value={status.value} hint={status.hint} />
        <StatItem label="最终提示词" value={promptChars} unit="字" hint={promptChars > 0 ? '已启用微调' : '未填写'} />
      </section>

      <section className="hh-panel p-6">
        <CardHeader
          icon={BookMarked}
          title="项目信息"
          description="生成世界观、角色、大纲与正文时，AI 都会参考这里的书名、类型与主题。"
        />
        <div className="mt-5 flex flex-wrap gap-x-4 gap-y-5">
          <Field id="ws-title" label="书名" required={editing} className="flex-[1_1_190px]">
            {editing ? (
              <input
                id="ws-title"
                value={form.title}
                onChange={(e) => setField('title', e.target.value)}
                placeholder="输入书名"
                className="hh-field"
              />
            ) : (
              <ReadLine value={form.title} />
            )}
          </Field>
          <Field id="ws-genre" label="类型" className="flex-[1_1_190px]">
            {editing ? (
              <input
                id="ws-genre"
                value={form.genre}
                onChange={(e) => setField('genre', e.target.value)}
                placeholder="如：都市、玄幻、悬疑"
                className="hh-field"
              />
            ) : (
              <ReadLine value={form.genre} />
            )}
          </Field>
          <Field
            id="ws-platform"
            label="目标平台"
            hint={`${platform.description}影响正文写法提示与新生成章纲的默认字数。`}
            className="flex-[1_1_190px]"
          >
            {editing ? (
              <select
                id="ws-platform"
                value={form.platform_preset}
                onChange={(e) => setField('platform_preset', e.target.value as PlatformPreset | '')}
                className="hh-field"
              >
                {PLATFORM_OPTIONS.map((opt) => (
                  <option key={opt.value || 'generic'} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            ) : (
              <ReadLine value={platform.label} />
            )}
          </Field>
        </div>
        <Field id="ws-theme" label="主题" className="mt-5">
          {editing ? (
            <textarea
              id="ws-theme"
              value={form.theme}
              onChange={(e) => setField('theme', e.target.value)}
              placeholder="这本书想表达什么，如：成长、复仇、救赎，或写一段完整的题旨。"
              rows={3}
              className={cn(TEXTAREA, 'min-h-[110px]')}
            />
          ) : (
            <ReadBlock value={form.theme} />
          )}
        </Field>
      </section>

      <section className="hh-panel p-6">
        <CardHeader
          icon={SlidersHorizontal}
          title="最终提示词"
          badge={<FillBadge filled={promptChars > 0} on="已启用" off="未填写" />}
          meta={`${promptChars} 字`}
          description="作为作者补充要求，追加到世界观、总纲和正文生成的提示词末尾。"
        />
        {editing ? (
          <textarea
            aria-label="最终提示词"
            value={form.generation_prompt}
            onChange={(e) => setField('generation_prompt', e.target.value)}
            placeholder="写会影响最终提交 prompt 的补充要求，例如：节奏更快、减少解释、对白更口语、每场戏必须有冲突。"
            rows={4}
            className={cn(TEXTAREA, 'mt-5 min-h-[138px]')}
          />
        ) : (
          <ReadBlock
            value={form.generation_prompt}
            empty="未填写。可以写全书通用的写作要求，例如：节奏更快、减少解释、对白更口语、每场戏必须有冲突。"
            className="mt-5"
          />
        )}
      </section>

      {!hasContent && !editing ? (
        <section className="hh-panel flex flex-col items-center px-6 py-12 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <BookOpenText className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-lg font-semibold tracking-tight text-content">还没有任何世界设定</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            时代背景、地点设定、氛围基调、世界规则四个模块，可以手动填写，也可以让 AI 根据项目资料生成初稿，再回来细修。
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-2.5">
            <button onClick={() => setEditing(true)} className="hh-btn-secondary">
              <Pencil className="h-4 w-4" />
              手动填写
            </button>
            <button onClick={() => setShowRegenModal(true)} disabled={regenerating} className="hh-btn-primary">
              {regenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              AI 生成初稿
            </button>
          </div>
        </section>
      ) : (
        <section className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,460px),1fr))] gap-4">
          {BLOCKS.map((block) => {
            const value = form[block.key];
            const chars = value.trim().length;
            return (
              <article key={block.key} className="hh-panel flex flex-col p-6">
                <CardHeader
                  icon={block.icon}
                  title={block.label}
                  badge={<FillBadge filled={chars > 0} on="已设定" off="待补充" />}
                  meta={`${chars} 字`}
                  description={block.description}
                />
                {editing ? (
                  <textarea
                    aria-label={block.label}
                    value={value}
                    onChange={(e) => setField(block.key, e.target.value)}
                    placeholder={block.placeholder}
                    rows={8}
                    className={cn(TEXTAREA, 'mt-5 min-h-[180px] flex-1 text-[15px] leading-7')}
                  />
                ) : (
                  <ReadBlock value={value} empty="暂未设定" className="mt-5 min-h-[180px] flex-1 text-[15px] leading-7" />
                )}
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
                <KbReferenceHint projectId={currentProject.id} link={kbLink} />
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

function StatItem({ label, value, unit, hint }: { label: string; value: ReactNode; unit?: string; hint: string }) {
  return (
    <div className="px-5 py-4 md:px-6">
      <p className="text-xs text-content-tertiary">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-content tabular-nums">
        {value}
        {unit && <span className="ml-1 text-sm font-medium tracking-normal text-content-tertiary">{unit}</span>}
      </p>
      <p className="mt-0.5 text-xs text-content-tertiary">{hint}</p>
    </div>
  );
}

function CardHeader({
  icon: Icon,
  title,
  badge,
  meta,
  description,
}: {
  icon: LucideIcon;
  title: string;
  badge?: ReactNode;
  meta?: string;
  description: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-brand/10 text-brand">
        <Icon className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <h2 className="truncate text-base font-semibold text-content">{title}</h2>
            {badge}
          </div>
          {meta && <span className="shrink-0 text-xs text-content-tertiary tabular-nums">{meta}</span>}
        </div>
        <p className="mt-0.5 text-[13px] leading-6 text-content-secondary">{description}</p>
      </div>
    </div>
  );
}

function FillBadge({ filled, on, off }: { filled: boolean; on: string; off: string }) {
  return <span className={cn('lj-badge', filled ? 'lj-badge--ok' : 'lj-badge--muted')}>{filled ? on : off}</span>;
}

function Field({
  id,
  label,
  required,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  required?: boolean;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <label htmlFor={id} className="hh-label">
        {label}
        {required && <span className="ml-0.5 text-red-500">*</span>}
      </label>
      {children}
      {hint && <p className="mt-1.5 text-xs leading-5 text-content-tertiary">{hint}</p>}
    </div>
  );
}

function ReadLine({ value }: { value: string }) {
  const text = value.trim();
  return (
    <div className={cn('hh-subpanel flex h-10 items-center px-3 text-sm', text ? 'text-content' : 'text-content-tertiary')}>
      <span className="truncate" title={text || undefined}>{text || '未填写'}</span>
    </div>
  );
}

function ReadBlock({ value, empty = '未填写', className }: { value: string; empty?: string; className?: string }) {
  const text = value.trim();
  return (
    <div
      className={cn(
        'whitespace-pre-wrap break-words rounded border px-4 py-3 text-sm leading-7',
        text ? 'border-surface-border-light bg-surface-paper text-content' : 'border-dashed border-surface-border text-content-tertiary',
        className,
      )}
    >
      {text || empty}
    </div>
  );
}
