/** 灵感模式 - 流程步骤映射与纯工具函数（无组件、无副作用） */

import type { GenerationArtifacts, GenerationNodeKey } from './useProjectGeneration';
import type { OptionGenerationStep, Step } from './types';

export const FLOW_STEPS = ['idea', 'title', 'description', 'theme', 'genre', 'perspective', 'confirm'] as const;
export type FlowStep = (typeof FLOW_STEPS)[number];

type StepChipStatus = 'done' | 'current' | 'upcoming';

/** 状态机 Step → 头部步骤条使用的展示步骤 */
export function getFlowStep(step: Step): FlowStep {
  switch (step) {
    case 'loading_title':
    case 'title':
      return 'title';
    case 'loading_desc':
    case 'description':
      return 'description';
    case 'loading_theme':
    case 'theme':
      return 'theme';
    case 'loading_genre':
    case 'genre':
      return 'genre';
    case 'perspective':
      return 'perspective';
    case 'confirm':
    case 'generating':
    case 'complete':
      return 'confirm';
    default:
      return 'idea';
  }
}

/** 正在加载候选时对应的 API 步骤（用于挑选等待文案） */
export function getLoadingApiStep(step: Step): OptionGenerationStep | null {
  switch (step) {
    case 'loading_title':
      return 'title';
    case 'loading_desc':
      return 'description';
    case 'loading_theme':
      return 'theme';
    case 'loading_genre':
      return 'genre';
    default:
      return null;
  }
}

export function getStepChipStatus(index: number, activeIndex: number, currentStep: Step): StepChipStatus {
  if (currentStep === 'complete') return 'done';
  if (currentStep === 'generating') return index < FLOW_STEPS.length - 1 ? 'done' : 'current';
  if (index < activeIndex) return 'done';
  if (index === activeIndex) return 'current';
  return 'upcoming';
}

/** 书名统一带一层《》：AI 返回的候选常常自带书名号，避免出现《《x》》 */
export function formatBookTitle(title?: string, fallback = '未命名项目') {
  const bare = (title ?? '').trim().replace(/^[《「『"“]+|[》」』"”]+$/g, '').trim();
  return `《${bare || fallback}》`;
}

/** 秒 → m:ss */
export function formatDuration(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
}

/** 生成节点完成后的一行摘要；没有产物时返回 null，由界面回退到节点提示文案 */
export function getNodePreview(node: GenerationNodeKey, artifacts: GenerationArtifacts): string | null {
  if (node === 'worldBuilding') {
    const world = artifacts.worldBuilding;
    if (!world) return null;
    return [world.time_period, world.location, world.atmosphere].filter(Boolean).join(' · ') || '世界观已生成';
  }

  if (node === 'characters') {
    if (artifacts.characters.length === 0) return null;
    const names = artifacts.characters.slice(0, 4).map((character) => character.name).join('、');
    return artifacts.characters.length > 4 ? `${names} 等 ${artifacts.characters.length} 人` : names;
  }

  if (node === 'volumes') {
    const result = artifacts.volumes;
    if (!result || result.volumes.length === 0) return null;
    const titles = result.volumes.slice(0, 3).map((v) => `《${v.title}》`).join('、');
    return `共 ${result.volumes.length} 卷 / ${result.chapter_count} 章：${titles}${result.volumes.length > 3 ? ' …' : ''}`;
  }

  const content = artifacts.outline?.content;
  if (!content) return null;
  try {
    const parsed = JSON.parse(content) as { premise?: string };
    return parsed.premise || content;
  } catch {
    return content;
  }
}
