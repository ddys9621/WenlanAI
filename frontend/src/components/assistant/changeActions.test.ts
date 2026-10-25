import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { describe, expect, it, vi } from 'vitest';

import type { AssistantPlan } from '@/types/assistant';

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }));
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn(), warning: vi.fn() } }));

const plan: AssistantPlan = {
  kind: 'volumes', title: '分卷草案：2 卷', volumes: [
    { id: 'gone-1', volume_number: 1, title: '藏书楼', chapter_start: 1, chapter_end: 60, summary: '', unit_count: 0 },
    { id: 'gone-2', volume_number: 2, title: '问道台', chapter_start: 61, chapter_end: 120, summary: '', unit_count: 0 },
  ],
};

describe('confirmPlan', () => {
  it('卷纲已经不在了：确认失败只交给调用方提示一次，不让全局拦截器每卷弹一条「卷纲不存在」', async () => {
    axios.defaults.adapter = (config: InternalAxiosRequestConfig) => Promise.reject(new AxiosError(
      'Request failed with status code 404', 'ERR_BAD_REQUEST', config, null,
      { status: 404, statusText: 'Not Found', data: { detail: '卷纲不存在' }, headers: {}, config },
    ));
    const { confirmPlan, errorDetail } = await import('./changeActions'); // 接口实例要在换好 adapter 之后再建
    const err = await confirmPlan(plan, false).catch((e: unknown) => e);
    expect(errorDetail(err)).toBe('卷纲不存在');
    expect(toastError).not.toHaveBeenCalled();
  });
});
