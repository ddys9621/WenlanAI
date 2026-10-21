/**
 * 改动卡片的操作：卡片按钮和待确认栏（单条 / 全部）共用同一套——调接口、通知页面刷新；提示由调用方决定。
 * notify = false：批量处理时先不通知页面刷新，全部做完再统一通知（少一些和建档请求交错的读请求）。
 */
import { isAxiosError } from 'axios';
import { assistantApi, chapterOutlineApi, volumeApi } from '@/services/api';
import { emitAssistantData } from '@/store/assistantStore';
import type { AssistantEntityCandidate, AssistantFieldCandidate, AssistantPlan } from '@/types/assistant';
import { planConfirmTargets, planEntity } from '@/utils/cocreation';

export const errorDetail = (err: unknown): string => {
  if (isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
  }
  return err instanceof Error ? err.message : '操作失败';
};

export async function fieldAction(projectId: string, candidate: AssistantFieldCandidate, action: 'apply' | 'undo' | 'reject', notify = true) {
  const call = action === 'apply' ? assistantApi.applyCandidate : action === 'undo' ? assistantApi.undoCandidate : assistantApi.rejectCandidate;
  const next = await call(projectId, candidate.id);
  if (notify && action !== 'reject') emitAssistantData({ entity: next.entity, targetId: next.target_id });
  return next;
}

export async function entityAction(projectId: string, candidate: AssistantEntityCandidate, action: 'apply' | 'reject', notify = true) {
  const call = action === 'apply' ? assistantApi.applyEntityCandidate : assistantApi.rejectEntityCandidate;
  const next = await call(projectId, candidate.id);
  if (notify && action === 'apply') emitAssistantData({ entity: next.entity_type, targetId: next.created_entity_id });
  return next;
}

export async function confirmPlan(plan: AssistantPlan, notify = true): Promise<void> {
  const { volumeIds, outlineIds } = planConfirmTargets(plan);
  await Promise.all([
    ...volumeIds.map((id) => volumeApi.confirm(id, true)),
    ...outlineIds.map((id) => chapterOutlineApi.confirmChapterOutline(id, true)),
  ]);
  if (notify) emitAssistantData({ entity: planEntity(plan) });
}
