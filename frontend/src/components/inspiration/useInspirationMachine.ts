/** 灵感模式状态机 Hook - 封装 reducer + API 副作用 */

import { useReducer, useCallback } from 'react';
import { toast } from 'sonner';
import {
  inspirationApi,
  type InspirationOptionsRequest,
  type InspirationOptionsResult,
  type InspirationQuickRequest,
  type InspirationQuickResult,
} from '../../services/api';
import { runAIJob } from '../../store/aiJobsStore';
import { wizardReducer } from './reducer';
import { createInitialState } from './types';
import type { GenerationApiContext, OptionGenerationStep, RefinementContext, Step, WizardData } from './types';

const REGENERATE_OPTIONS = new Set(['重新生成', '让AI重新生成']);
const CUSTOM_INPUT_OPTIONS = new Set(['我自己输入书名', '我自己输入']);

/** API step → 下一个显示步骤的映射 */
const API_STEP_MAP: Record<OptionGenerationStep, { loadingStep: Step; successStep: Step }> = {
  title: { loadingStep: 'loading_title', successStep: 'title' },
  description: { loadingStep: 'loading_desc', successStep: 'description' },
  theme: { loadingStep: 'loading_theme', successStep: 'theme' },
  genre: { loadingStep: 'loading_genre', successStep: 'genre' },
};

/** 当前 step → 需要调用的 API step */
const NEXT_API_STEP: Record<string, OptionGenerationStep> = {
  idea: 'title',
  title: 'description',
  description: 'theme',
  theme: 'genre',
};

/** 候选生成失败后 currentStep 停在 loading_*，用户此时"自己写"的就是该步骤的字段 */
const LOADING_STEP_TARGET: Partial<Record<Step, Step>> = {
  loading_title: 'title',
  loading_desc: 'description',
  loading_theme: 'theme',
  loading_genre: 'genre',
};

type BuildContextInput = Partial<WizardData> & Partial<GenerationApiContext>;

/** 构建 API context */
const buildApiContext = (
  step: OptionGenerationStep,
  data: BuildContextInput,
  userInput?: string,
): GenerationApiContext => {
  const originalIdea = (userInput || data.originalIdea || data.original_idea || '').trim();
  const base = originalIdea ? { original_idea: originalIdea } : {};

  switch (step) {
    case 'title': return { ...base, description: userInput || data.originalIdea || data.description };
    case 'description': return { ...base, title: data.title };
    case 'theme': return { ...base, title: data.title, description: data.description };
    case 'genre': return { ...base, title: data.title, description: data.description, theme: data.theme };
    default: return {};
  }
};

const buildRefinementContext = (
  context?: RefinementContext,
  hint?: string,
): RefinementContext => {
  const trimmedHint = hint?.trim();
  const requirements = [...(context?.requirements ?? [])];

  if (trimmedHint && requirements[requirements.length - 1] !== trimmedHint) {
    requirements.push(trimmedHint);
  }

  return {
    requirements,
    previousOptions: context?.previousOptions ?? [],
  };
};

const hasRefinementContext = (context: RefinementContext) =>
  context.requirements.length > 0 || context.previousOptions.length > 0;

const STEP_LABELS: Record<OptionGenerationStep, string> = { title: '书名', description: '简介', theme: '主题', genre: '类型' };

/**
 * 候选生成走通用后台任务（不弹窗：对话气泡里已有骨架屏；托盘可见、刷新不丢）。
 * 任务硬失败折成软错误 {error}，让下面的状态机分支保持原样。
 */
async function requestOptions(data: InspirationOptionsRequest): Promise<InspirationOptionsResult> {
  try {
    const job = await runAIJob({
      kind: 'inspiration_options',
      title: `灵感：生成${STEP_LABELS[data.step]}候选`,
      openModal: false,
      connect: (options) => inspirationApi.generateOptionsStream(data, options),
    });
    return (job.result as InspirationOptionsResult | null) ?? { options: [], error: '生成失败' };
  } catch (err) {
    return { options: [], error: err instanceof Error ? err.message : '生成失败' };
  }
}

async function requestQuickGenerate(data: InspirationQuickRequest): Promise<InspirationQuickResult> {
  const job = await runAIJob({
    kind: 'inspiration_quick',
    title: '灵感：智能补全书籍信息',
    openModal: false,
    connect: (options) => inspirationApi.quickGenerateStream(data, options),
  });
  return (job.result as InspirationQuickResult | null) ?? { title: '', description: '', theme: '', genre: [], error: '补全失败' };
}

export function useInspirationMachine() {
  const [state, dispatch] = useReducer(wizardReducer, undefined, createInitialState);

  /** 通用 API 调用：生成选项 */
  const callGenerateOptions = useCallback(async (
    apiStep: OptionGenerationStep,
    context: BuildContextInput,
    userInput?: string,
    hint?: string,
    refinementContext?: RefinementContext,
  ) => {
    const mapping = API_STEP_MAP[apiStep];
    dispatch({ type: 'API_LOADING', payload: mapping.loadingStep });

    try {
      const trimmedHint = hint?.trim() || undefined;
      const requestContext = buildApiContext(apiStep, context, userInput);
      const requestRefinementContext = buildRefinementContext(refinementContext, trimmedHint);
      const requestData = {
        step: apiStep,
        context: requestContext,
        ...(trimmedHint ? { hint: trimmedHint } : {}),
        ...(hasRefinementContext(requestRefinementContext)
          ? {
              refinement_context: {
                requirements: requestRefinementContext.requirements,
                previous_options: requestRefinementContext.previousOptions,
              },
            }
          : {}),
      };

      const response = await requestOptions(requestData);

      if (response.error || !response.options || response.options.length < 3) {
        const stepLabel = { title: '书名', description: '简介', theme: '主题', genre: '类型' }[apiStep];
        dispatch({
          type: 'API_ERROR',
          payload: {
            error: response.error
              ? `生成${stepLabel}时出错：${response.error}\n\n你可以选择：`
              : `生成的选项格式不正确（至少需要3个有效选项）\n\n你可以选择：`,
            retryContext: {
              step: apiStep,
              context: requestContext,
              hint: trimmedHint,
              refinementContext: requestRefinementContext,
            },
            options: response.options?.length ? response.options : ['重新生成', '我自己输入'],
          },
        });
        return;
      }

      dispatch({
        type: 'API_SUCCESS',
        payload: {
          nextStep: mapping.successStep,
          aiMessage: {
            type: 'ai',
            content: response.prompt || `请选择一个${apiStep === 'genre' ? '类型标签（可多选）' : '选项'}，或者输入你自己的：`,
            options: response.options,
            isMultiSelect: apiStep === 'genre',
          },
        },
      });
      dispatch({
        type: 'RECORD_REFINEMENT_RESULT',
        payload: { step: apiStep, hint: trimmedHint, options: response.options },
      });
    } catch (error: unknown) {
      const detail =
        typeof error === 'object' &&
        error !== null &&
        'response' in error &&
        typeof (error as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
          ? (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null;
      console.error(`生成${apiStep}失败:`, error);
      toast.error(detail || '生成失败，请重试');
      dispatch({
        type: 'API_ERROR',
        payload: {
          error: '生成失败，请重试',
          retryContext: {
            step: apiStep,
            context: buildApiContext(apiStep, context, userInput),
            hint: hint?.trim() || undefined,
            refinementContext: buildRefinementContext(refinementContext, hint),
          },
        },
      });
    }
  }, []);

  /** 自定义输入处理（非 idea 阶段） */
  const handleCustomInput = useCallback(async (input: string) => {
    const updatedData = { ...state.wizardData };
    const step = LOADING_STEP_TARGET[state.currentStep] ?? state.currentStep;

    if (step === 'title') updatedData.title = input;
    else if (step === 'description') updatedData.description = input;
    else if (step === 'theme') updatedData.theme = input;
    else if (step === 'genre') {
      dispatch({ type: 'ADVANCE_TO_PERSPECTIVE', payload: { genres: [input], sourceText: input } });
      return;
    }
    else if (step === 'perspective') {
      dispatch({ type: 'SELECT_PERSPECTIVE', payload: input });
      dispatch({ type: 'SET_WIZARD_DATA', payload: { narrative_perspective: input } });
      return;
    }

    dispatch({ type: 'SET_WIZARD_DATA', payload: updatedData });

    const nextApiStep = NEXT_API_STEP[step];
    if (nextApiStep) {
      await callGenerateOptions(nextApiStep, updatedData);
    }
  }, [state.currentStep, state.wizardData, callGenerateOptions]);

  /** 发送消息（idea 阶段） */
  const sendMessage = useCallback(async (input: string) => {
    if (!input.trim()) {
      toast.warning('请输入内容');
      return;
    }
    dispatch({ type: 'SEND_MESSAGE', payload: input });

    if (state.currentStep === 'idea') {
      const originalIdea = input.trim();
      dispatch({ type: 'SET_WIZARD_DATA', payload: { originalIdea } });
      await callGenerateOptions('title', { originalIdea }, originalIdea);
    } else {
      // 非 idea 阶段的自定义输入
      await handleCustomInput(input);
    }
  }, [callGenerateOptions, handleCustomInput, state.currentStep]);

  /** 重试 */
  const retry = useCallback(async () => {
    if (!state.retryContext) return;
    const { step, context, hint, refinementContext } = state.retryContext;

    // 移除上一条错误消息
    dispatch({ type: 'RETRY' });
    await callGenerateOptions(step, context, undefined, hint, refinementContext);
  }, [state.retryContext, callGenerateOptions]);

  /** 换一批：对当前步骤重新生成选项，可带额外提示 */
  const regenerateOptions = useCallback(async (hint?: string) => {
    const stepMap: Record<string, OptionGenerationStep> = {
      title: 'title',
      description: 'description',
      theme: 'theme',
      genre: 'genre',
    };
    const apiStep = stepMap[state.currentStep];
    if (!apiStep) return;

    const trimmedHint = hint?.trim() || undefined;
    dispatch({ type: 'DISABLE_LAST_OPTIONS' });
    dispatch({
      type: 'ADD_MESSAGE',
      payload: { type: 'user', content: trimmedHint ? `重新生成：${trimmedHint}` : '重新生成' },
    });
    await callGenerateOptions(
      apiStep,
      state.wizardData,
      undefined,
      trimmedHint,
      state.refinementContexts[apiStep],
    );
  }, [state.currentStep, state.refinementContexts, state.wizardData, callGenerateOptions]);

  /** 选择选项 */
  const selectOption = useCallback(async (option: string) => {
    // 重试
    if (REGENERATE_OPTIONS.has(option) && state.retryContext) {
      await retry();
      return;
    }
    // 自行输入提示
    if (CUSTOM_INPUT_OPTIONS.has(option)) {
      toast.info('请在下方输入框中输入您的内容');
      return;
    }
    // Genre 多选
    if (state.currentStep === 'genre') {
      dispatch({ type: 'TOGGLE_GENRE', payload: option });
      return;
    }
    // 视角选择
    if (state.currentStep === 'perspective') {
      dispatch({ type: 'SELECT_PERSPECTIVE', payload: option });
      dispatch({ type: 'SET_WIZARD_DATA', payload: { narrative_perspective: option } });
      return;
    }
    // 确认阶段
    if (state.currentStep === 'confirm') {
      if (option === '✅ 确认创建') {
        dispatch({ type: 'CONFIRM_CREATE' });
        return; // 由外部 useProjectGeneration 接管
      }
      if (option === '🔄 重新开始') {
        dispatch({ type: 'RESTART' });
        return;
      }
    }

    // 常规选项选择
    dispatch({ type: 'SELECT_OPTION', payload: option });
    const updatedData = { ...state.wizardData };
    if (state.currentStep === 'title') updatedData.title = option;
    else if (state.currentStep === 'description') updatedData.description = option;
    else if (state.currentStep === 'theme') updatedData.theme = option;
    dispatch({ type: 'SET_WIZARD_DATA', payload: updatedData });

    const nextApiStep = NEXT_API_STEP[state.currentStep];
    if (nextApiStep) {
      await callGenerateOptions(nextApiStep, updatedData);
    }
  }, [callGenerateOptions, retry, state.currentStep, state.retryContext, state.wizardData]);

  /** 确认 Genre */
  const confirmGenres = useCallback(() => {
    if (state.selectedOptions.length === 0) {
      toast.warning('请至少选择一个类型');
      return;
    }
    dispatch({ type: 'CONFIRM_GENRES' });
  }, [state.selectedOptions]);

  /** 快速生成：用已有信息调用 quickGenerate 补全缺失字段，直接跳到确认 */
  const quickGenerate = useCallback(async () => {
    const data = state.wizardData;
    if (!data.title && !data.description && !data.theme) {
      toast.warning('请至少提供标题、简介或主题中的一项');
      return;
    }
    dispatch({ type: 'API_LOADING', payload: 'loading_title' });
    try {
      const result = await requestQuickGenerate({
        title: data.title,
        description: data.description,
        theme: data.theme,
        genre: data.genre,
        narrative_perspective: data.narrative_perspective,
      });
      if (result.error) {
        throw new Error(result.error);
      }
      // 视角缺失时兜底为第三人称：readyToGenerate 依赖它，缺了创建流程会卡在 0%
      const completed = {
        title: result.title || data.title || '',
        description: result.description || data.description || '',
        theme: result.theme || data.theme || '',
        genre: result.genre?.length ? result.genre : data.genre || [],
        narrative_perspective: result.narrative_perspective || data.narrative_perspective || '第三人称',
      };
      dispatch({ type: 'SET_WIZARD_DATA', payload: completed });
      dispatch({
        type: 'API_SUCCESS',
        payload: {
          nextStep: 'confirm',
          aiMessage: {
            type: 'ai',
            content: `已为你快速补全所有信息：\n\n📖 书名：${completed.title}\n📝 简介：${completed.description}\n🎨 主题：${completed.theme}\n🏷️ 类型：${completed.genre.join('、')}\n👁️ 视角：${completed.narrative_perspective}\n\n请确认是否开始创建项目？`,
            options: ['✅ 确认创建', '🔄 重新开始'],
          },
        },
      });
    } catch {
      toast.error('快速生成失败，请重试');
      dispatch({
        type: 'API_ERROR',
        payload: { error: '快速生成失败，请重试' },
      });
    }
  }, [state.wizardData]);

  /** 重置 */
  const reset = useCallback(() => {
    dispatch({ type: 'RESTART' });
  }, []);

  return {
    state,
    dispatch,
    sendMessage,
    selectOption,
    confirmGenres,
    quickGenerate,
    regenerateOptions,
    retry,
    reset,
  };
}
