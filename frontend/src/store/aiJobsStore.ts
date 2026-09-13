/**
 * 全局 AI 任务 store：任务注册表 + SSE 订阅所有权 + 断线重连
 *
 * 设计要点：
 * - SSE 订阅由 store 拥有而不是页面：页面卸载 / 切路由 / 关弹窗都不会断流，托盘与横幅在任何页面都能看到进度
 * - 通用事件（progress / stage / tool_call / reference / llm / content / result / done / error）归约进 AIJobState；
 *   场景级事件（partial / bridges / meta …）通过 subscribe 原样交给页面
 * - 连接层中断（刷新 / 代理掐断）≠ 任务失败：用 lastSeq 重连 /api/ai-jobs/{id}/events
 * - 托盘 × （dismiss）同时让后端移除该终态任务：否则刷新后 syncFromServer 会把保留期内的它同步回来
 * - 监听者 / 定时器不放进 zustand state（避免无意义的重渲染）
 * - 横幅 / 托盘 / 页面列表通过摘要选择器订阅（AIJobSummary + 判等），正文 content 事件不会让它们重渲染
 */
import { useMemo, useRef, useSyncExternalStore } from 'react';
import { toast } from 'sonner';
import { create } from 'zustand';
import { aiJobsApi } from '@/services/aiJobsApi';
import { AI_JOB_SUMMARY_KEYS, type AIJobSnapshot, type AIJobState, type AIJobSummary } from '@/types/ai_job';
import { applyEvent, createJobState, fromSnapshot, isTerminal } from '@/utils/aiJobReducer';
import type { SSEClientOptions, SSEMessage } from '@/utils/sseClient';

/** 连接层中断（刷新 / 代理掐断 / 网关 5xx）不等于任务失败：这些文案触发重连而不是报错 */
const CONNECTION_LOST_MESSAGES = ['连接在生成完成前中断', 'Failed to fetch', 'NetworkError', 'network error', 'Load failed'];
export const isConnectionLost = (message: string) =>
  CONNECTION_LOST_MESSAGES.some((m) => message.includes(m)) || message.startsWith('HTTP error');

const RECONNECT_DELAY_MS = 1500;
const MAX_RECONNECT_ATTEMPTS = 40; // ≈ 1 分钟

type AIJobListener = (message: SSEMessage, job: AIJobState) => void;
type AIJobSettled = (job: AIJobState) => void;

interface StartAIJobParams<TResult = unknown> {
  kind: string;
  title: string;
  projectId?: string | null;
  /** 发起请求：把 options 透传给对应的 ssePost 封装，如 `(o) => characterApi.generateCharacterStream(payload, o)` */
  connect: (options: SSEClientOptions<TResult>) => Promise<unknown>;
  /** 场景级事件（partial / bridges / meta …）；通用事件也会经过这里 */
  onEvent?: AIJobListener;
  /** 终态回调（done / error / cancelled），只触发一次 */
  onSettled?: AIJobSettled;
  /** 默认 true：发起后立刻打开通用弹窗 */
  openModal?: boolean;
  /** 业务附加信息（如 chapter_id）；后端 start 事件之前先用它，快照到达后以后端 meta 为准 */
  meta?: Record<string, unknown>;
}

interface AIJobsState {
  jobs: Record<string, AIJobState>;
  openJobId: string | null;
  start: <T>(params: StartAIJobParams<T>) => Promise<string>;
  attach: (jobId: string) => Promise<void>;
  syncFromServer: (projectId?: string | null) => Promise<void>;
  cancel: (jobId: string) => Promise<void>;
  dismiss: (jobId: string) => void;
  openModal: (jobId: string) => void;
  closeModal: () => void;
  subscribe: (jobId: string, listener: AIJobListener) => () => void;
  onSettled: (jobId: string, cb: AIJobSettled) => () => void;
}

const listeners = new Map<string, Set<AIJobListener>>();
const settledCallbacks = new Map<string, Set<AIJobSettled>>();
const settledFired = new Set<string>();
const reconnectTimers = new Map<string, ReturnType<typeof setTimeout>>();
let pendingCounter = 0;

function moveKey<V>(map: Map<string, V>, from: string, to: string) {
  const v = map.get(from);
  if (v === undefined) return;
  map.delete(from);
  map.set(to, v);
}

export const useAIJobsStore = create<AIJobsState>((set, get) => {
  const update = (jobId: string, fn: (job: AIJobState) => AIJobState) => {
    const job = get().jobs[jobId];
    if (!job) return;
    set((s) => ({ jobs: { ...s.jobs, [jobId]: fn(job) } }));
  };

  /** start 事件到达：临时 id → 后端 id（状态、弹窗、监听者一并迁移） */
  const rename = (from: string, to: string) => {
    set((s) => {
      const job = s.jobs[from];
      if (!job) return s;
      const jobs = { ...s.jobs };
      delete jobs[from];
      jobs[to] = { ...job, id: to };
      return { jobs, openJobId: s.openJobId === from ? to : s.openJobId };
    });
    moveKey(listeners, from, to);
    moveKey(settledCallbacks, from, to);
  };

  const fireSettled = (jobId: string) => {
    const job = get().jobs[jobId];
    if (!job || !isTerminal(job) || settledFired.has(jobId)) return;
    settledFired.add(jobId);
    for (const cb of settledCallbacks.get(jobId) ?? []) cb(job);
    settledCallbacks.delete(jobId);
    listeners.delete(jobId);
  };

  const handleMessage = (idRef: { current: string }, m: SSEMessage) => {
    if (m.type === 'start' && typeof m.job_id === 'string' && m.job_id !== idRef.current) {
      rename(idRef.current, m.job_id);
      idRef.current = m.job_id;
    }
    const id = idRef.current;
    update(id, (job) => applyEvent({ ...job, connection: 'live' }, m));
    const job = get().jobs[id];
    if (!job) return;
    for (const l of listeners.get(id) ?? []) l(m, job);
    if (isTerminal(job)) fireSettled(id);
  };

  const scheduleReconnect = (jobId: string, attempt: number) => {
    const job = get().jobs[jobId];
    if (!job || isTerminal(job)) return;
    if (attempt > MAX_RECONNECT_ATTEMPTS) {
      update(jobId, (j) => ({ ...j, connection: 'lost' }));
      return;
    }
    update(jobId, (j) => ({ ...j, connection: 'connecting' }));
    const timer = setTimeout(() => {
      reconnectTimers.delete(jobId);
      const current = get().jobs[jobId];
      if (current && !isTerminal(current)) void runEvents(jobId, current.lastSeq, attempt);
    }, RECONNECT_DELAY_MS);
    reconnectTimers.set(jobId, timer);
  };

  const runEvents = async (jobId: string, since: number, attempt = 0): Promise<void> => {
    const idRef = { current: jobId };
    try {
      await aiJobsApi.events(jobId, since, { onMessage: (m) => handleMessage(idRef, m) });
    } catch (err) {
      const job = get().jobs[jobId];
      if (!job || isTerminal(job)) return;
      const message = err instanceof Error ? err.message : String(err);
      if (isConnectionLost(message)) {
        scheduleReconnect(jobId, attempt + 1);
        return;
      }
      // 服务端明确报错（如 404 任务已过期）：按快照兜底，拿不到就标失败
      try {
        const snap = await aiJobsApi.get(jobId);
        update(jobId, () => ({ ...fromSnapshot(snap), connection: 'closed' }));
      } catch {
        update(jobId, (j) => ({ ...j, status: 'error', error: '任务不存在或已过期', finishedAt: Date.now(), connection: 'closed' }));
      }
      fireSettled(jobId);
      return;
    }
    update(jobId, (j) => ({ ...j, connection: 'closed' }));
    fireSettled(jobId);
  };

  const trackSnapshot = (snap: AIJobSnapshot) => {
    set((s) => ({ jobs: { ...s.jobs, [snap.id]: fromSnapshot(snap) } }));
    if (snap.status === 'running') void runEvents(snap.id, 0);
    else update(snap.id, (j) => ({ ...j, connection: 'closed' }));
  };

  return {
    jobs: {},
    openJobId: null,

    start: (params) => {
      const tempId = `pending-${++pendingCounter}`;
      set((s) => ({
        jobs: {
          ...s.jobs,
          [tempId]: createJobState({
            id: tempId, kind: params.kind, title: params.title, projectId: params.projectId ?? null, meta: params.meta,
          }),
        },
        openJobId: params.openModal === false ? s.openJobId : tempId,
      }));
      if (params.onEvent) listeners.set(tempId, new Set([params.onEvent]));
      if (params.onSettled) settledCallbacks.set(tempId, new Set([params.onSettled]));
      const idRef = { current: tempId };

      return new Promise<string>((resolve, reject) => {
        let resolved = false;
        const settle = (fn: () => void) => {
          if (resolved) return;
          resolved = true;
          fn();
        };
        params
          .connect({
            onMessage: (m) => {
              handleMessage(idRef, m);
              if (idRef.current !== tempId) settle(() => resolve(idRef.current));
            },
          })
          .then(() => {
            update(idRef.current, (j) => ({ ...j, connection: 'closed' }));
            fireSettled(idRef.current);
            settle(() => resolve(idRef.current));
          })
          .catch((err: unknown) => {
            const id = idRef.current;
            const message = err instanceof Error ? err.message : String(err);
            const job = get().jobs[id];
            if (id !== tempId && job && !isTerminal(job) && isConnectionLost(message)) {
              scheduleReconnect(id, 1);
              settle(() => resolve(id));
              return;
            }
            if (job && !isTerminal(job)) {
              update(id, (j) => ({ ...j, status: 'error', error: message, finishedAt: Date.now(), connection: 'closed' }));
            }
            fireSettled(id);
            settle(() => reject(err instanceof Error ? err : new Error(message)));
          });
      });
    },

    attach: async (jobId) => {
      if (get().jobs[jobId]) return;
      trackSnapshot(await aiJobsApi.get(jobId));
    },

    syncFromServer: async (projectId) => {
      let jobs: AIJobSnapshot[];
      try {
        ({ jobs } = await aiJobsApi.list(projectId ?? undefined));
      } catch {
        return;
      }
      for (const snap of jobs) {
        if (!get().jobs[snap.id]) trackSnapshot(snap);
      }
    },

    cancel: async (jobId) => {
      try {
        await aiJobsApi.cancel(jobId);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '停止失败');
      }
    },

    dismiss: (jobId) => {
      const job = get().jobs[jobId];
      if (!job || !isTerminal(job)) return;
      set((s) => {
        const jobs = { ...s.jobs };
        delete jobs[jobId];
        return { jobs, openJobId: s.openJobId === jobId ? null : s.openJobId };
      });
      settledFired.delete(jobId);
      // 后端保留期内 GET 列表仍会返回它，刷新时 syncFromServer 会再捞回托盘 → 一并让后端移除。
      // pending-* 是还没拿到后端 id 就失败的任务，后端没这条记录；已过保留期被 gc 的 404 也无需提示。
      if (!jobId.startsWith('pending-')) void aiJobsApi.dismiss(jobId).catch(() => {});
    },

    openModal: (jobId) => set({ openJobId: jobId }),
    closeModal: () => set({ openJobId: null }),

    subscribe: (jobId, listener) => {
      let bucket = listeners.get(jobId);
      if (!bucket) listeners.set(jobId, (bucket = new Set()));
      bucket.add(listener);
      return () => {
        bucket!.delete(listener);
      };
    },

    onSettled: (jobId, cb) => {
      const job = get().jobs[jobId];
      if (job && isTerminal(job)) {
        cb(job);
        return () => {};
      }
      let bucket = settledCallbacks.get(jobId);
      if (!bucket) settledCallbacks.set(jobId, (bucket = new Set()));
      bucket.add(cb);
      return () => {
        bucket!.delete(cb);
      };
    },
  };
});

/** 任务以 error / cancelled 结束时 runAIJob / waitForAIJob 抛出的错误（带终态 job 便于分支处理） */
export class AIJobError extends Error {
  readonly job: AIJobState;

  constructor(job: AIJobState) {
    super(job.error ?? (job.status === 'cancelled' ? '任务已停止' : '任务失败'));
    this.name = 'AIJobError';
    this.job = job;
  }
}

/** 等待某个已跟踪任务的终态：done → resolve；error / cancelled → reject AIJobError；未跟踪 → reject */
export function waitForAIJob(jobId: string): Promise<AIJobState> {
  return new Promise((resolve, reject) => {
    if (!useAIJobsStore.getState().jobs[jobId]) {
      reject(new Error('任务不存在或尚未跟踪'));
      return;
    }
    useAIJobsStore.getState().onSettled(jobId, (job) => (job.status === 'done' ? resolve(job) : reject(new AIJobError(job))));
  });
}

/** 发起并等到终态（批量编排 / 对话框流程用）；onStarted 在拿到后端 job id 时回调 */
export async function runAIJob<T = unknown>(
  params: StartAIJobParams<T> & { onStarted?: (jobId: string) => void },
): Promise<AIJobState> {
  const { onStarted, ...startParams } = params;
  const jobId = await useAIJobsStore.getState().start(startParams);
  onStarted?.(jobId);
  return waitForAIJob(jobId);
}

/** 页面级：按 id 取任务状态（不存在 / null → null） */
export const useAIJob = (jobId: string | null) => useAIJobsStore((s) => (jobId ? s.jobs[jobId] ?? null : null));

const byRunningThenNewest = (a: AIJobSummary, b: AIJobSummary) =>
  Number(isTerminal(a)) - Number(isTerminal(b)) || b.startedAt - a.startedAt;

const toSummary = (job: AIJobState): AIJobSummary => {
  const summary = {} as Record<string, unknown>;
  for (const key of AI_JOB_SUMMARY_KEYS) summary[key] = job[key];
  return summary as unknown as AIJobSummary;
};

/** 摘要字段逐个引用判等：reducer 只在对应事件到来时才新建 progress / llm / meta 对象，所以 content 事件不会让判等失败 */
const summaryEqual = (a: AIJobSummary, b: AIJobSummary) => AI_JOB_SUMMARY_KEYS.every((key) => a[key] === b[key]);
export const summariesEqual = (a: AIJobSummary[], b: AIJobSummary[]) =>
  a.length === b.length && a.every((job, i) => summaryEqual(job, b[i]));

type JobsState = Pick<AIJobsState, 'jobs'>;

export function selectRunningSummaries(state: JobsState, projectId?: string | null, kinds?: readonly string[]): AIJobSummary[] {
  return Object.values(state.jobs)
    .filter((j) => j.status === 'running' && (!projectId || j.projectId === projectId) && (!kinds?.length || kinds.includes(j.kind)))
    .sort(byRunningThenNewest)
    .map(toSummary);
}

export function selectAllSummaries(state: JobsState): AIJobSummary[] {
  return Object.values(state.jobs).sort(byRunningThenNewest).map(toSummary);
}

/** 带自定义判等的订阅：判等相同就复用上一次的引用，React 才不会重渲染（zustand v5 默认只做 Object.is） */
function useSummaries(selector: (state: JobsState) => AIJobSummary[]): AIJobSummary[] {
  const cache = useRef<AIJobSummary[] | null>(null);
  const getSnapshot = () => {
    const next = selector(useAIJobsStore.getState());
    if (cache.current && summariesEqual(cache.current, next)) return cache.current;
    cache.current = next;
    return next;
  };
  return useSyncExternalStore(useAIJobsStore.subscribe, getSnapshot, getSnapshot);
}

/** 某项目正在运行的任务摘要（横幅 / 页面列表用）；kinds 可选过滤。只在摘要变化时触发重渲染 */
export function useRunningAIJobs(projectId?: string | null, kinds?: readonly string[]): AIJobSummary[] {
  const kindKey = kinds?.join('|') ?? '';
  const selector = useMemo(() => {
    const kindList = kindKey ? kindKey.split('|') : undefined;
    return (state: JobsState) => selectRunningSummaries(state, projectId, kindList);
  }, [projectId, kindKey]);
  return useSummaries(selector);
}

/** 全部任务摘要（托盘用）：running 优先，其次开始时间倒序 */
export function useAllAIJobs(): AIJobSummary[] {
  return useSummaries(selectAllSummaries);
}
