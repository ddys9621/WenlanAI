/**
 * 处理过程的时间线（模型每做一步先说一句在干什么，下面跟一行回执「已新建 5 项资料 · 已完成」）。
 * 有 note 的步骤先显示那句话，再显示回执；运行中的那一步转圈。旧消息没有 note，只列回执。
 * collapsible：存下的处理过程在窄屏（手机）上先收成一行「处理过程 3 步：读取 → 修改」，点开看每一步；宽屏照常展开。
 */
import { useState } from 'react';
import { Check, ChevronDown, Loader2, TriangleAlert } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface TimelineStep {
  label: string;
  /** 存下的步骤用 summary，运行中的用 detail */
  summary?: string;
  detail?: string;
  ok: boolean;
  note?: string;
  running?: boolean;
}

const narrowScreen = () => typeof window !== 'undefined' && Boolean(window.matchMedia?.('(max-width: 639px)').matches);

export function StepTimeline({ steps, collapsible = false }: { steps: TimelineStep[]; collapsible?: boolean }) {
  const [open, setOpen] = useState(() => !collapsible || !narrowScreen());
  if (!steps.length) return null;
  const failed = steps.some((s) => !s.ok && !s.running);
  return (
    <div className="space-y-2">
      {collapsible && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className={cn('as-receipt w-full text-left sm:hidden', failed && 'as-receipt--warn')}
        >
          {failed
            ? <TriangleAlert className="h-3.5 w-3.5 flex-none text-gold-500" />
            : <Check className="h-3.5 w-3.5 flex-none text-emerald-500" />}
          <span className="flex-none text-content">处理过程 {steps.length} 步</span>
          <span className="min-w-0 truncate text-content-tertiary">{steps.map((s) => s.label).join(' → ')}</span>
          <ChevronDown className={cn('ml-auto h-3.5 w-3.5 flex-none text-content-tertiary transition-transform', open && 'rotate-180')} />
        </button>
      )}
      <ol className={cn('space-y-2', collapsible && !open && 'max-sm:hidden')} aria-label="处理过程">
        {steps.map((s, i) => {
          const text = s.summary || s.detail || '';
          const state = s.running ? '进行中' : s.ok ? '已完成' : '没成功';
          return (
            <li key={i} className="space-y-1.5">
              {s.note && <p className="as-step-note">{s.note}</p>}
              <div className={cn('as-receipt', !s.ok && !s.running && 'as-receipt--warn')} title={text ? `${s.label} · ${text}` : s.label}>
                {s.running
                  ? <Loader2 className="h-3.5 w-3.5 flex-none animate-spin text-brand" />
                  : s.ok
                    ? <Check className="h-3.5 w-3.5 flex-none text-emerald-500" />
                    : <TriangleAlert className="h-3.5 w-3.5 flex-none text-gold-500" />}
                <span className="flex-none text-content">{s.label}</span>
                {text && <span className="min-w-0 truncate text-content-tertiary">{text}</span>}
                <span className="ml-auto flex-none pl-2 text-[11px] text-content-tertiary">{state}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
