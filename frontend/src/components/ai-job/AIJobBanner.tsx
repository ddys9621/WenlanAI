/** 页面横幅：当前项目里正在后台运行的 AI 任务（弹窗最小化后仍能看到进度、重新打开或停止） */
import { Loader2 } from 'lucide-react';
import { useAIJobsStore, useRunningAIJobs } from '@/store/aiJobsStore';
import type { AIJobSummary } from '@/types/ai_job';
import { formatElapsed, llmSummary } from './format';
import { useElapsedSeconds } from './useElapsedSeconds';

export function AIJobBanner({ projectId, kinds }: { projectId?: string | null; kinds?: string[] }) {
  const jobs = useRunningAIJobs(projectId, kinds);
  const openJobId = useAIJobsStore((s) => s.openJobId);
  const visible = jobs.filter((j) => j.id !== openJobId); // 弹窗正开着的那个不重复显示
  if (visible.length === 0) return null;
  return (
    <div className="space-y-2">
      {visible.map((j) => (
        <BannerRow key={j.id} job={j} />
      ))}
    </div>
  );
}

function BannerRow({ job }: { job: AIJobSummary }) {
  const openModal = useAIJobsStore((s) => s.openModal);
  const cancel = useAIJobsStore((s) => s.cancel);
  const elapsed = useElapsedSeconds(job.startedAt, true, null);
  return (
    <section className="hh-panel flex flex-col gap-2 border-l-4 border-brand px-5 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="flex min-w-0 items-center gap-2 text-content">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand" />
          <span className="shrink-0 font-medium">{job.title}</span>
          <span className="truncate text-content-secondary">{job.progress?.message}</span>
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <button type="button" onClick={() => openModal(job.id)} className="hh-btn-ghost hh-btn-sm">
            查看
          </button>
          <button type="button" onClick={() => void cancel(job.id)} className="hh-btn-ghost hh-btn-sm text-red-500 hover:bg-red-50">
            停止
          </button>
        </div>
      </div>
      <div className="hh-progress">
        <div className="hh-progress-bar" style={{ width: `${job.progress?.pct ?? 0}%` }} />
      </div>
      <p className="text-xs text-content-tertiary tabular-nums">
        {job.llm ? llmSummary(job.llm) : '等待模型响应…'} · 已用 {formatElapsed(elapsed)}
      </p>
    </section>
  );
}
