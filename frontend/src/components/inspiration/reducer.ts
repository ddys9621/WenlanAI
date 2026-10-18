/** 灵感模式状态机 - 纯函数 Reducer */

import type { WizardState, WizardAction, Message } from './types';
import { createInitialState } from './types';

let _msgCounter = 0;
const genMsgId = (): string => `msg_${Date.now()}_${++_msgCounter}`;

/** 将最后一条带 options 的 AI 消息标记为 disabled */
const disableLastOptions = (messages: Message[]): Message[] => {
  const result = [...messages];
  for (let i = result.length - 1; i >= 0; i--) {
    if (result[i].type === 'ai' && result[i].options?.length) {
      result[i] = { ...result[i], disabled: true };
      break;
    }
  }
  return result;
};

/** 添加用户消息并禁用历史选项 */
const addUserMsg = (messages: Message[], content: string): Message[] => {
  const disabled = disableLastOptions(messages);
  return [...disabled, { id: genMsgId(), type: 'user', content }];
};

/** 添加 AI 消息 */
const addAiMsg = (messages: Message[], msg: Omit<Message, 'id'>): Message[] => [
  ...messages,
  { ...msg, id: genMsgId() },
];

const buildPerspectivePrompt = (messages: Message[], userContent: string) =>
  addAiMsg(addUserMsg(messages, userContent), {
    type: 'ai',
    content: '很好！最后一步，请选择小说的叙事视角：',
    options: ['第一人称', '第三人称', '全知视角'],
  });

export function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    // ---- 用户发送消息 ----
    case 'SEND_MESSAGE':
      return {
        ...state,
        messages: addUserMsg(state.messages, action.payload),
        loading: true,
      };

    // ---- 选择选项（非 genre / perspective / confirm） ----
    case 'SELECT_OPTION':
      return {
        ...state,
        messages: addUserMsg(state.messages, action.payload),
        loading: true,
      };

    // ---- Genre 多选切换 ----
    case 'TOGGLE_GENRE': {
      const opt = action.payload;
      const selected = state.selectedOptions.includes(opt)
        ? state.selectedOptions.filter(o => o !== opt)
        : [...state.selectedOptions, opt];
      return { ...state, selectedOptions: selected };
    }

    // ---- 确认 Genre 选择 ----
    case 'CONFIRM_GENRES': {
      if (state.selectedOptions.length === 0) return state;
      const content = state.selectedOptions.join('、');
      return {
        ...state,
        messages: buildPerspectivePrompt(state.messages, content),
        wizardData: { ...state.wizardData, genre: state.selectedOptions },
        selectedOptions: [],
        currentStep: 'perspective',
        loading: false,
      };
    }

    case 'ADVANCE_TO_PERSPECTIVE':
      return {
        ...state,
        messages: buildPerspectivePrompt(state.messages, action.payload.sourceText),
        wizardData: { ...state.wizardData, genre: action.payload.genres },
        selectedOptions: [],
        currentStep: 'perspective',
        loading: false,
      };

    // ---- 选择视角 → 进入 confirm ----
    case 'SELECT_PERSPECTIVE': {
      const data = {
        ...state.wizardData,
        narrative_perspective: action.payload,
        genre: state.wizardData.genre || [],
      };
      const summary = `太棒了！你的小说设定已完成，请确认：

📖 书名：${data.title}
📝 简介：${data.description}
🎯 主题：${data.theme}
🏷️ 类型：${(data.genre || []).join('、')}
👁️ 视角：${data.narrative_perspective}

请选择下一步操作：`;

      return {
        ...state,
        messages: addAiMsg(
          addUserMsg(state.messages, action.payload),
          { type: 'ai', content: summary, options: ['✅ 确认创建', '🔄 重新开始'] }
        ),
        wizardData: data,
        currentStep: 'confirm',
        loading: false,
      };
    }

    // ---- 确认创建 ----
    case 'CONFIRM_CREATE':
      return {
        ...state,
        messages: addAiMsg(
          addUserMsg(state.messages, '确认创建'),
          { type: 'ai', content: '好的！正在为你创建项目，这可能需要几分钟时间...' }
        ),
        currentStep: 'generating',
        loading: true,
        // 上一次创建失败后 progress 会停在中途，不清零会挡住重新创建的自动启动
        progress: 0,
        progressMessage: '',
        generationError: null,
      };

    // ---- 重新开始 ----
    case 'RESTART':
      return createInitialState();

    // ---- API 状态 ----
    case 'API_LOADING':
      return { ...state, currentStep: action.payload, loading: true };

    // 本次请求作废（如智能补全失败）：只停止加载，步骤与已有候选原样保留
    case 'API_IDLE':
      return { ...state, loading: false };

    case 'API_SUCCESS':
      return {
        ...state,
        messages: addAiMsg(state.messages, action.payload.aiMessage),
        currentStep: action.payload.nextStep,
        loading: false,
        retryContext: null,
      };

    case 'API_ERROR': {
      const errorMsg: Omit<Message, 'id'> = {
        type: 'ai',
        content: action.payload.error,
        options: action.payload.options || ['重新生成', '我自己输入'],
      };
      return {
        ...state,
        messages: addAiMsg(state.messages, errorMsg),
        loading: false,
        retryContext: action.payload.retryContext || null,
      };
    }

    case 'RETRY':
      return { ...state, loading: true };

    // ---- 数据收集 ----
    case 'SET_WIZARD_DATA':
      return { ...state, wizardData: { ...state.wizardData, ...action.payload } };

    case 'RECORD_REFINEMENT_RESULT': {
      const existing = state.refinementContexts[action.payload.step] ?? {
        requirements: [],
        previousOptions: [],
      };
      const hint = action.payload.hint?.trim();
      const requirements =
        hint && existing.requirements[existing.requirements.length - 1] !== hint
          ? [...existing.requirements, hint]
          : existing.requirements;

      return {
        ...state,
        refinementContexts: {
          ...state.refinementContexts,
          [action.payload.step]: {
            requirements,
            previousOptions: action.payload.options,
          },
        },
      };
    }

    // ---- 生成流程 ----
    case 'GEN_START':
      return {
        ...state,
        currentStep: 'generating',
        projectTitle: action.payload.title,
        generationSteps: { worldBuilding: 'pending', characters: 'pending', outline: 'pending', volumes: 'pending' },
        progress: 0,
        progressMessage: '开始创建项目...',
        loading: true,
        generationError: null,
        generationMeta: {
          startedAt: Date.now(),
          lastUpdateAt: Date.now(),
          elapsedSec: 0,
          chunks: 0,
          stallLevel: 'none',
        },
      };

    case 'GEN_PROGRESS':
      return {
        ...state,
        progress: action.payload.progress,
        progressMessage: action.payload.message,
        generationSteps: action.payload.steps
          ? { ...state.generationSteps, ...action.payload.steps }
          : state.generationSteps,
        generationMeta: {
          ...state.generationMeta,
          lastUpdateAt: Date.now(),
          chunks: state.generationMeta.chunks + 1,
          stallLevel: 'none',
        },
      };

    case 'GEN_ACTIVITY':
      return {
        ...state,
        generationMeta: {
          ...state.generationMeta,
          lastUpdateAt: Date.now(),
          chunks: state.generationMeta.chunks + 1,
          stallLevel: 'none',
        },
      };

    case 'GEN_TICK': {
      if (state.currentStep !== 'generating' || !state.generationMeta.startedAt) return state;
      const now = Date.now();
      const elapsedSec = Math.floor((now - state.generationMeta.startedAt) / 1000);
      const sinceLast = state.generationMeta.lastUpdateAt ? now - state.generationMeta.lastUpdateAt : 0;
      // 单个节点一次 LLM 调用常常 30~60 秒没有中间进度，阈值不能太敏感
      const stallLevel = sinceLast > 90000 ? 'stalled' : sinceLast > 30000 ? 'slow' : 'none';
      return {
        ...state,
        generationMeta: {
          ...state.generationMeta,
          elapsedSec,
          stallLevel,
        },
      };
    }

    case 'GEN_STEP_UPDATE':
      return {
        ...state,
        generationSteps: { ...state.generationSteps, ...action.payload },
      };

    case 'GEN_PROJECT_CREATED':
      return { ...state, projectId: action.payload };

    case 'GEN_COMPLETE':
      return {
        ...state,
        currentStep: 'complete',
        progress: 100,
        progressMessage: '项目创建完成！',
        loading: false,
        generationMeta: {
          ...state.generationMeta,
          lastUpdateAt: Date.now(),
          stallLevel: 'none',
        },
      };

    case 'GEN_ERROR':
      return {
        ...state,
        currentStep: 'confirm',
        loading: false,
        progressMessage: action.payload,
        generationError: action.payload,
        generationMeta: {
          startedAt: null,
          lastUpdateAt: null,
          elapsedSec: 0,
          chunks: 0,
          stallLevel: 'none',
        },
      };
    case 'ADD_MESSAGE':
      return {
        ...state,
        messages: addAiMsg(state.messages, action.payload),
      };

    case 'DISABLE_LAST_OPTIONS':
      return {
        ...state,
        messages: disableLastOptions(state.messages),
      };

    default:
      return state;
  }
}
