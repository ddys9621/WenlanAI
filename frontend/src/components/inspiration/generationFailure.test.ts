import { describe, expect, it } from 'vitest';
import { getInterruption } from './flow';
import { wizardReducer } from './reducer';
import { createInitialState, type WizardAction, type WizardState } from './types';

const run = (state: WizardState, actions: WizardAction[]) => actions.reduce(wizardReducer, state);

/** 已收齐信息、停在确认页的状态 */
const confirmState = (): WizardState => ({
  ...createInitialState(),
  currentStep: 'confirm',
  wizardData: { title: '青云', description: '少年下山', theme: '成长', genre: ['仙侠'], narrative_perspective: '第三人称' },
});

describe('灵感模式创建中断', () => {
  it('首次创建在世界观失败（项目没建成）→ 只给失败文案，不给续跑入口', () => {
    const state = run(confirmState(), [
      { type: 'CONFIRM_CREATE' },
      { type: 'GEN_START', payload: { title: '青云' } },
      { type: 'GEN_STEP_UPDATE', payload: { worldBuilding: 'processing' } },
      { type: 'GEN_PROGRESS', payload: { progress: 2, message: '开始生成世界观...' } },
      { type: 'GEN_STEP_UPDATE', payload: { worldBuilding: 'error' } },
      { type: 'GEN_ERROR', payload: '向导：生成世界构建失败: 模型超时' },
    ]);
    expect(state.currentStep).toBe('confirm');
    expect(getInterruption(state)).toEqual({ message: '向导：生成世界构建失败: 模型超时', resumeNode: null });
  });

  it('续跑在第一个进度事件前就失败（进度停在 0，如 409）→ 仍保留失败文案与续跑入口，不会退回「开始创建项目」再建一个', () => {
    const state = run(confirmState(), [
      { type: 'CONFIRM_CREATE' },
      { type: 'GEN_START', payload: { title: '青云' } },
      { type: 'GEN_PROJECT_CREATED', payload: 'p1' },
      { type: 'GEN_STEP_UPDATE', payload: { worldBuilding: 'completed', characters: 'error' } },
      { type: 'GEN_ERROR', payload: '连接在生成完成前中断' },
      // 作者点「从「角色」继续」：节点进度区间从 0 起，请求还没发出去就被拒
      { type: 'GEN_START', payload: { title: '青云' } },
      { type: 'GEN_STEP_UPDATE', payload: { worldBuilding: 'completed' } },
      { type: 'GEN_PROGRESS', payload: { progress: 0, message: '正在生成角色...' } },
      { type: 'GEN_STEP_UPDATE', payload: { characters: 'error' } },
      { type: 'GEN_ERROR', payload: '「向导：生成角色」已有任务在运行，请等待完成或先停止' },
    ]);
    expect(state.progress).toBe(0);
    expect(getInterruption(state)).toEqual({
      message: '「向导：生成角色」已有任务在运行，请等待完成或先停止',
      resumeNode: 'characters',
    });
  });

  it('续跑入口落在第一个失败环节；没有标失败时落在第一个未完成环节', () => {
    const base = { ...confirmState(), projectId: 'p1', generationError: '生成失败' };
    expect(getInterruption({
      ...base,
      generationSteps: { worldBuilding: 'completed', characters: 'completed', outline: 'error', volumes: 'pending' },
    }).resumeNode).toBe('outline');
    expect(getInterruption({
      ...base,
      generationSteps: { worldBuilding: 'completed', characters: 'completed', outline: 'pending', volumes: 'pending' },
    }).resumeNode).toBe('outline');
  });

  it('重新开始 / 再次确认创建 / 开始新一轮生成都会清掉上一次的失败', () => {
    const failed = run(confirmState(), [
      { type: 'GEN_START', payload: { title: '青云' } },
      { type: 'GEN_ERROR', payload: '生成失败' },
    ]);
    expect(failed.generationError).toBe('生成失败');
    expect(wizardReducer(failed, { type: 'CONFIRM_CREATE' }).generationError).toBeNull();
    expect(wizardReducer(failed, { type: 'GEN_START', payload: { title: '青云' } }).generationError).toBeNull();
    expect(wizardReducer(failed, { type: 'RESTART' }).generationError).toBeNull();
  });

  it('没出过错的确认页没有中断信息', () => {
    expect(getInterruption(confirmState())).toEqual({ message: null, resumeNode: null });
  });
});
