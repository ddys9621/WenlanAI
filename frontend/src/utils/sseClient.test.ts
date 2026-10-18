import { afterEach, describe, expect, it, vi } from 'vitest';
import { ssePost } from './sseClient';

const encoder = new TextEncoder();
const frame = (data: Record<string, unknown>) => `data: ${JSON.stringify(data)}\n\n`;

/** 伪造后端：按顺序吐出 SSE 帧后关闭流（ai_jobs 失败时就是 error 之后直接收尾，不再发 done） */
function sseResponse(frames: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(encoder.encode(f));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

type Outcome<T> = { state: 'resolved'; value: T } | { state: 'rejected'; error: Error } | { state: 'pending' };

/** promise 在 ms 内没落定就判为挂起：挂起正是要抓的症状，不能让测试本身卡死 */
function settleWithin<T>(promise: Promise<T>, ms = 300): Promise<Outcome<T>> {
  return Promise.race([
    promise.then(
      (value): Outcome<T> => ({ state: 'resolved', value }),
      (error: Error): Outcome<T> => ({ state: 'rejected', error }),
    ),
    new Promise<Outcome<T>>((resolve) => setTimeout(() => resolve({ state: 'pending' }), ms)),
  ]);
}

/** 向导 / 灵感模式的写法：标完失败再 throw，指望 await 处的 catch 接住 */
const throwingOnError = (error: string) => {
  throw new Error(error);
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ssePost：onError 回调抛异常时 Promise 仍要按失败落定', () => {
  it('任务失败（error 事件后流关闭）→ reject 原错误文案', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([
      frame({ type: 'start', job_id: 'j1' }),
      frame({ type: 'progress', message: '生成第1/2批角色', progress: 15, seq: 1 }),
      frame({ type: 'error', error: '向导：生成角色失败: 批次1在3次重试后仍然失败', code: 500, seq: 2 }),
    ])));

    const outcome = await settleWithin(ssePost('/api/wizard-stream/characters', {}, { onError: throwingOnError }));

    expect(outcome.state).toBe('rejected');
    expect(outcome.state === 'rejected' && outcome.error.message).toContain('批次1在3次重试后仍然失败');
  });

  it('发起即被拒（409 同项目已有任务）→ reject 后端 detail', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: '「向导：生成故事大纲」已有任务在运行，请等待完成或先停止' }),
      { status: 409, headers: { 'Content-Type': 'application/json' } },
    )));

    const outcome = await settleWithin(ssePost('/api/wizard-stream/outline', {}, { onError: throwingOnError }));

    expect(outcome.state).toBe('rejected');
    expect(outcome.state === 'rejected' && outcome.error.message).toContain('已有任务在运行');
  });

  it('流在 done / error 之前被掐断 → reject「连接在生成完成前中断」，onError 只通知一次', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([
      frame({ type: 'start', job_id: 'j2' }),
      frame({ type: 'progress', message: '生成中... (300字符)', progress: 40, seq: 1 }),
    ])));
    const onError = vi.fn(throwingOnError);

    const outcome = await settleWithin(ssePost('/api/wizard-stream/world-building', {}, { onError }));

    expect(outcome.state).toBe('rejected');
    expect(outcome.state === 'rejected' && outcome.error.message).toBe('连接在生成完成前中断');
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it('不抛异常的 onError 行为不变：error 事件 → 通知一次并 reject', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([
      frame({ type: 'start', job_id: 'j3' }),
      frame({ type: 'error', error: '模型超时', code: 500, seq: 1 }),
    ])));
    const onError = vi.fn();

    const outcome = await settleWithin(ssePost('/api/x', {}, { onError }));

    expect(outcome.state).toBe('rejected');
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith('模型超时', 500);
  });

  it('正常收尾：result + done → resolve 结果', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([
      frame({ type: 'start', job_id: 'j4' }),
      frame({ type: 'result', data: { project_id: 'p1' }, seq: 1 }),
      frame({ type: 'done', seq: 2 }),
    ])));

    const outcome = await settleWithin(ssePost('/api/x', {}, { onError: throwingOnError }));

    expect(outcome).toEqual({ state: 'resolved', value: { project_id: 'p1' } });
  });
});
