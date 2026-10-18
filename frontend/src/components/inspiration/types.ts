/** 灵感模式状态机 - 类型定义 */

// 向导步骤（显式状态）
export type Step =
  | 'idea'
  | 'loading_title'
  | 'title'
  | 'loading_desc'
  | 'description'
  | 'loading_theme'
  | 'theme'
  | 'loading_genre'
  | 'genre'
  | 'perspective'
  | 'confirm'
  | 'generating'
  | 'complete';

export type OptionGenerationStep = 'title' | 'description' | 'theme' | 'genre';

export interface Message {
  id: string;
  type: 'ai' | 'user';
  content: string;
  options?: string[];
  isMultiSelect?: boolean;
  disabled?: boolean;
}

export interface WizardData {
  originalIdea?: string;
  title: string;
  description: string;
  theme: string;
  genre: string[];
  narrative_perspective: string;
}

export type GenStepStatus = 'pending' | 'processing' | 'completed' | 'error';
export interface GenerationSteps {
  worldBuilding: GenStepStatus;
  characters: GenStepStatus;
  outline: GenStepStatus;
  volumes: GenStepStatus;
}

type StallLevel = 'none' | 'slow' | 'stalled';
export interface GenerationMeta {
  startedAt: number | null;
  lastUpdateAt: number | null;
  elapsedSec: number;
  chunks: number;
  stallLevel: StallLevel;
}

export interface GenerationApiContext {
  title?: string;
  description?: string;
  theme?: string;
  original_idea?: string;
}

export interface RefinementContext {
  requirements: string[];
  previousOptions: string[];
}

export interface RetryContext {
  step: OptionGenerationStep;
  context: GenerationApiContext;
  hint?: string;
  refinementContext?: RefinementContext;
}

export interface WizardState {
  currentStep: Step;
  messages: Message[];
  wizardData: Partial<WizardData>;
  selectedOptions: string[];
  loading: boolean;
  projectId: string;
  projectTitle: string;
  progress: number;
  progressMessage: string;
  generationSteps: GenerationSteps;
  generationMeta: GenerationMeta;
  /** 上一轮创建 / 续跑中断的原因；开始新一轮、重新确认创建、重新开始时清空 */
  generationError: string | null;
  refinementContexts: Partial<Record<OptionGenerationStep, RefinementContext>>;
  retryContext: RetryContext | null;
}

export type WizardAction =
  | { type: 'SEND_MESSAGE'; payload: string }
  | { type: 'SELECT_OPTION'; payload: string }
  | { type: 'TOGGLE_GENRE'; payload: string }
  | { type: 'CONFIRM_GENRES' }
  | { type: 'ADVANCE_TO_PERSPECTIVE'; payload: { genres: string[]; sourceText: string } }
  | { type: 'CONFIRM_CREATE' }
  | { type: 'RESTART' }
  | { type: 'RETRY' }
  | { type: 'API_LOADING'; payload: Step }
  | { type: 'API_IDLE' }
  | { type: 'API_SUCCESS'; payload: { nextStep: Step; aiMessage: Omit<Message, 'id'> } }
  | { type: 'API_ERROR'; payload: { error: string; retryContext?: RetryContext; options?: string[] } }
  | { type: 'RECORD_REFINEMENT_RESULT'; payload: { step: OptionGenerationStep; hint?: string; options: string[] } }
  | { type: 'GEN_START'; payload: { title: string } }
  | { type: 'GEN_PROGRESS'; payload: { progress: number; message: string; steps?: Partial<GenerationSteps> } }
  | { type: 'GEN_STEP_UPDATE'; payload: Partial<GenerationSteps> }
  | { type: 'GEN_ACTIVITY' }
  | { type: 'GEN_TICK' }
  | { type: 'GEN_PROJECT_CREATED'; payload: string }
  | { type: 'GEN_COMPLETE' }
  | { type: 'GEN_ERROR'; payload: string }
  | { type: 'SET_WIZARD_DATA'; payload: Partial<WizardData> }
  | { type: 'SELECT_PERSPECTIVE'; payload: string }
  | { type: 'ADD_MESSAGE'; payload: Omit<Message, 'id'> }
  | { type: 'DISABLE_LAST_OPTIONS' };

export const createInitialState = (): WizardState => ({
  currentStep: 'idea',
  messages: [
    {
      id: 'welcome',
      type: 'ai',
      content: '你好！我是你的AI创作助手。让我们一起创作一部精彩的小说吧！\n\n请告诉我，你想写一本什么样的小说？',
    },
  ],
  wizardData: {},
  selectedOptions: [],
  loading: false,
  projectId: '',
  projectTitle: '',
  progress: 0,
  progressMessage: '',
  generationSteps: { worldBuilding: 'pending', characters: 'pending', outline: 'pending', volumes: 'pending' },
  generationMeta: { startedAt: null, lastUpdateAt: null, elapsedSec: 0, chunks: 0, stallLevel: 'none' },
  generationError: null,
  refinementContexts: {},
  retryContext: null,
});
