import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SSEClientOptions, SSEMessage } from '@/utils/sseClient';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), info: vi.fn(), success: vi.fn() } }));
vi.mock('@/services/aiJobsApi', () => ({
  aiJobsApi: { list: vi.fn(), get: vi.fn(), events: vi.fn(), cancel: vi.fn(), dismiss: vi.fn() },
}));

import { aiJobsApi } from '@/services/aiJobsApi';
import { useAIJobsStore } from './aiJobsStore';
import { isJobCancelled, runWizardJob, WIZARD_CONNECTION_LOST } from './wizardJob';

const api = aiJobsApi as unknown as Record<'events' | 'get', ReturnType<typeof vi.fn>>;
const ev = (m: Record<string, unknown>) => m as unknown as SSEMessage;

/** 造一个"后端"：按脚本把消息推给 onMessage，然后按 outcome 结束 */
function scripted<T = unknown>(messages: SSEMessage[], outcome: 'resolve' | Error = 'resolve') {
  return async (options: SSEClientOptions<T>) => {
    for (const m of messages) options.onMessage?.(m);
    if (outcome instanceof Error) throw outcome;
    return true;
  };
}

beforeEach(() => {
  useAIJobsStore.setState({ jobs: {}, openJobId: null });
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe('runWizardJob', () => {
  it('完成 → 返回 result；进度按后端 0-100 转发；拿到后端 job id；不弹通用任务弹窗', async () => {
    const onProgress = vi.fn();
    const onStarted = vi.fn();
    const result = await runWizardJob<{ project_id: string }>({
      kind: 'wizard_world_building', title: '向导：生成世界构建', onProgress, onStarted,
      connect: scripted([
        ev({ type: 'start', job_id: 'w1' }),
        ev({ type: 'progress', message: '开始生成世界观...', progress: 10, seq: 1 }),
        ev({ type: 'result', data: { project_id: 'p1' }, seq: 2 }),
        ev({ type: 'done', seq: 3 }),
      ]),
    });
    expect(result).toEqual({ project_id: 'p1' });
    expect(onProgress).toHaveBeenCalledWith('开始生成世界观...', 10);
    expect(onStarted).toHaveBeenCalledWith('w1');
    expect(useAIJobsStore.getState().openJobId).toBeNull();
  });

  it('任务失败 → 按后端文案 reject，不算停止', async () => {
    const error = await runWizardJob({
      kind: 'wizard_characters', title: '向导：生成角色', projectId: 'p1',
      connect: scripted([
        ev({ type: 'start', job_id: 'w2' }),
        ev({ type: 'error', error: '向导：生成角色失败: 批次1在3次重试后仍然失败', code: 500, seq: 1 }),
      ]),
    }).catch((e: unknown) => e);
    expect((error as Error).message).toContain('批次1在3次重试后仍然失败');
    expect(isJobCancelled(error)).toBe(false);
  });

  it('后端任务被停止（499）→ reject 且识别为停止', async () => {
    const error = await runWizardJob({
      kind: 'wizard_outline', title: '向导：生成故事大纲', projectId: 'p1',
      connect: scripted([
        ev({ type: 'start', job_id: 'w3' }),
        ev({ type: 'error', error: '已停止；本步已写入的数据保留，可重新生成', code: 499, seq: 1 }),
      ]),
    }).catch((e: unknown) => e);
    expect(isJobCancelled(error)).toBe(true);
  });

  it('发起即被拒（409）→ reject 后端 detail', async () => {
    await expect(runWizardJob({
      kind: 'wizard_volumes', title: '向导：生成卷纲', projectId: 'p1',
      connect: scripted([], new Error('「向导：生成卷纲」已有任务在运行，请等待完成或先停止')),
    })).rejects.toThrow('已有任务在运行');
  });

  it('中途断线 → 按 lastSeq 续上事件流，照样拿到结果', async () => {
    vi.useFakeTimers();
    api.events.mockImplementation(async (_id: string, _since: number, options: SSEClientOptions<unknown>) => {
      options.onMessage?.(ev({ type: 'result', data: { count: 5 }, seq: 3 }));
      options.onMessage?.(ev({ type: 'done', seq: 4 }));
      return true;
    });
    const pending = runWizardJob({
      kind: 'wizard_characters', title: '向导：生成角色', projectId: 'p1',
      connect: scripted(
        [ev({ type: 'start', job_id: 'w4' }), ev({ type: 'progress', message: '半路', progress: 40, seq: 2 })],
        new Error('连接在生成完成前中断'),
      ),
    });
    await vi.advanceTimersByTimeAsync(1500);
    await expect(pending).resolves.toEqual({ count: 5 });
    expect(api.events).toHaveBeenCalledWith('w4', 2, expect.anything());
  });

  it('重连次数用尽（connection=lost）→ reject「连接已断开」，不再无限等待', async () => {
    vi.useFakeTimers();
    api.events.mockRejectedValue(new Error('Failed to fetch'));
    const pending = runWizardJob({
      kind: 'wizard_outline', title: '向导：生成故事大纲', projectId: 'p1',
      connect: scripted([ev({ type: 'start', job_id: 'w5' })], new Error('连接在生成完成前中断')),
    }).catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(1500 * 45);
    const error = await pending;
    expect((error as Error).message).toBe(WIZARD_CONNECTION_LOST);
    expect(isJobCancelled(error)).toBe(false);
  });
});
