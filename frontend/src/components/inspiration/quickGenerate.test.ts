import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), warning: vi.fn(), info: vi.fn(), success: vi.fn() } }));

import { toast } from 'sonner';
import type { InspirationQuickResult } from '../../services/api';
import { wizardReducer } from './reducer';
import { createInitialState, type WizardAction, type WizardState } from './types';
import { runQuickGenerate } from './useInspirationMachine';

/** 用真 reducer 接住 dispatch，断言流程走完后的状态 */
function harness(initial: WizardState) {
  let state = initial;
  return {
    dispatch: (action: WizardAction) => {
      state = wizardReducer(state, action);
    },
    get state() {
      return state;
    },
  };
}

const THEME_OPTIONS = ['成长', '复仇', '救赎'];

/** 选好书名和简介、正停在「主题」一步看 AI 给的主题候选 */
const themeStep = (): WizardState => ({
  ...createInitialState(),
  currentStep: 'theme',
  wizardData: { originalIdea: '少年下山', title: '青云', description: '少年下山闯江湖' },
  messages: [
    ...createInitialState().messages,
    { id: 'm1', type: 'ai', content: '这本书的核心主题是什么？', options: THEME_OPTIONS },
  ],
});

const filled: InspirationQuickResult = {
  title: '青云', description: '少年下山闯江湖', theme: '成长', genre: ['仙侠'], narrative_perspective: '第三人称',
};

beforeEach(() => vi.clearAllMocks());

describe('灵感模式「让 AI 补全剩余项」', () => {
  it('任务失败 → 留在当前步骤、原候选还能选，并提示真实原因', async () => {
    const h = harness(themeStep());
    await runQuickGenerate(h.state, h.dispatch, async () => {
      throw new Error('「灵感：智能补全书籍信息」已有任务在运行，请等待完成或先停止');
    });
    expect(h.state.currentStep).toBe('theme');
    expect(h.state.loading).toBe(false);
    expect(h.state.messages.at(-1)).toMatchObject({ options: THEME_OPTIONS });
    expect(h.state.messages.at(-1)?.disabled).toBeFalsy();
    expect(h.state.wizardData).toMatchObject({ title: '青云', description: '少年下山闯江湖' });
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('已有任务在运行'));
  });

  it('后端软错误（result.error）同样留在原步骤', async () => {
    const h = harness(themeStep());
    await runQuickGenerate(h.state, h.dispatch, async () => ({ ...filled, error: 'AI返回格式错误，请重试' }));
    expect(h.state.currentStep).toBe('theme');
    expect(h.state.messages.at(-1)).toMatchObject({ options: THEME_OPTIONS });
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('AI返回格式错误'));
  });

  it('补全期间也停在当前步骤（不切到「书名」）', async () => {
    const h = harness(themeStep());
    let during: Pick<WizardState, 'currentStep' | 'loading'> | null = null;
    await runQuickGenerate(h.state, h.dispatch, async () => {
      during = { currentStep: h.state.currentStep, loading: h.state.loading };
      return filled;
    });
    expect(during).toEqual({ currentStep: 'theme', loading: true });
  });

  it('补全成功 → 写回信息并进入确认', async () => {
    const h = harness(themeStep());
    await runQuickGenerate(h.state, h.dispatch, async () => filled);
    expect(h.state.currentStep).toBe('confirm');
    expect(h.state.loading).toBe(false);
    expect(h.state.wizardData).toMatchObject({ theme: '成长', genre: ['仙侠'], narrative_perspective: '第三人称' });
  });
});
