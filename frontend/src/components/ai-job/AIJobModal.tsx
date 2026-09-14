/** 通用 AI 任务弹窗：进度 / 模型思考计数 / 过程面板 / 正文预览；运行中可最小化到后台或停止 */
import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, Loader2, Minimize2, Square, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAIJobsStore } from '@/store/aiJobsStore';
import { kindLabel, type AIJobState, type AIJobStatus } from '@/types/ai_job';
import { AIJobProcess } from './AIJobProcess';
import { formatElapsed, llmSummary } from './format';
import { useElapsedSeconds } from './useElapsedSeconds';

const STATUS_META: Record<AIJobStatus, { label: string; className: string }> = {
  running: { label: '运行中', className: 'bg-brand/10 text-brand' },
  done: { label: '已完成', className: 'bg-emerald-50 text-emerald-600' },
  error: { label: '失败', className: 'bg-red-50 text-red-600' },
  cancelled: { label: '已停止', className: 'bg-surface-hover text-content-secondary' },
};

export function AIJobModal() {
  const job = useAIJobsStore((s) => (s.openJobId ? s.jobs[s.openJobId] ?? null : null));
  const closeModal = useAIJobsStore((s) => s.closeModal);
  const cancel = useAIJobsStore((s) => s.cancel);
  if (!job) return null;
  return <AIJobModalBody job={job} onMinimize={closeModal} onStop={() => void cancel(job.id)} onClose={closeModal} />;
}

function AIJobModalBody({
  job,
  onMinimize,
  onStop,
  onClose,
}: {
  job: AIJobState;
  onMinimize: () => void;
  onStop: () => void;
  onClose: () => void;
}) {
  const running = job.status === 'running';
  const elapsed = useElapsedSeconds(job.startedAt, running, job.finishedAt);
  const status = STATUS_META[job.status];
  const contentRef = useRef<HTMLPreElement>(null);
  const dismissAction = running ? onMinimize : onClose;

  useEffect(() => {
    if (contentRef.current) contentRef.current.scrollTop = contentRef.current.scrollHeight;
  }, [job.content]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') dismissAction();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dismissAction]);

  return createPortal(
    <div className="hh-modal-mask z-[70]" onClick={dismissAction}>
      <div className="hh-modal max-w-[760px]" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="hh-modal-head">
          <div className="min-w-0">
            <p className="hh-eyebrow">AI 任务 · {kindLabel(job.kind)}</p>
            <h2 className="mt-2 truncate text-xl font-semibold tracking-tight text-content">{job.title}</h2>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-content-tertiary tabular-nums">
              <span className={cn('px-1.5 py-0.5 font-medium', status.className)}>{status.label}</span>
              <span>已用 {formatElapsed(elapsed)}</span>
              {job.connection === 'connecting' && (
                // lastSeq 为 0 说明这条 SSE 还没收到过任何事件：是首次连接（后端可能正忙），不是断线重连
                <span className="text-amber-600">{job.lastSeq > 0 ? '正在重连…' : '正在连接后端…'}</span>
              )}
              {job.connection === 'lost' && (
                <span className="text-amber-600">连接已断开，任务可能仍在后台运行；刷新页面可重连</span>
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={dismissAction}
            className="hh-icon-btn-plain -mr-2 -mt-1"
            aria-label={running ? '最小化到后台' : '关闭'}
            title={running ? '最小化到后台（任务继续运行）' : '关闭'}
          >
            {running ? <Minimize2 className="h-4 w-4" /> : <X className="h-4 w-4" />}
          </button>
        </div>

        <div className="hh-modal-body space-y-5">
          <section>
            <div className="hh-progress">
              <div
                className={cn(
                  'hh-progress-bar',
                  job.status === 'error' && 'bg-red-500',
                  job.status === 'cancelled' && 'bg-content-tertiary',
                )}
                style={{ width: `${job.progress?.pct ?? (running ? 2 : 100)}%` }}
              />
            </div>
            <p className="mt-2 flex items-center gap-2 text-sm text-content-secondary">
              {running && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand" />}
              <span className="min-w-0 truncate" title={job.progress?.message}>
                {job.progress?.message || (running ? '正在准备…' : status.label)}
              </span>
              {typeof job.wordCount === 'number' && (
                <span className="shrink-0 text-xs text-content-tertiary tabular-nums">{job.wordCount.toLocaleString()} 字</span>
              )}
            </p>
            {job.llm && <p className="mt-1 text-xs text-content-tertiary tabular-nums">{llmSummary(job.llm)}</p>}
          </section>

          <AIJobProcess job={job} />

          {job.content && (
            <section>
              <p className="mb-1.5 text-xs font-medium text-content-secondary">生成内容预览</p>
              <pre
                ref={contentRef}
                className="hh-subpanel max-h-60 overflow-y-auto whitespace-pre-wrap p-3 font-sans text-sm leading-6 text-content"
              >
                {job.content}
              </pre>
            </section>
          )}

          {job.status === 'error' && job.error && (
            <p className="flex items-start gap-2 border border-red-200 bg-red-50/80 px-3 py-2 text-sm text-red-600">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              {job.error}
            </p>
          )}
          {job.status === 'cancelled' && job.error && <p className="text-sm text-content-secondary">{job.error}</p>}
        </div>

        <div className="hh-modal-foot">
          {running ? (
            <>
              <button type="button" onClick={onMinimize} className="hh-btn-ghost">
                <Minimize2 className="h-4 w-4" />
                后台运行
              </button>
              <button type="button" onClick={onStop} className="hh-btn-danger">
                <Square className="h-4 w-4" />
                停止
              </button>
            </>
          ) : (
            <button type="button" onClick={onClose} className="hh-btn-primary">
              关闭
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
