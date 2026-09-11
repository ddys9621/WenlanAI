/**
 * 通用 AI 后台任务 API（对应 backend/app/api/ai_jobs.py）
 * 各业务的"发起"接口仍在各自 api（如 characterApi.generateCharacterStream），发起后重连 / 停止统一走这里。
 */
import api from '@/services/api';
import type { AIJobSnapshot } from '@/types/ai_job';
import { ssePost, type SSEClientOptions } from '@/utils/sseClient';

export const aiJobsApi = {
  /** 当前用户的任务（running 优先 + 保留期内的终态）GET /api/ai-jobs?project_id= */
  list: (projectId?: string) =>
    api.get<unknown, { jobs: AIJobSnapshot[] }>('/ai-jobs', { params: projectId ? { project_id: projectId } : undefined }),

  /** 快照 GET /api/ai-jobs/{id} */
  get: (jobId: string) => api.get<unknown, AIJobSnapshot>(`/ai-jobs/${jobId}`),

  /** SSE：从 since 之后回放并续尾到终态 POST /api/ai-jobs/{id}/events */
  events: (jobId: string, since: number, options?: SSEClientOptions) =>
    ssePost(`/api/ai-jobs/${jobId}/events`, { since }, options),

  /** 停止 DELETE /api/ai-jobs/{id} */
  cancel: (jobId: string) => api.delete<unknown, { cancelled: boolean }>(`/ai-jobs/${jobId}`),

  /** 移除终态任务（托盘 ×）POST /api/ai-jobs/{id}/dismiss：否则刷新后 list 会把它同步回来 */
  dismiss: (jobId: string) => api.post<unknown, { dismissed: boolean }>(`/ai-jobs/${jobId}/dismiss`),
};
