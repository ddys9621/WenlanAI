/**
 * 桥段 - 前端 API 客户端（工程化桥段流水线：骨架 → 填充 → 展开）
 *
 * 对应后端 backend/app/api/plot_bridges.py
 */
import api from '@/services/api';
import { ssePost } from '@/utils/sseClient';
import type { SSEClientOptions } from '@/utils/sseClient';
import type {
  BridgeSlotPreview,
  ExpandAllBridgesRequest,
  ExpandAllBridgesResponse,
  ExpandBridgeRequest,
  ExpandBridgeResponse,
  FillBridgesRequest,
  FillBridgesResult,
  PlotBridge,
  UpdateBridgeRequest,
} from '@/types/plot_bridge';

export const plotBridgesApi = {
  /**
   * 纯计算预览：主线节点 → 桥段槽位表（不写库）
   * GET /api/projects/{projectId}/bridges/plan-preview
   */
  planPreview: (projectId: string) =>
    api.get<unknown, BridgeSlotPreview>(`/projects/${projectId}/bridges/plan-preview`),

  /**
   * 建骨架：创建 N 个 draft 桥段（无 LLM）；已存在 → 409
   * POST /api/projects/{projectId}/bridges/plan
   */
  plan: (projectId: string) =>
    api.post<unknown, PlotBridge[]>(`/projects/${projectId}/bridges/plan`, {}),

  /**
   * 重置骨架：删除全部桥段；已展开 → 409
   * DELETE /api/projects/{projectId}/bridges
   */
  reset: (projectId: string) =>
    api.delete<unknown, { deleted: number }>(`/projects/${projectId}/bridges`),

  /**
   * SSE：启动后台填充任务并从头订阅事件（任务不随连接断开而终止；重连 / 停止走 aiJobsApi；已有任务 → 409）
   * POST /api/projects/{projectId}/bridges/fill-stream
   */
  fillStream: (
    projectId: string,
    payload: FillBridgesRequest,
    options?: SSEClientOptions<FillBridgesResult>,
  ) => ssePost<FillBridgesResult>(`/api/projects/${projectId}/bridges/fill-stream`, payload, options),

  /**
   * 列出项目下所有桥段
   * GET /api/projects/{projectId}/bridges
   */
  list: (projectId: string) =>
    api.get<unknown, PlotBridge[]>(`/projects/${projectId}/bridges`),

  /**
   * 获取单个桥段详情
   * GET /api/bridges/{bridgeId}
   */
  update: (bridgeId: string, payload: UpdateBridgeRequest) =>
    api.patch<unknown, PlotBridge>(`/bridges/${bridgeId}`, payload),

  /**
   * 删除桥段
   * DELETE /api/bridges/{bridgeId}
   */
  delete: (bridgeId: string) =>
    api.delete<unknown, { success: boolean }>(`/bridges/${bridgeId}`),

  /**
   * 展开为第 4(n-1)+1…4n 章（要求 ready 且前一桥段已 completed）
   * POST /api/bridges/{bridgeId}/expand
   */
  expand: (bridgeId: string, payload: ExpandBridgeRequest = {}) =>
    api.post<unknown, ExpandBridgeResponse>(`/bridges/${bridgeId}/expand`, payload),

  /**
   * 按 bridge_number 顺序批量展开全部 ready 桥段（首个失败即停止）
   * POST /api/projects/{projectId}/bridges/expand-all
   */
  expandAll: (projectId: string, payload: ExpandAllBridgesRequest = {}) =>
    api.post<unknown, ExpandAllBridgesResponse>(`/projects/${projectId}/bridges/expand-all`, payload),
};
