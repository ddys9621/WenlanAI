/**
 * 全局智能助笔 ·「任务」界面：本项目正在跑的后台任务、助笔的处理记录、之前的对话（只读回看）。
 * 回看用和对话一样的排版（作者浅灰块、团队正文），卡片只列名称和处理结果。
 */
import { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, Eye, Loader2, RefreshCw, Sparkles, Square } from 'lucide-react';
import { cn } from '@/lib/utils';
import { assistantApi } from '@/services/api';
import { useAIJobsStore, useRunningAIJobs } from '@/store/aiJobsStore';
import { kindLabel } from '@/types/ai_job';
import type {
  AssistantMessageView, AssistantRunStatus, AssistantRunView, AssistantSessionInfo, AssistantSessionView,
} from '@/types/assistant';
import { changeItems, type ChangeState } from '@/utils/cocreation';
import { formatServerTime } from '@/utils/serverTime';
import { MemberAvatar, RichText, StatusDot, type StatusTone } from './CocreationParts';

const CARD_TONE: Record<ChangeState, StatusTone> = {
  pending: 'orange', done: 'green', dropped: 'gray', open: 'brand', missing: 'red', gone: 'gray',
};

/** 回看时每条消息下的卡片：只读，列出名称和处理结果（状态和对话里的改动清单是同一套） */
function readCards(view: AssistantSessionView, m: AssistantMessageView): { id: string; label: string; status: { label: string; tone: StatusTone } }[] {
  const lookups = {
    fields: new Map(view.candidates.map((c) => [c.id, c])),
    entities: new Map(view.entity_candidates.map((c) => [c.id, c])),
    confirmedPlans: new Set<string>(),
  };
  const cards = { candidates: m.candidates, entity_candidates: m.entity_candidates ?? [], chapter_candidates: [], plans: m.plans ?? [] };
  return changeItems(cards, lookups).map((item) => ({
    id: item.key, label: `${item.tag} · ${item.title}`, status: { label: item.status, tone: CARD_TONE[item.state] },
  }));
}

const RUN_STATUS: Record<AssistantRunStatus, { label: string; tone: StatusTone }> = {
  running: { label: '进行中', tone: 'brand' },
  waiting_input: { label: '等你回答', tone: 'orange' },
  completed: { label: '已完成', tone: 'green' },
  failed: { label: '失败', tone: 'red' },
  cancelled: { label: '已停止', tone: 'gray' },
  interrupted: { label: '已中断', tone: 'orange' },
};

function Empty({ text }: { text: string }) {
  return <p className="rounded-[12px] border border-dashed border-surface-border-light px-4 py-4 text-center text-[13px] text-content-tertiary">{text}</p>;
}

/** 只读回看的一条消息：和对话里同样的排版，没有操作按钮 */
function ReadMessage({ view, m }: { view: AssistantSessionView; m: AssistantMessageView }) {
  const cards = readCards(view, m);
  const time = formatServerTime(m.created_at);
  if (m.role === 'user') {
    return (
      <div className="flex flex-col items-end">
        <span className="as-meta mb-1">{m.answer ? '回答提问 · ' : ''}{time}</span>
        <div className="as-user-msg max-w-[88%]"><RichText text={m.content} /></div>
      </div>
    );
  }
  const note = [m.delegated && '受主编委托', m.question && '向你提问', time].filter(Boolean).join(' · ');
  return (
    <div>
      <div className="mb-1.5 flex h-6 items-center gap-2">
        {m.member
          ? <MemberAvatar member={m.member} />
          : <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-50 text-brand"><Sparkles className="h-3 w-3" /></span>}
        <span className="flex-none whitespace-nowrap text-[13px] font-medium text-content">{m.member?.name ?? '智能助笔'}</span>
        <span className="as-meta min-w-0 truncate" title={note}>{note}</span>
      </div>
      {m.steps.length > 0 && (
        <p className="as-meta mb-2">处理记录 {m.steps.length} 步：{m.steps.map((s) => s.label).join(' → ')}</p>
      )}
      {cards.length > 0 && (
        <ul className="as-list mb-2.5">
          {cards.map((c) => (
            <li key={c.id} className="flex items-center gap-3 px-4 py-2.5">
              <span className="min-w-0 flex-1 truncate text-[13px] text-content">{c.label}</span>
              <StatusDot tone={c.status.tone} label={c.status.label} />
            </li>
          ))}
        </ul>
      )}
      <div className="as-prose"><RichText text={m.content} /></div>
    </div>
  );
}

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
        <div className="flex flex-none items-center gap-2 border-b border-surface-border-light px-2 py-1.5">
          <button onClick={() => setReading(null)} className="as-btn-ghost px-2"><ChevronLeft className="h-4 w-4" />任务</button>
          <p className="min-w-0 flex-1 truncate text-[13px] font-medium text-content">{reading.session?.title}</p>
          <span className="as-meta pr-2">只读回看</span>
        </div>
        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-4 py-5">
          {reading.messages.map((m) => <ReadMessage key={m.id} view={reading} m={m} />)}
          {!reading.messages.length && <p className="pt-10 text-center text-[13px] text-content-tertiary">这段对话没有消息</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto px-4 pb-5">
      <div className="flex items-center justify-between pt-4">
        <p className="text-[13px] text-content-secondary">本项目的后台任务与助笔记录</p>
        <button onClick={() => void load()} disabled={loading} className="as-icon-btn" title="刷新">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
        </button>
      </div>

      <section>
        <p className="as-section-title">正在运行<span className="ml-auto text-[12px] font-normal tabular-nums text-content-tertiary">{running.length}</span></p>
        {running.length ? (
          <ul className="as-list">
            {running.map((job) => (
              <li key={job.id} className="flex items-center gap-3 px-4 py-3">
                <Loader2 className="h-4 w-4 flex-none animate-spin text-brand" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-content">{job.title || kindLabel(job.kind)}</span>
                  <span className="block truncate text-[12px] text-content-tertiary">{kindLabel(job.kind)}{job.progress?.message ? ` · ${job.progress.message}` : ''}</span>
                </span>
                {job.kind === 'assistant_run' ? (
                  <button onClick={onOpenConversation} className="as-icon-btn" title="回到对话"><Sparkles className="h-4 w-4" /></button>
                ) : (
                  <button onClick={() => useAIJobsStore.getState().openModal(job.id)} className="as-icon-btn" title="查看过程"><Eye className="h-4 w-4" /></button>
                )}
                <button onClick={() => void useAIJobsStore.getState().cancel(job.id)} className="as-icon-btn hover:bg-cinnabar-wash hover:text-cinnabar" title="停止">
                  <Square className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        ) : <Empty text="没有正在运行的任务" />}
      </section>

      <section>
        <p className="as-section-title">助笔处理记录<span className="ml-auto text-[12px] font-normal tabular-nums text-content-tertiary">{runs.length}</span></p>
        {runs.length ? (
          <ul className="as-list">
            {runs.map((run) => {
              const status = RUN_STATUS[run.status] ?? RUN_STATUS.completed;
              const open = expanded === run.id;
              return (
                <li key={run.id}>
                  <button onClick={() => setExpanded((cur) => (cur === run.id ? null : run.id))} className="as-row">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] text-content" title={run.goal}>{run.goal}</span>
                      <span className="block truncate text-[12px] text-content-tertiary">{run.message || '—'} · {run.steps.length} 步 · {formatServerTime(run.updated_at)}</span>
                    </span>
                    <StatusDot tone={status.tone} label={status.label} />
                    <ChevronRight className={cn('h-4 w-4 flex-none text-content-tertiary transition-transform', open && 'rotate-90')} />
                  </button>
                  {open && (
                    <div className="border-t border-surface-border-light bg-surface-paper px-4 py-3">
                      {run.steps.length ? (
                        <ol className="space-y-1 text-[12px] leading-[1.6] text-content-secondary">
                          {run.steps.map((s, i) => (
                            <li key={i}><span className="tabular-nums text-content-tertiary">{i + 1}.</span> {s.label}<span className="text-content-tertiary"> · {s.summary}</span></li>
                          ))}
                        </ol>
                      ) : <p className="as-meta">这轮没有调用工具，直接回复的。</p>}
                      {run.status === 'waiting_input' && (
                        <button onClick={onOpenConversation} className="as-btn-primary mt-2.5">去回答</button>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        ) : <Empty text="还没有助笔处理记录" />}
      </section>

      <section>
        <p className="as-section-title">对话记录<span className="ml-auto text-[12px] font-normal tabular-nums text-content-tertiary">{sessions.length}</span></p>
        {sessions.length ? (
          <ul className="as-list">
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => (s.archived ? void assistantApi.sessionById(projectId, s.id).then(setReading) : onOpenConversation())}
                  className="as-row"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] text-content">{s.title}</span>
                    <span className="block text-[12px] text-content-tertiary">{s.message_count ?? 0} 条消息 · {formatServerTime(s.updated_at)}</span>
                  </span>
                  <StatusDot tone={s.archived ? 'gray' : 'green'} label={s.archived ? '已归档' : '当前'} />
                  <ChevronRight className="h-4 w-4 flex-none text-content-tertiary" />
                </button>
              </li>
            ))}
          </ul>
        ) : <Empty text="还没有对话" />}
      </section>
    </div>
  );
}
