/** 全局智能助笔 ·「任务」界面：本项目正在跑的后台任务、助笔的处理记录、之前的对话（只读回看）。 */
import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Eye, Loader2, RefreshCw, Sparkles, Square } from 'lucide-react';
import { cn } from '@/lib/utils';
import { assistantApi } from '@/services/api';
import { useAIJobsStore, useRunningAIJobs } from '@/store/aiJobsStore';
import { kindLabel } from '@/types/ai_job';
import type { AssistantRunStatus, AssistantRunView, AssistantSessionInfo, AssistantSessionView } from '@/types/assistant';
import { formatServerTime } from '@/utils/serverTime';

const RUN_STATUS: Record<AssistantRunStatus, { label: string; cls: string }> = {
  running: { label: '进行中', cls: 'lj-badge--candidate' },
  waiting_input: { label: '等你回答', cls: 'lj-badge--stale' },
  completed: { label: '已完成', cls: 'lj-badge--ok' },
  failed: { label: '失败', cls: 'lj-badge--danger' },
  cancelled: { label: '已停止', cls: 'lj-badge--muted' },
  interrupted: { label: '已中断', cls: 'lj-badge--stale' },
};

interface AssistantTasksProps {
  projectId: string;
  onOpenConversation: () => void;
}

export function AssistantTasks({ projectId, onOpenConversation }: AssistantTasksProps) {
  const running = useRunningAIJobs(projectId);
  const [runs, setRuns] = useState<AssistantRunView[]>([]);
  const [sessions, setSessions] = useState<AssistantSessionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reading, setReading] = useState<AssistantSessionView | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, s] = await Promise.all([assistantApi.runs(projectId), assistantApi.sessions(projectId)]);
      setRuns(r.items);
      setSessions(s.items);
    } catch {
      /* 读取失败保留上次的记录 */
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  if (reading) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex items-center gap-2 border-b border-surface-border-light px-3 py-2">
          <button onClick={() => setReading(null)} className="hh-btn-ghost hh-btn-sm h-7 px-2 text-[11px]"><ArrowLeft className="h-3 w-3" />任务目录</button>
          <p className="min-w-0 flex-1 truncate text-xs font-medium text-content">{reading.session?.title}</p>
          <span className="text-[10px] text-content-tertiary">只读回看</span>
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-3">
          {reading.messages.map((m) => (
            <article key={m.id} className={cn('rounded border px-3 py-2', m.role === 'user' ? 'border-surface-border-light bg-surface-paper' : 'border-surface-border bg-white')}>
              <p className="mb-0.5 text-[11px] text-content-tertiary">{m.role === 'user' ? '你' : '智能助笔'} · {formatServerTime(m.created_at)}</p>
              <p className="whitespace-pre-wrap break-words text-xs leading-6 text-content">{m.content}</p>
              {m.steps.length > 0 && <p className="mt-1 text-[11px] text-content-tertiary">处理记录 {m.steps.length} 步：{m.steps.map((s) => s.label).join(' → ')}</p>}
            </article>
          ))}
          {!reading.messages.length && <p className="text-center text-xs text-content-tertiary">这段对话没有消息</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-surface-border-light px-3 py-2">
        <p className="text-xs text-content-secondary">本项目的后台任务与助笔记录</p>
        <button onClick={() => void load()} disabled={loading} className="hh-btn-ghost hh-btn-sm h-7 px-2 text-[11px]">
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}刷新
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3">
        <section>
          <p className="mb-1 text-[11px] font-medium text-content-tertiary">正在运行 · {running.length}</p>
          {running.length ? (
            <ul className="divide-y divide-surface-border-light rounded border border-surface-border-light bg-white">
              {running.map((job) => (
                <li key={job.id} className="flex items-center gap-2 px-3 py-2">
                  <Loader2 className="h-3.5 w-3.5 flex-none animate-spin text-brand" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium text-content">{job.title || kindLabel(job.kind)}</span>
                    <span className="block truncate text-[11px] text-content-tertiary">{kindLabel(job.kind)}{job.progress?.message ? ` · ${job.progress.message}` : ''}</span>
                  </span>
                  {job.kind === 'assistant_run' ? (
                    <button onClick={onOpenConversation} className="rounded p-1 text-content-tertiary hover:bg-surface-hover hover:text-content" title="回到对话"><Sparkles className="h-3.5 w-3.5" /></button>
                  ) : (
                    <button onClick={() => useAIJobsStore.getState().openModal(job.id)} className="rounded p-1 text-content-tertiary hover:bg-surface-hover hover:text-content" title="查看过程"><Eye className="h-3.5 w-3.5" /></button>
                  )}
                  <button onClick={() => void useAIJobsStore.getState().cancel(job.id)} className="rounded p-1 text-content-tertiary hover:bg-cinnabar-wash hover:text-cinnabar" title="停止"><Square className="h-3.5 w-3.5" /></button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded border border-dashed border-surface-border bg-surface-paper px-3 py-3 text-center text-[11px] text-content-tertiary">没有正在运行的任务</p>
          )}
        </section>

        <section>
          <p className="mb-1 text-[11px] font-medium text-content-tertiary">助笔处理记录 · {runs.length}</p>
          {runs.length ? (
            <ul className="divide-y divide-surface-border-light rounded border border-surface-border-light bg-white">
              {runs.map((run) => {
                const status = RUN_STATUS[run.status] ?? RUN_STATUS.completed;
                return (
                  <li key={run.id}>
                    <button onClick={() => setExpanded((cur) => (cur === run.id ? null : run.id))} className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-surface-hover">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium text-content" title={run.goal}>{run.goal}</span>
                        <span className="block truncate text-[11px] text-content-tertiary">{run.message || '—'} · {run.steps.length} 步 · {formatServerTime(run.updated_at)}</span>
                      </span>
                      <span className={cn('lj-badge flex-none', status.cls)}>{status.label}</span>
                    </button>
                    {expanded === run.id && (
                      <div className="border-t border-surface-border-light bg-surface-paper px-3 py-2">
                        {run.steps.length ? (
                          <ol className="space-y-0.5 text-[11px] leading-5 text-content-secondary">
                            {run.steps.map((s, i) => <li key={i}>{i + 1}. {s.label} · {s.summary}</li>)}
                          </ol>
                        ) : <p className="text-[11px] text-content-tertiary">这轮没有调用工具，直接回复的。</p>}
                        {run.status === 'waiting_input' && (
                          <button onClick={onOpenConversation} className="hh-btn-secondary hh-btn-sm mt-2 h-7 text-[11px]">去回答</button>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="rounded border border-dashed border-surface-border bg-surface-paper px-3 py-3 text-center text-[11px] text-content-tertiary">还没有助笔处理记录</p>
          )}
        </section>

        <section>
          <p className="mb-1 text-[11px] font-medium text-content-tertiary">对话记录 · {sessions.length}</p>
          <ul className="divide-y divide-surface-border-light rounded border border-surface-border-light bg-white">
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => (s.archived ? void assistantApi.sessionById(projectId, s.id).then(setReading) : onOpenConversation())}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface-hover"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium text-content">{s.title}</span>
                    <span className="block text-[11px] text-content-tertiary">{s.message_count ?? 0} 条消息 · {formatServerTime(s.updated_at)}</span>
                  </span>
                  <span className={cn('lj-badge flex-none', s.archived ? 'lj-badge--muted' : 'lj-badge--ok')}>{s.archived ? '已归档' : '当前'}</span>
                </button>
              </li>
            ))}
            {!sessions.length && <li className="px-3 py-3 text-center text-[11px] text-content-tertiary">还没有对话</li>}
          </ul>
        </section>
      </div>
    </div>
  );
}
