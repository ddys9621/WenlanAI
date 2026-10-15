/**
 * 智能助笔 · 共创室的小部件（参考岚笺 creative-team）：成员头像、团队条（点一下 @成员）、
 * 团队设置（每位成员可单独指定模型）、创作进度条、规划草案卡片（作者确认才定稿）。
 */
import { useState } from 'react';
import { ArrowRight, Check, Compass, Loader2, Settings2, X } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { assistantApi, chapterOutlineApi, volumeApi } from '@/services/api';
import { emitAssistantData } from '@/store/assistantStore';
import type { AssistantMember, AssistantPlan, AssistantProgress, AssistantTeam } from '@/types/assistant';
import { memberTone, planConfirmTargets, planEntity, planLink } from '@/utils/cocreation';

export function MemberAvatar({ member, size = 'sm' }: { member: Pick<AssistantMember, 'initials' | 'color' | 'name'>; size?: 'sm' | 'md' }) {
  return (
    <span
      title={member.name}
      className={cn(
        'inline-flex flex-none items-center justify-center rounded font-semibold',
        size === 'sm' ? 'h-4 w-4 text-[10px]' : 'h-7 w-7 text-xs',
        memberTone(member.color),
      )}
    >
      {member.initials}
    </span>
  );
}

export function TeamBar({ members, onMention, onOpenSettings }: {
  members: AssistantMember[];
  onMention: (member: AssistantMember) => void;
  onOpenSettings: () => void;
}) {
  if (!members.length) return null;
  return (
    <div className="mb-1.5 flex items-center gap-1">
      <span className="mr-0.5 text-[10px] text-content-tertiary">找人</span>
      {members.map((m) => (
        <button key={m.id} onClick={() => onMention(m)} className="rounded p-0.5 hover:bg-surface-hover" title={`${m.name}：${m.responsibility}${m.model ? `（模型 ${m.model}）` : ''}`}>
          <MemberAvatar member={m} size="md" />
        </button>
      ))}
      <button onClick={onOpenSettings} className="ml-auto rounded p-1 text-content-tertiary hover:bg-surface-hover hover:text-content" title="团队与模型">
        <Settings2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export function TeamSettings({ projectId, team, onChange, onClose }: {
  projectId: string;
  team: AssistantTeam;
  onChange: (team: AssistantTeam) => void;
  onClose: () => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>(() => Object.fromEntries(team.members.map((m) => [m.id, m.model ?? ''])));
  const [saving, setSaving] = useState<string | null>(null);

  const save = async (member: AssistantMember) => {
    const value = (drafts[member.id] ?? '').trim();
    if (value === (member.model ?? '')) return;
    setSaving(member.id);
    try {
      onChange(await assistantApi.setMemberModel(projectId, member.id, value || null));
      toast.success(value ? `${member.name}改用 ${value}` : `${member.name}跟随项目模型`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '没保存成功');
    } finally {
      setSaving(null);
    }
  };

  return (
    <section className="rounded border border-surface-border bg-white px-3 py-2.5">
      <header className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-semibold text-content">共创团队</span>
        <button onClick={onClose} className="rounded p-1 text-content-tertiary hover:bg-surface-hover"><X className="h-3.5 w-3.5" /></button>
      </header>
      <p className="mb-2 text-[11px] leading-5 text-content-tertiary">
        主编默认发言，会把专业的事交给成员；你也可以用「@成员」直接找人。模型留空 = 跟随项目模型（填设置里可用的模型名）。
      </p>
      <ul className="space-y-1.5">
        {team.members.map((m) => (
          <li key={m.id} className="flex items-center gap-2">
            <MemberAvatar member={m} size="md" />
            <span className="min-w-0 flex-1">
              <span className="block text-xs font-medium text-content">{m.name}</span>
              <span className="block truncate text-[11px] text-content-tertiary">{m.responsibility}</span>
            </span>
            <input
              value={drafts[m.id] ?? ''}
              onChange={(e) => setDrafts((d) => ({ ...d, [m.id]: e.target.value }))}
              onBlur={() => void save(m)}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              placeholder="跟随项目模型"
              className="hh-field h-7 w-36 text-[11px]"
            />
            {saving === m.id && <Loader2 className="h-3.5 w-3.5 animate-spin text-brand" />}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ProgressStrip({ progress, onAsk, disabled }: { progress: AssistantProgress; onAsk: (label: string) => void; disabled?: boolean }) {
  const step = progress.next_step;
  return (
    <details className="border-b border-surface-border-light bg-brand-50/40 px-3 py-1.5 text-[11px]">
      <summary className="flex cursor-pointer select-none items-center gap-1.5 text-content-secondary">
        <Compass className="h-3 w-3 flex-none text-brand" />
        <span className="truncate">下一步：<span className="font-medium text-content">{step.label}</span></span>
        {step.action !== 'done' && (
          <button
            onClick={(e) => { e.preventDefault(); onAsk(step.label); }}
            disabled={disabled}
            className="ml-auto inline-flex flex-none items-center gap-0.5 rounded px-1.5 py-0.5 text-brand hover:bg-brand-50 disabled:opacity-40"
          >
            让主编推进<ArrowRight className="h-3 w-3" />
          </button>
        )}
      </summary>
      <pre className="mt-1 whitespace-pre-wrap font-sans leading-5 text-content-tertiary">{progress.text}</pre>
    </details>
  );
}

export function PlanCard({ plan, onNavigate }: { plan: AssistantPlan; onNavigate: (page: string) => void }) {
  const [state, setState] = useState<'idle' | 'saving' | 'done'>('idle');

  const confirm = async () => {
    const { volumeIds, outlineIds } = planConfirmTargets(plan);
    setState('saving');
    try {
      await Promise.all([
        ...volumeIds.map((id) => volumeApi.confirm(id)),
        ...outlineIds.map((id) => chapterOutlineApi.confirmChapterOutline(id)),
      ]);
      setState('done');
      emitAssistantData({ entity: planEntity(plan) });
      toast.success(plan.kind === 'outlines' ? '章纲已确认，可以开写了' : '卷纲已确认');
    } catch (err) {
      setState('idle');
      toast.error(err instanceof Error ? err.message : '没确认成功（可能已被修改或删除），去谋篇页看看');
    }
  };

  const rows: { key: string; head: string; body: string }[] = plan.kind === 'volumes'
    ? plan.volumes.map((v) => ({ key: v.id, head: `第${v.volume_number}卷《${v.title}》第 ${v.chapter_start}-${v.chapter_end} 章`, body: v.summary }))
    : plan.kind === 'units'
      ? plan.volume.units.map((u) => ({ key: String(u.index), head: `单元 ${u.index}《${u.title}》第 ${u.chapter_start}-${u.chapter_end} 章`, body: u.story }))
      : plan.chapters.map((c) => ({ key: c.id, head: `第 ${c.chapter_number} 章《${c.title}》`, body: c.plot_points }));

  return (
    <section className="mt-2 rounded border border-brand/30 bg-brand-50/30 px-2.5 py-2">
      <header className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-content">{plan.title}</span>
        <span className={cn('lj-badge', state === 'done' ? 'lj-badge--ok' : 'lj-badge--draft')}>{state === 'done' ? '已确认' : '草案'}</span>
      </header>
      <ol className="mt-1.5 max-h-56 space-y-1 overflow-y-auto">
        {rows.map((r) => (
          <li key={r.key} className="text-[11px] leading-5">
            <span className="font-medium text-content">{r.head}</span>
            {r.body && <span className="block line-clamp-2 text-content-tertiary">{r.body}</span>}
          </li>
        ))}
      </ol>
      {plan.kind === 'units' && plan.volume.threads.length > 0 && (
        <p className="mt-1 text-[11px] leading-5 text-content-secondary">线索：{plan.volume.threads.join('；')}</p>
      )}
      <div className="mt-1.5 flex items-center gap-1.5">
        <button onClick={() => void confirm()} disabled={state !== 'idle'} className="hh-btn-primary hh-btn-sm h-7 px-2 text-[11px]">
          {state === 'saving' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
          {state === 'done' ? '已确认' : '采用并确认'}
        </button>
        <button onClick={() => onNavigate(planLink(plan))} className="hh-btn-ghost hh-btn-sm h-7 px-2 text-[11px]">去谋篇页修改</button>
      </div>
    </section>
  );
}
