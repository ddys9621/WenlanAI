/** 顶栏 AI 任务托盘：运行中数量 + 下拉列表（查看 / 停止 / 移除），任何页面都能找回后台任务 */
import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Loader2, Sparkles, Square, X, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAIJobsStore, useAllAIJobs } from '@/store/aiJobsStore';
import { kindLabel, type AIJobState } from '@/types/ai_job';
import { formatElapsed } from './format';

export function AIJobTray() {
  const jobs = useAllAIJobs();
  const runningCount = jobs.filter((j) => j.status === 'running').length;
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open]);

  if (jobs.length === 0) return null;
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title="AI 任务"
        className={cn(
          'flex h-10 items-center gap-2 border px-3 text-sm',
          runningCount > 0
            ? 'border-brand/40 bg-brand/5 text-brand'
            : 'border-transparent text-content-secondary hover:border-surface-border hover:bg-white/70',
        )}
      >
        {runningCount > 0 ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
        <span className="hidden md:inline">AI 任务</span>
        {runningCount > 0 && <span className="tabular-nums">{runningCount}</span>}
      </button>
      {open && (
        <div className="hh-menu absolute right-0 top-full mt-2 max-h-[70vh] w-[360px] overflow-y-auto">
          <ul className="divide-y divide-surface-border/70">
            {jobs.map((j) => (
              <TrayRow key={j.id} job={j} onOpened={() => setOpen(false)} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TrayRow({ job, onOpened }: { job: AIJobState; onOpened: () => void }) {
  const openModal = useAIJobsStore((s) => s.openModal);
  const cancel = useAIJobsStore((s) => s.cancel);
  const dismiss = useAIJobsStore((s) => s.dismiss);
  const running = job.status === 'running';
  const elapsed = Math.max(0, Math.round(((job.finishedAt ?? Date.now()) - job.startedAt) / 1000));
  const summary = running
    ? `${job.progress?.pct ?? 0}% · 已用 ${formatElapsed(elapsed)}`
    : job.status === 'done'
      ? `已完成 · 用时 ${formatElapsed(elapsed)}`
      : job.status === 'error'
        ? `失败：${job.error ?? ''}`
        : '已停止';
  return (
    <li className="px-3 py-2.5 text-sm">
      <div className="flex items-center gap-2">
        {running ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand" />
        ) : job.status === 'done' ? (
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
        ) : (
          <XCircle className={cn('h-4 w-4 shrink-0', job.status === 'error' ? 'text-red-500' : 'text-content-tertiary')} />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-content">{job.title}</p>
          <p className="truncate text-xs text-content-tertiary tabular-nums">
            {kindLabel(job.kind)} · {summary}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            openModal(job.id);
            onOpened();
          }}
          className="hh-btn-ghost hh-btn-sm"
        >
          查看
        </button>
        {running ? (
          <button type="button" onClick={() => void cancel(job.id)} className="hh-icon-btn-plain text-red-500" title="停止" aria-label="停止">
            <Square className="h-3.5 w-3.5" />
          </button>
        ) : (
          <button type="button" onClick={() => dismiss(job.id)} className="hh-icon-btn-plain" title="移除" aria-label="移除">
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {running && (
        <div className="hh-progress mt-2">
          <div className="hh-progress-bar" style={{ width: `${job.progress?.pct ?? 0}%` }} />
        </div>
      )}
    </li>
  );
}
