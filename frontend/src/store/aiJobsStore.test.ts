import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AIJobSnapshot } from '@/types/ai_job';
import type { SSEClientOptions, SSEMessage } from '@/utils/sseClient';
import { createJobState } from '@/utils/aiJobReducer';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), info: vi.fn(), success: vi.fn() } }));
vi.mock('@/services/aiJobsApi', () => ({
  aiJobsApi: { list: vi.fn(), get: vi.fn(), events: vi.fn(), cancel: vi.fn(), dismiss: vi.fn() },
}));

import { aiJobsApi } from '@/services/aiJobsApi';
import { isConnectionLost, runAIJob, useAIJobsStore, waitForAIJob } from './aiJobsStore';

type Mocked = Record<'list' | 'get' | 'events' | 'cancel' | 'dismiss', ReturnType<typeof vi.fn>>;
const api = aiJobsApi as unknown as Mocked;

/** 造一个"后端"：按脚本把消息推给 onMessage，然后按 outcome 结束 */
function scripted(messages: SSEMessage[], outcome: 'resolve' | Error = 'resolve') {
  return async (options: SSEClientOptions<unknown>) => {
    for (const m of messages) options.onMessage?.(m);
    if (outcome instanceof Error) throw outcome;
    return true;
  };
}

function snapshot(over: Partial<AIJobSnapshot>): AIJobSnapshot {
  return {
    id: 'x', kind: 'demo', title: '演示', project_id: 'p1', scope: null, meta: {}, status: 'running',
    started_at: 1000, finished_at: null, elapsed: 0, seq: 0, error: null, result: null, last_progress: null, live: {},
    ...over,
  };
}

const ev = (m: Record<string, unknown>) => m as unknown as SSEMessage;
const microtasks = () => new Promise<void>((r) => queueMicrotask(() => queueMicrotask(r)));

beforeEach(() => {
  useAIJobsStore.setState({ jobs: {}, openJobId: null });
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe('start', () => {
  it('start 事件把临时 id 换成后端 job_id，事件归约到状态，结束触发 onSettled 一次', async () => {
    const settled = vi.fn();
    const seen: string[] = [];
    const jobId = await useAIJobsStore.getState().start({
      kind: 'demo', title: '演示', projectId: 'p1',
      connect: scripted([
        ev({ type: 'start', job_id: 'j1' }),
        ev({ type: 'progress', message: '一步', progress: 30, seq: 1 }),
        ev({ type: 'stage', name: 'a', label: 'A', status: 'done', seq: 2 }),
        ev({ type: 'result', data: { ok: true }, seq: 3 }),
        ev({ type: 'done', seq: 4 }),
      ]),
      onEvent: (m) => seen.push(m.type),
      onSettled: settled,
    });
    await microtasks();
    const state = useAIJobsStore.getState();
    expect(jobId).toBe('j1');
    expect(Object.keys(state.jobs)).toEqual(['j1']);
    expect(state.openJobId).toBe('j1');
    expect(state.jobs.j1.status).toBe('done');
    expect(state.jobs.j1.result).toEqual({ ok: true });
    expect(state.jobs.j1.stages).toHaveLength(1);
    expect(state.jobs.j1.connection).toBe('closed');
    expect(seen).toEqual(['start', 'progress', 'stage', 'result', 'done']);
    expect(settled).toHaveBeenCalledTimes(1);
  });

  it('openModal:false 不打开弹窗', async () => {
    await useAIJobsStore.getState().start({
      kind: 'demo', title: '演示', openModal: false,
      connect: scripted([ev({ type: 'start', job_id: 'j0' }), ev({ type: 'done', seq: 1 })]),
    });
    expect(useAIJobsStore.getState().openJobId).toBeNull();
  });

  it('发起请求就失败（如 409）→ reject 且任务标为失败', async () => {
    await expect(
      useAIJobsStore.getState().start({ kind: 'demo', title: '演示', connect: scripted([], new Error('该项目已有任务在运行')) }),
    ).rejects.toThrow('已有任务');
    const job = Object.values(useAIJobsStore.getState().jobs)[0];
    expect(job.status).toBe('error');
    expect(job.error).toBe('该项目已有任务在运行');
  });

  it('start 之后连接中断 → 用 lastSeq 重连通用事件端点，任务不算失败', async () => {
    vi.useFakeTimers();
    api.events.mockImplementation(async (_id: string, _since: number, options: SSEClientOptions<unknown>) => {
      options.onMessage?.(ev({ type: 'progress', message: '续上', progress: 80, seq: 6 }));
      options.onMessage?.(ev({ type: 'done', seq: 7 }));
      return true;
    });
    const jobId = await useAIJobsStore.getState().start({
      kind: 'demo', title: '演示',
      connect: scripted(
        [ev({ type: 'start', job_id: 'j2' }), ev({ type: 'progress', message: '半路', progress: 40, seq: 5 })],
        new Error('连接在生成完成前中断'),
      ),
    });
    expect(jobId).toBe('j2');
    await vi.advanceTimersByTimeAsync(0);
    expect(useAIJobsStore.getState().jobs.j2.status).toBe('running');
    expect(useAIJobsStore.getState().jobs.j2.connection).toBe('connecting');
    await vi.advanceTimersByTimeAsync(1500);
    expect(api.events).toHaveBeenCalledWith('j2', 5, expect.anything());
    expect(useAIJobsStore.getState().jobs.j2.status).toBe('done');
    expect(useAIJobsStore.getState().jobs.j2.progress?.message).toBe('续上');
  });
});

describe('syncFromServer', () => {
  it('只接管尚未跟踪的任务：running 的从 0 回放，终态的只进列表', async () => {
    api.list.mockResolvedValue({
      jobs: [
        snapshot({ id: 'r1', last_progress: { type: 'progress', message: '跑着', progress: 20, seq: 3 } }),
        snapshot({ id: 'd1', status: 'done', finished_at: 2000 }),
      ],
    });
    api.events.mockResolvedValue(true);
    useAIJobsStore.setState({ jobs: { d1: createJobState({ id: 'd1', kind: 'demo', title: '已有' }) }, openJobId: null });
    await useAIJobsStore.getState().syncFromServer('p1');
    expect(api.list).toHaveBeenCalledWith('p1');
    expect(api.events).toHaveBeenCalledTimes(1);
    expect(api.events).toHaveBeenCalledWith('r1', 0, expect.anything());
    expect(useAIJobsStore.getState().jobs.r1.progress).toEqual({ message: '跑着', pct: 20 });
    expect(useAIJobsStore.getState().jobs.d1.title).toBe('已有');
  });

  it('列表接口失败时静默', async () => {
    api.list.mockRejectedValue(new Error('network'));
    await expect(useAIJobsStore.getState().syncFromServer()).resolves.toBeUndefined();
  });
});

describe('onSettled / dismiss', () => {
  it('对已终态任务注册 onSettled 立即回调', () => {
    useAIJobsStore.setState({ jobs: { a: { ...createJobState({ id: 'a', kind: 'k', title: 't' }), status: 'done' } }, openJobId: null });
    const cb = vi.fn();
    useAIJobsStore.getState().onSettled('a', cb);
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it('dismiss 只允许移除终态任务，并关掉对应弹窗', () => {
    api.dismiss.mockResolvedValue({ dismissed: true });
    useAIJobsStore.setState({
      jobs: {
        a: { ...createJobState({ id: 'a', kind: 'k', title: 't' }), status: 'done' },
        b: createJobState({ id: 'b', kind: 'k', title: 't' }),
      },
      openJobId: 'a',
    });
    useAIJobsStore.getState().dismiss('a');
    useAIJobsStore.getState().dismiss('b');
    expect(Object.keys(useAIJobsStore.getState().jobs)).toEqual(['b']);
    expect(useAIJobsStore.getState().openJobId).toBeNull();
  });

  it('dismiss 同步告知后端移除，刷新后 syncFromServer 才不会把它捞回来；后端失败静默', async () => {
    api.dismiss.mockRejectedValue(new Error('network'));
    useAIJobsStore.setState({ jobs: { a: { ...createJobState({ id: 'a', kind: 'k', title: 't' }), status: 'done' } }, openJobId: null });
    useAIJobsStore.getState().dismiss('a');
    expect(api.dismiss).toHaveBeenCalledWith('a');
    await microtasks();
    expect(useAIJobsStore.getState().jobs).toEqual({});
  });

  it('尚未拿到后端 id 就失败的任务（pending-*）dismiss 不打后端', () => {
    useAIJobsStore.setState({
      jobs: { 'pending-9': { ...createJobState({ id: 'pending-9', kind: 'k', title: 't' }), status: 'error' } },
      openJobId: null,
    });
    useAIJobsStore.getState().dismiss('pending-9');
    expect(api.dismiss).not.toHaveBeenCalled();
    expect(useAIJobsStore.getState().jobs).toEqual({});
  });
});

describe('isConnectionLost', () => {
  it('识别连接层中断文案，但带 detail 的业务错误不算', () => {
    expect(isConnectionLost('连接在生成完成前中断')).toBe(true);
    expect(isConnectionLost('Failed to fetch')).toBe(true);
    expect(isConnectionLost('HTTP error! status: 502')).toBe(true);
    expect(isConnectionLost('该项目已有填充任务在运行')).toBe(false);
  });
});

describe('meta', () => {
  it('start 时可附带 meta；快照的 meta 也带进状态', async () => {
    await useAIJobsStore.getState().start({
      kind: 'demo', title: '演示', meta: { chapter_id: 'c1' },
      connect: scripted([ev({ type: 'start', job_id: 'jm' }), ev({ type: 'done', seq: 1 })]),
    });
    expect(useAIJobsStore.getState().jobs.jm.meta).toEqual({ chapter_id: 'c1' });
    api.list.mockResolvedValue({ jobs: [snapshot({ id: 'r9', status: 'done', finished_at: 2000, meta: { chapter_id: 'c9' } })] });
    await useAIJobsStore.getState().syncFromServer();
    expect(useAIJobsStore.getState().jobs.r9.meta).toEqual({ chapter_id: 'c9' });
  });
});

describe('runAIJob / waitForAIJob', () => {
  it('runAIJob 在任务 done 后 resolve 终态，onStarted 拿到真实 id', async () => {
    const onStarted = vi.fn();
    const job = await runAIJob({
      kind: 'demo', title: '演示', onStarted,
      connect: scripted([ev({ type: 'start', job_id: 'jr' }), ev({ type: 'result', data: { n: 1 }, seq: 1 }), ev({ type: 'done', seq: 2 })]),
    });
    expect(job.id).toBe('jr');
    expect(job.status).toBe('done');
    expect(job.result).toEqual({ n: 1 });
    expect(onStarted).toHaveBeenCalledWith('jr');
  });

  it('runAIJob 在任务 error / cancelled 时 reject（带 job）', async () => {
    await expect(runAIJob({
      kind: 'demo', title: '演示',
      connect: scripted([ev({ type: 'start', job_id: 'je' }), ev({ type: 'error', error: '模型超时', seq: 1 })]),
    })).rejects.toMatchObject({ message: '模型超时', job: { id: 'je', status: 'error' } });
    await expect(runAIJob({
      kind: 'demo', title: '演示',
      connect: scripted([ev({ type: 'start', job_id: 'jc' }), ev({ type: 'error', error: '已停止', code: 499, seq: 1 })]),
    })).rejects.toMatchObject({ job: { status: 'cancelled' } });
  });

  it('runAIJob 发起即失败（409）→ reject 原错误', async () => {
    await expect(runAIJob({ kind: 'demo', title: '演示', connect: scripted([], new Error('已有任务在运行')) })).rejects.toThrow('已有任务');
  });

  it('waitForAIJob：已终态立即返回；接管中的任务等到终态事件（失败 → reject）', async () => {
    useAIJobsStore.setState({ jobs: { w1: { ...createJobState({ id: 'w1', kind: 'k', title: 't' }), status: 'done' } }, openJobId: null });
    expect((await waitForAIJob('w1')).status).toBe('done');

    api.get.mockResolvedValue(snapshot({ id: 'w3' }));
    api.events.mockImplementation(async (_id: string, _since: number, options: SSEClientOptions<unknown>) => {
      options.onMessage?.(ev({ type: 'error', error: '炸了', seq: 1 }));
      return true;
    });
    await useAIJobsStore.getState().attach('w3');       // running 快照 → 从 0 回放 → error
    await expect(waitForAIJob('w3')).rejects.toMatchObject({ message: '炸了', job: { id: 'w3', status: 'error' } });
    await expect(waitForAIJob('nope')).rejects.toThrow('任务不存在');
  });
});