/**
 * 智能助笔 · 共创室的小部件（参考岚笺 creative-team）：成员头像、状态点、@成员菜单、
 * 团队设置（上下文上限、每位成员可单独指定模型）、上下文用量圆环、「下一步」建议条、规划草案卡片（作者确认才定稿）。
 * 外观是 AI 助手面板（globals.css 的 as-*），配色沿用全站 token。
 */
import { useEffect, useRef, useState } from 'react';
import { AtSign, Check, Compass, Hourglass, Loader2, SlidersHorizontal, X } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { assistantApi } from '@/services/api';
import type {
  AssistantContextUsage, AssistantDeferred, AssistantMember, AssistantPlan, AssistantProgress, AssistantTeam,
} from '@/types/assistant';
import { memberTone, planLink } from '@/utils/cocreation';
import { confirmPlan, errorDetail } from './changeActions';
import { formatTokens, parseWindowInput, sourceText, usageTitle, usageTone, windowChoice } from '@/utils/contextUsage';

const TONE_TEXT = { ok: 'text-content-tertiary', warn: 'text-gold-500', full: 'text-cinnabar' } as const;

export type StatusTone = 'green' | 'orange' | 'red' | 'gray' | 'brand';

const DOT: Record<StatusTone, string> = {
  green: 'bg-emerald-500', orange: 'bg-gold-400', red: 'bg-cinnabar', gray: 'bg-neutral-300', brand: 'bg-brand',
};

/** 回复里的 **加粗** 显示成粗体，其余照原样换行（字号、颜色跟着外层的 as-prose / as-user-msg 走） */
export function RichText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*\n]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) => (part.startsWith('**') && part.endsWith('**') && part.length > 4
        ? <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
        : <span key={i}>{part}</span>))}
    </>
  );
}

/** 状态：小圆点 + 文字 */
export function StatusDot({ tone, label }: { tone: StatusTone; label: string }) {
  return (
    <span className="as-status">
      <span className={cn('as-dot', DOT[tone])} />
      {label}
    </span>
  );
}

/** 输入框里的上下文用量（参照写代码 agent）：小圆环 + 百分比，悬停看分项；空闲时是下一条要求的估算，运行中每一步刷新 */
export function ContextMeter({ usage, compacting }: { usage: AssistantContextUsage | null; compacting?: boolean }) {
  if (!usage) return null;
  const tone = usageTone(usage.percent);
  const r = 6;
  const c = 2 * Math.PI * r;
  const filled = (Math.min(100, Math.max(0, usage.percent)) / 100) * c;
  return (
    <span title={usageTitle(usage)} className={cn('flex cursor-help items-center gap-1 text-[11px] tabular-nums', TONE_TEXT[tone])}>
      <svg viewBox="0 0 16 16" className="h-4 w-4 -rotate-90" aria-hidden>
        <circle cx="8" cy="8" r={r} fill="none" stroke="currentColor" strokeOpacity={0.2} strokeWidth={2} />
        <circle cx="8" cy="8" r={r} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeDasharray={`${filled} ${c}`} />
      </svg>
      {compacting ? '压缩中…' : `${usage.percent}%`}
    </span>
  );
}

function ContextLimit({ projectId, team, onChange }: { projectId: string; team: AssistantTeam; onChange: (team: AssistantTeam) => void }) {
  const ctx = team.context;
  const [choice, setChoice] = useState(() => windowChoice(ctx.setting, ctx.presets));
  const [custom, setCustom] = useState(() => (ctx.setting ? String(Math.round(ctx.setting / 1000)) : ''));
  const [saving, setSaving] = useState(false);

  const save = async (value: number | null) => {
    if (value === ctx.setting) return;
    setSaving(true);
    try {
      const next = await assistantApi.setContextWindow(projectId, value);
      onChange(next);
      toast.success(value ? `上下文上限改为 ${formatTokens(value)}` : `上下文上限改为自动（${formatTokens(next.context.window)}）`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '没保存成功');
    } finally {
      setSaving(false);
    }
  };

  const pick = (value: string) => {
    setChoice(value);
    if (value !== 'custom') void save(value ? Number(value) : null);
  };

  const saveCustom = () => {
    if (!custom.trim()) return;
    const value = parseWindowInput(custom, ctx.min, ctx.max);
    if (value === null) {
      toast.error(`上下文上限填 ${formatTokens(ctx.min)}–${formatTokens(ctx.max)}：按 K 填（100 = 100K），也可以写 1.5M`);
      return;
    }
    void save(value);
  };

  return (
    <div className="mx-4 mb-3 rounded-[10px] bg-surface-paper px-3.5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium text-content">上下文上限</span>
        <span className="ml-auto flex items-center gap-1.5">
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin text-content-tertiary" />}
          {choice === 'custom' && (
            <input
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              onBlur={saveCustom}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              placeholder="如 100（= 100K）"
              className="as-field h-8 w-28 text-[12px]"
            />
          )}
          <select
            value={choice}
            onChange={(e) => pick(e.target.value)}
            disabled={saving}
            className="h-8 w-auto cursor-pointer rounded-[8px] py-0 pl-2.5 pr-8 text-[12px]"
          >
            <option value="">自动（{formatTokens(ctx.auto)}）</option>
            {ctx.presets.map((p) => <option key={p} value={String(p)}>{formatTokens(p)}</option>)}
            <option value="custom">自定义…</option>
          </select>
        </span>
      </div>
      <p className="mt-2 text-[12px] leading-[1.6] text-content-tertiary">
        {sourceText(ctx.source, ctx.model, ctx.window)}。每次调用模型都按这个上限装填：装不下先把本轮较早的工具结果压成一句，
        较早的对话由模型压成「前情摘要」常驻。自动 = 按各成员用的模型查窗口，查不到按 64K；填得比模型实际窗口大会报错。
      </p>
    </div>
  );
}

const AVATAR_SIZE = { sm: 'h-5 w-5 text-[10px]', md: 'h-7 w-7 text-[12px]', lg: 'h-9 w-9 text-[14px]' } as const;

/** 成员头像：浅底 + 同色深字的首字，按成员区分颜色 */
export function MemberAvatar({ member, size = 'sm' }: { member: Pick<AssistantMember, 'initials' | 'name' | 'color'>; size?: keyof typeof AVATAR_SIZE }) {
  return (
    <span title={member.name} className={cn('inline-flex shrink-0 select-none items-center justify-center rounded-full font-medium leading-none', memberTone(member.color), AVATAR_SIZE[size])}>
      {member.initials}
    </span>
  );
}

/** 输入框工具条上的「@成员」：点开列出团队成员，选一位就在草稿开头 @ 他；底部进团队设置 */
export function MemberPicker({ members, onMention, onOpenSettings }: {
  members: AssistantMember[];
  onMention: (member: AssistantMember) => void;
  onOpenSettings: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative shrink-0">
      <button onClick={() => setOpen((v) => !v)} className={cn('as-chip', open && 'as-chip--on')} title="找团队里的某位成员" aria-expanded={open}>
        <AtSign className="h-3.5 w-3.5" />成员
      </button>
      {open && (
        <div className="as-menu bottom-full left-0 mb-2 w-72">
          {members.map((m) => (
            <button key={m.id} onClick={() => { onMention(m); setOpen(false); }} className="as-menu-item">
              <MemberAvatar member={m} size="md" />
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] text-content">{m.name}</span>
                <span className="block truncate text-[12px] text-content-tertiary">{m.responsibility}</span>
              </span>
              {m.model && <span className="max-w-[5.5rem] truncate text-[11px] text-content-tertiary" title={m.model}>{m.model}</span>}
            </button>
          ))}
          <div className="my-1 h-px bg-surface-border-light" />
          <button onClick={() => { onOpenSettings(); setOpen(false); }} className="as-menu-item text-[12px] text-content-secondary">
            <SlidersHorizontal className="h-3.5 w-3.5" />团队与模型设置
          </button>
        </div>
      )}
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
    <section className="as-card animate-scale-in">
      <header className="flex items-center justify-between px-4 pb-2.5 pt-3.5">
        <span className="text-[14px] font-semibold text-content">团队与模型</span>
        <button onClick={onClose} className="as-icon-btn h-7 w-7" title="收起"><X className="h-4 w-4" /></button>
      </header>
      <ContextLimit projectId={projectId} team={team} onChange={onChange} />
      <p className="px-4 pb-2.5 text-[12px] leading-[1.6] text-content-tertiary">
        主编默认发言，会把专业的事交给成员；你也可以用「@成员」直接找人。模型留空 = 跟随项目模型（填设置里可用的模型名）。
      </p>
      <ul className="divide-y divide-surface-border-light border-t border-surface-border-light">
        {team.members.map((m) => (
          <li key={m.id} className="flex items-center gap-3 px-4 py-2.5">
            <MemberAvatar member={m} size="md" />
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] text-content">{m.name}</span>
              <span className="block truncate text-[12px] text-content-tertiary">{m.responsibility}</span>
            </span>
            <input
              value={drafts[m.id] ?? ''}
              onChange={(e) => setDrafts((d) => ({ ...d, [m.id]: e.target.value }))}
              onBlur={() => void save(m)}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              placeholder="跟随项目模型"
              className="as-field h-8 w-36 text-[12px]"
            />
            {saving === m.id ? <Loader2 className="h-3.5 w-3.5 animate-spin text-content-tertiary" /> : m.context_window ? (
              <span className="w-9 text-right text-[11px] tabular-nums text-content-tertiary" title="这位成员调用模型时的上下文上限">
                {formatTokens(m.context_window)}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** 创作进度：输入框上方一行「下一步」，悬停看各层进度；按钮把建议填进输入框交给主编 */
export function NextStepHint({ progress, onAsk, disabled }: { progress: AssistantProgress; onAsk: (label: string) => void; disabled?: boolean }) {
  const step = progress.next_step;
  return (
    <div className="mb-2 flex items-center gap-2 px-1 text-[12px]" title={progress.text}>
      <Compass className="h-3.5 w-3.5 flex-none text-brand" />
      <span className="min-w-0 flex-1 truncate text-content-tertiary">
        下一步：<span className="text-content-secondary">{step.label}</span>
      </span>
      {step.action !== 'done' && (
        <button onClick={() => onAsk(step.label)} disabled={disabled} className="as-link">让主编推进</button>
      )}
    </div>
  );
}

/** 挂起的要求：上游卡片还没处理完时说明「处理完会接着做什么」；处理完了（又不是在这里处理的）给一个接着做的按钮 */
export function DeferredHint({ deferred, onContinue, disabled }: { deferred: AssistantDeferred; onContinue: () => void; disabled?: boolean }) {
  return (
    <div className="mb-2 flex items-center gap-2 px-1 text-[12px]">
      <Hourglass className="h-3.5 w-3.5 flex-none text-gold-500" />
      <span className="min-w-0 flex-1 truncate text-content-tertiary">
        {deferred.ready ? '上游卡片处理好了，可以接着：' : `处理完待确认的 ${deferred.pending} 张卡，团队会接着：`}
        <span className="text-content-secondary">{deferred.label}</span>
      </span>
      {deferred.ready && <button onClick={onContinue} disabled={disabled} className="as-link">接着做</button>}
    </div>
  );
}

export function PlanCard({ plan, confirmed, onConfirmed, onFailed, onNavigate, showActions = true }: {
  plan: AssistantPlan;
  /** 在本页（卡片或待确认栏）确认过 */
  confirmed?: boolean;
  onConfirmed?: (plan: AssistantPlan) => void;
  /** 没确认成功（多半是卷纲 / 章纲已被替换或删了）：让对话重新读一次，作废的草案就不再挂在待确认里 */
  onFailed?: () => void;
  onNavigate: (page: string) => void;
  /** false = 只看草案（在待确认栏里展开时，确认在那一行上，不再重复一个按钮） */
  showActions?: boolean;
}) {
  const [state, setState] = useState<'idle' | 'saving' | 'done'>(plan.confirmed || confirmed ? 'done' : 'idle');
  // 重新读取对话时服务端说已确认（可能是在谋篇页确认的）、或在待确认栏里确认了：跟着改，别再显示成草案
  useEffect(() => {
    if (plan.confirmed || confirmed) setState('done');
  }, [plan.confirmed, confirmed]);

  const confirm = async () => {
    setState('saving');
    try {
      await confirmPlan(plan);
      setState('done');
      onConfirmed?.(plan);
      toast.success(plan.kind === 'outlines' ? '章纲已确认，可以开写了' : '卷纲已确认');
    } catch (err) {
      setState('idle');
      toast.error(`没确认成功：${errorDetail(err)}`);
      onFailed?.();
    }
  };
  const status: { tone: StatusTone; label: string } = plan.gone
    ? { tone: 'gray', label: '已失效' }
    : state === 'done' ? { tone: 'green', label: '已确认' } : { tone: 'orange', label: '草案' };

  const rows: { key: string; head: string; body: string }[] = plan.kind === 'volumes'
    ? plan.volumes.map((v) => ({ key: v.id, head: `第${v.volume_number}卷《${v.title}》第 ${v.chapter_start}-${v.chapter_end} 章`, body: v.summary }))
    : plan.kind === 'units'
      ? plan.volume.units.map((u) => ({ key: String(u.index), head: `单元 ${u.index}《${u.title}》第 ${u.chapter_start}-${u.chapter_end} 章`, body: u.story }))
      : plan.chapters.map((c) => ({ key: c.id, head: `第 ${c.chapter_number} 章《${c.title}》`, body: c.plot_points }));

  return (
    <section className="as-card">
      <header className="as-card-head">
        <div className="flex items-center gap-2">
          <span className="as-kind">规划草案</span>
          <span className="ml-auto"><StatusDot tone={status.tone} label={status.label} /></span>
        </div>
        <p className="mt-1.5 text-[14px] font-semibold text-content">{plan.title}</p>
      </header>
      <ol className="max-h-64 space-y-2 overflow-y-auto px-4 pb-3.5">
        {rows.map((r) => (
          <li key={r.key} className="text-[13px] leading-[1.6]">
            <span className="text-content">{r.head}</span>
            {r.body && <span className="block line-clamp-2 text-[12px] text-content-tertiary">{r.body}</span>}
          </li>
        ))}
      </ol>
      {plan.kind === 'units' && plan.volume.threads.length > 0 && (
        <p className="mx-4 mb-3.5 rounded-[8px] bg-surface-paper px-3 py-2 text-[12px] leading-[1.6] text-content-secondary">线索：{plan.volume.threads.join('；')}</p>
      )}
      <footer className="as-card-foot">
        {plan.gone ? (
          <>
            <span className="mr-auto min-w-0 text-[12px] leading-[1.5] text-content-tertiary">这些卷纲 / 章纲已被重新生成或删掉，这份草案作废</span>
            <button onClick={() => onNavigate(planLink(plan))} className="as-link">去谋篇页看现在的</button>
          </>
        ) : (
          <button onClick={() => onNavigate(planLink(plan))} className="as-link mr-auto">去谋篇页修改</button>
        )}
        {showActions && !plan.gone && (
          <button onClick={() => void confirm()} disabled={state !== 'idle'} className="as-btn-primary">
            {state === 'saving' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            {state === 'done' ? '已确认' : '采用并确认'}
          </button>
        )}
      </footer>
    </section>
  );
}
