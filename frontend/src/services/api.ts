import axios from 'axios';

declare module 'axios' {
  export interface AxiosRequestConfig {
    /** 为 true 时响应错误不弹全局 toast，由调用方自行处理（如「暂无分析结果」404 属正常态） */
    silent?: boolean;
  }
}

interface MCPPluginSimpleCreate {
  config_json: string;
  enabled: boolean;
}
import { toast } from 'sonner';
import { ssePost } from '../utils/sseClient';
import type { SSEClientOptions } from '../utils/sseClient';
import { PROJECT_HEADER, getActiveProjectId } from '../utils/activeProject';
import type { MemoryAnnotation } from '../utils/annotationSegments';
import type { UpdateCheckResult, UpdateJobStatus } from '../types/system_update';
import type {
  User,
  AuthConfig,
  AuthSettingsView,
  AuthSettingsUpdate,
  AnnouncementView,
  AnnouncementSettingsView,
  AnnouncementUpdate,
  Project,
  ProjectCreate,
  ProjectUpdate,
  WorldBuildingResponse,
  Outline,
  OutlineCreate,
  OutlineUpdate,
  Character,
  CharacterUpdate,
  Chapter,
  ChapterCreate,
  ChapterGenerateRequest,
  ChapterUpdate,
  GenerateCharacterRequest,
  GenerateCharactersResponse,
  GenerateOutlineResponse,
  WizardPlotLinesRequest,
  WizardPlotLinesResponse,
  Settings,
  SettingsUpdate,
  AIModelOption,
  ProjectAIOverrides,
  ProjectAIPreference,
  WritingStyle,
  WritingStyleCreate,
  WritingStyleUpdate,
  PresetStyle,
  WritingStyleListResponse,
  MCPPlugin,
  MCPPluginCreate,
  MCPPluginUpdate,
  MCPTestResult,
  MCPTool,
  MCPMarketplaceListResponse,
  MCPMarketplaceInstallRequest,
  PlotCard,
  PlotCardCreate,
  PlotCardUpdate,
  PlotCardGenerateRequest,
  PlotCardReorderRequest,
  PlotCardListResponse,
  PlotLine,
  PlotLineCreate,
  PlotLineUpdate,
  PlotLineGenerateRequest,
  PlotLineReorderRequest,
  PlotLineListResponse,
  PlotLineProgress,
  ChapterOutline,
  ChapterOutlineCreate,
  ChapterOutlineUpdate,
  ChapterOutlineReorderRequest,
  ChapterOutlineListResponse,
  ChapterOutlineBatchCreateRequest,
  PlotLineWithLinks,
  PlotCardWithLinks,
  WorldRule,
  WorldRuleCreate,
  WorldRuleUpdate,
  WorldRuleListResponse,
  PaginationResponse,
  ChapterAnalysisResponse,
  BookDissectTask,
  BookDissectUploadResponse,
  BookDissectV2Overview,
  BookDissectV2ChapterSummary,
  BookDissectV2ChapterDetail,
  BookDissectV2DictionaryEntry,
  BookDissectV2Entity,
  BookDissectV2Relation,
  BookDissectV2Event,
} from '../types';

type ChapterListApiResponse = Chapter[] | { items?: Chapter[] };

/** 正文生成任务的 result 事件 data */
export interface ChapterWriteResult {
  word_count: number;
  analysis_task_id: string | null;
  analysis_job_id: string | null;
}

/** 生成前预检查：前面「有正文但未分析（无记忆状态）」的章节 */
export interface ChapterGenerationPrecheck {
  count: number;
  chapters: Array<{ id: string; chapter_number: number; title: string }>;
  message: string;
}

/** 项目级去 AI 味提示词（GET/POST/PUT/DELETE /projects/{id}/deai-prompts） */
export interface DeaiPrompt {
  id: string;
  project_id: string;
  name: string;
  content: string;
  order_index: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface DeaiPromptInput {
  name: string;
  content: string;
}

/** 去 AI 味重写请求：只带提示词 id（按勾选顺序），后端拼提示词 + 原文 */
export interface ChapterRegenerateRequest {
  prompt_ids: string[];
}

/** GET /chapters/{id}/annotations：正文里可定位的记忆标注 */
export interface ChapterAnnotationsResponse {
  chapter_id: string;
  chapter_number: number;
  title: string;
  word_count: number;
  annotations: MemoryAnnotation[];
  has_analysis: boolean;
  summary: { total_annotations: number; hooks: number; foreshadows: number; plot_points: number; character_events: number };
}

/** 去 AI 味重写任务的 result 事件 data */
export interface ChapterRegenerateResult {
  word_count: number;
}

const api = axios.create({
  baseURL: '/api',
  timeout: 180000, // 3分钟超时
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

api.interceptors.request.use(
  (config) => {
    // 项目内的请求带当前项目 id：后端按项目 AI 偏好覆盖模型 / 参数（见 utils/activeProject.ts）
    const projectId = getActiveProjectId();
    if (projectId) config.headers.set(PROJECT_HEADER, projectId);
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

api.interceptors.response.use(
  (response) => {
    return response.data;
  },
  (error) => {
    let errorMessage = '请求失败';
    
    if (error.response) {
      const status = error.response.status;
      const data = error.response.data;
      
      switch (status) {
        case 400:
          errorMessage = data?.detail || '请求参数错误';
          break;
        case 401:
          if (window.location.pathname !== '/login') {
            errorMessage = '未授权，请先登录';
            window.location.href = '/login';
          } else if (typeof error.config?.url === 'string' && error.config.url.endsWith('/auth/user')) {
            // 登录页探测登录态，「未登录」是正常结果，不提示
            return Promise.reject(error);
          } else {
            // 登录页上的其他 401 是凭据错误，直接展示后端原因（用户名或密码错误 / 邮箱或密码错误）
            errorMessage = data?.detail || '账号或密码错误';
          }
          break;
        case 403:
          errorMessage = '没有权限访问';
          break;
        case 404:
          errorMessage = data?.detail || '请求的资源不存在';
          break;
        case 422:
          errorMessage = data?.detail || '请求参数验证失败';
          if (data?.errors) {
            console.error('验证错误详情:', data.errors);
          }
          break;
        case 500:
          errorMessage = data?.detail || '服务器内部错误';
          break;
        case 503:
          errorMessage = '服务暂时不可用，请稍后重试';
          break;
        default:
          errorMessage = data?.detail || data?.message || `请求失败 (${status})`;
      }
    } else if (error.request) {
      errorMessage = '网络错误，请检查网络连接';
    } else {
      errorMessage = error.message || '请求失败';
    }

    if (error.config?.silent) {
      return Promise.reject(error);
    }
    toast.error(errorMessage);
    console.error('API Error:', errorMessage, error);
    
    return Promise.reject(error);
  }
);

export const authApi = {
  getAuthConfig: () => api.get<unknown, AuthConfig>('/auth/config'),
  
  localLogin: (username: string, password: string) =>
    api.post<unknown, { success: boolean; message: string; user: User }>('/auth/local/login', { username, password }),

  // Linux.do OAuth：拿到授权地址后整页跳转，回调由后端设 Cookie 并 302 回首页
  getLinuxDOAuthUrl: () => api.get<unknown, { auth_url: string; state: string }>('/auth/linuxdo/url'),

  // 邮箱注册（验证码）/ 邮箱密码登录
  emailSendCode: (email: string) =>
    api.post<unknown, { success: boolean; message: string; cooldown_seconds: number }>('/auth/email/send-code', { email }),

  emailRegister: (data: { email: string; code: string; password: string; display_name?: string }) =>
    api.post<unknown, { success: boolean; message: string; user: User }>('/auth/email/register', data),

  emailLogin: (email: string, password: string) =>
    api.post<unknown, { success: boolean; message: string; user: User }>('/auth/email/login', { email, password }),
  
  getCurrentUser: () => api.get<unknown, User>('/auth/user'),
  
  getPasswordStatus: () => api.get<unknown, {
    has_password: boolean;
    has_custom_password: boolean;
    username: string | null;
    default_password: string | null;
  }>('/auth/password/status'),
  
  setPassword: (password: string) =>
    api.post<unknown, { success: boolean; message: string }>('/auth/password/set', { password }),
  
  refreshSession: () => api.post<unknown, { message: string; expire_at: number; remaining_minutes: number }>('/auth/refresh'),
  
  logout: () => api.post('/auth/logout'),
};

export const settingsApi = {
  getSettings: () => api.get<unknown, Settings>('/settings'),
  
  saveSettings: (data: SettingsUpdate) =>
    api.post<unknown, Settings>('/settings', data),
  
  getAvailableModels: (params: { api_key: string; api_base_url: string; provider: string }) =>
    api.get<unknown, { provider: string; models: AIModelOption[]; count?: number }>('/settings/models', { params }),

  /** 用已保存的设置拉模型列表（项目内模型选择器；密钥不经前端） */
  getSavedModels: () =>
    api.get<unknown, { provider: string; models: AIModelOption[]; count?: number }>('/settings/saved-models'),
  
  testApiConnection: (params: { api_key: string; api_base_url: string; provider: string; llm_model: string; max_tokens?: number }) =>
    api.post<unknown, {
      success: boolean;
      message: string;
      response_time_ms?: number;
      provider?: string;
      model?: string;
      response_preview?: string;
      details?: Record<string, boolean>;
      error?: string;
      error_type?: string;
      suggestions?: string[];
    }>('/settings/test', params),
};

/** 系统更新：检查 GitHub Release / 一键更新 / 任务进度（类型见 types/system_update.ts） */
export const systemUpdateApi = {
  check: (force = false) =>
    api.get<unknown, UpdateCheckResult>('/system/update/check', { params: { force } }),

  apply: () => api.post<unknown, UpdateJobStatus>('/system/update/apply'),

  status: () => api.get<unknown, UpdateJobStatus>('/system/update/status'),
};

/** 项目级 AI 偏好：复用设置页接口，按项目覆盖模型 / 参数（null = 跟随全局） */
export const projectAIPreferenceApi = {
  get: (projectId: string) =>
    api.get<unknown, ProjectAIPreference>(`/projects/${projectId}/ai-preference`),

  /** 整体替换：未覆盖的字段传 null */
  save: (projectId: string, overrides: ProjectAIOverrides) =>
    api.put<unknown, ProjectAIPreference>(`/projects/${projectId}/ai-preference`, overrides),

  /** 全部恢复跟随全局 */
  reset: (projectId: string) =>
    api.delete<unknown, ProjectAIPreference>(`/projects/${projectId}/ai-preference`),
};

export const projectApi = {
  getProjects: () => api.get<unknown, { total: number; items: Project[] }>('/projects'),
  
  getProject: (id: string) => api.get<unknown, Project>(`/projects/${id}`),
  
  createProject: (data: ProjectCreate) => api.post<unknown, Project>('/projects', data),
  
  updateProject: (id: string, data: ProjectUpdate) =>
    api.put<unknown, Project>(`/projects/${id}`, data),
  
  deleteProject: (id: string) => api.delete(`/projects/${id}`),
  
  exportProjectData: async (id: string, options: { include_generation_history?: boolean; include_writing_styles?: boolean }) => {
    const response = await axios.post(
      `/api/projects/${id}/export-data`,
      options,
      {
        responseType: 'blob',
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );
    
    // 从响应头获取文件名
    const contentDisposition = response.headers['content-disposition'];
    let filename = 'project_export.json';
    if (contentDisposition) {
      const matches = /filename\*=UTF-8''(.+)/.exec(contentDisposition);
      if (matches && matches[1]) {
        filename = decodeURIComponent(matches[1]);
      }
    }
    
    // 创建下载链接
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  },
  
  // 验证导入文件
  validateImportFile: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<unknown, {
      valid: boolean;
      version: string;
      project_name?: string;
      statistics: Record<string, number>;
      errors: string[];
      warnings: string[];
    }>('/projects/validate-import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  
  // 导入项目
  importProject: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<unknown, {
      success: boolean;
      project_id?: string;
      message: string;
      statistics: Record<string, number>;
      warnings: string[];
    }>('/projects/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  // 数据一致性检查
  checkConsistency: (projectId: string, autoFix = true) =>
    api.post<unknown, Record<string, unknown>>(`/projects/${projectId}/check-consistency`, null, { params: { auto_fix: autoFix } }),

  // 修复组织记录
  fixOrganizations: (projectId: string) =>
    api.post<unknown, { success: boolean; message: string; fixed_count: number; total_count: number }>(`/projects/${projectId}/fix-organizations`),

  // 修复成员计数
  fixMemberCounts: (projectId: string) =>
    api.post<unknown, { success: boolean; message: string; fixed_count: number; total_count: number }>(`/projects/${projectId}/fix-member-counts`),

  // 导出为TXT
  exportTxt: (projectId: string) => {
    window.open(`/api/projects/${projectId}/export`, '_blank');
  },
};

export const outlineApi = {
  getOutlines: (projectId: string) =>
    api.get<unknown, Outline[]>(`/projects/${projectId}/story-outlines`),
  
  createOutline: (projectId: string, data: OutlineCreate) => 
    api.post<unknown, Outline>(`/projects/${projectId}/story-outlines`, data),
  
  updateOutline: (id: string, data: OutlineUpdate) =>
    api.put<unknown, Outline>(`/story-outlines/${id}`, data),
  
  deleteOutline: (id: string) => api.delete(`/story-outlines/${id}`),
  
  activateOutline: (id: string) =>
    api.post<unknown, Outline>(`/story-outlines/${id}/activate`),

  // 获取大纲关联的剧情线
  getPlotLines: (outlineId: string) =>
    api.get<unknown, Array<{ id: string; title: string; description?: string; line_type?: string; order_index?: number }>>(`/story-outlines/${outlineId}/plot-lines`),
};

export const characterApi = {
  getCharacters: (projectId: string) =>
    api.get<unknown, Character[] | PaginationResponse<Character>>(`/characters/project/${projectId}`)
      .then(res => Array.isArray(res) ? res : (res.items || [])),
  
  createCharacter: (data: {
    project_id: string;
    name: string;
    age?: string;
    gender?: string;
    is_organization?: boolean;
    role_type?: string;
    personality?: string;
    background?: string;
    appearance?: string;
    relationships?: string;
    organization_type?: string;
    organization_purpose?: string;
    organization_members?: string;
    traits?: string;
    avatar_url?: string;
    power_level?: number;
    location?: string;
    motto?: string;
    color?: string;
  }) =>
    api.post<unknown, Character>('/characters', data),
  
  updateCharacter: (id: string, data: CharacterUpdate) =>
    api.put<unknown, Character>(`/characters/${id}`, data),
  
  deleteCharacter: (id: string) => api.delete(`/characters/${id}`),
  
  /** AI 生成角色：启动后台任务并从头订阅事件（重连 / 停止走 aiJobsApi）POST /api/characters/generate-stream */
  generateCharacterStream: (data: GenerateCharacterRequest, options?: SSEClientOptions<Character>) =>
    ssePost<Character>('/api/characters/generate-stream', data, options),
};

export const chapterApi = {
  getChapters: (projectId: string) =>
    api.get<unknown, ChapterListApiResponse>(`/chapters/project/${projectId}`)
       .then(res => Array.isArray(res) ? res : (res.items || [])),
  
  getChapter: (id: string) => api.get<unknown, Chapter>(`/chapters/${id}`),
  
  createChapter: (data: ChapterCreate) => api.post<unknown, Chapter>('/chapters', data),
  
  updateChapter: (id: string, data: ChapterUpdate) =>
    api.put<unknown, Chapter>(`/chapters/${id}`, data),
  
  deleteChapter: (id: string) => api.delete(`/chapters/${id}`),
  
  checkCanGenerate: (chapterId: string) =>
    api.get<unknown, import('../types').ChapterCanGenerateResponse>(`/chapters/${chapterId}/can-generate`),

  /** 正文里可定位的记忆标注（钩子 / 伏笔 / 情节点 / 角色事件），未分析时 annotations 为空、has_analysis=false */
  getAnnotations: (chapterId: string) =>
    api.get<unknown, ChapterAnnotationsResponse>(`/chapters/${chapterId}/annotations`),
  
  // 根据章纲获取或创建章节
  syncFromOutlines: (projectId: string) =>
    api.post<unknown, { created: number; skipped: number; total_outlines: number; message: string }>(
      `/chapters/project/${projectId}/sync-from-outlines`
    ),
  
  // 获取章节分析结果（未分析 → 404，属正常态，不弹全局 toast）
  getAnalysis: (chapterId: string) =>
    api.get<unknown, ChapterAnalysisResponse>(`/chapters/${chapterId}/analysis`, { silent: true }),

  /** 手动分析章节：后台任务 + SSE（重连 / 停止走 aiJobsApi）POST /api/chapters/{id}/analyze-stream */
  analyzeChapterStream: (chapterId: string, options?: SSEClientOptions<{ task_id: string; chapter_id: string; status: string }>) =>
    ssePost<{ task_id: string; chapter_id: string; status: string }>(`/api/chapters/${chapterId}/analyze-stream`, {}, options),

  /** 生成前预检查：前面是否有未分析（无记忆状态）的章节，用于提醒用户是否继续 */
  generationPrecheck: (chapterId: string) =>
    api.get<unknown, ChapterGenerationPrecheck>(`/chapters/${chapterId}/generation-precheck`),

  /** AI 创作正文：后台任务 + SSE；result = { word_count, analysis_task_id, analysis_job_id } */
  generateChapterStream: (chapterId: string, data: ChapterGenerateRequest, options?: SSEClientOptions<ChapterWriteResult>) =>
    ssePost<ChapterWriteResult>(`/api/chapters/${chapterId}/generate-stream`, data, options),

  /** 按去 AI 味提示词重写并覆盖正文：后台任务 + SSE；result = { word_count } */
  regenerateChapterStream: (chapterId: string, data: ChapterRegenerateRequest, options?: SSEClientOptions<ChapterRegenerateResult>) =>
    ssePost<ChapterRegenerateResult>(`/api/chapters/${chapterId}/regenerate-stream`, data, options),

  // 批量生成章节
};

export const deaiPromptApi = {
  list: (projectId: string) => api.get<unknown, DeaiPrompt[]>(`/projects/${projectId}/deai-prompts`),
  create: (projectId: string, data: DeaiPromptInput) => api.post<unknown, DeaiPrompt>(`/projects/${projectId}/deai-prompts`, data),
  update: (projectId: string, id: string, data: Partial<DeaiPromptInput>) =>
    api.put<unknown, DeaiPrompt>(`/projects/${projectId}/deai-prompts/${id}`, data),
  remove: (projectId: string, id: string) => api.delete(`/projects/${projectId}/deai-prompts/${id}`),
};

export const writingStyleApi = {
  // 获取预设风格列表
  getPresetStyles: () =>
    api.get<unknown, PresetStyle[]>('/writing-styles/presets/list'),
  
  // 获取项目的所有风格
  getProjectStyles: (projectId: string) =>
    api.get<unknown, WritingStyleListResponse>(`/writing-styles/project/${projectId}`),
  
  // 创建新风格（基于预设或自定义）
  createStyle: (data: WritingStyleCreate) =>
    api.post<unknown, WritingStyle>('/writing-styles', data),
  
  // 更新风格
  updateStyle: (styleId: number, data: WritingStyleUpdate) =>
    api.put<unknown, WritingStyle>(`/writing-styles/${styleId}`, data),
  
  // 删除风格
  deleteStyle: (styleId: number) =>
    api.delete<unknown, { message: string }>(`/writing-styles/${styleId}`),
  
  // 设置默认风格
  setDefaultStyle: (styleId: number, projectId: string) =>
    api.post<unknown, WritingStyle>(`/writing-styles/${styleId}/set-default`, { project_id: projectId }),
  
  // 为项目初始化默认风格（如果没有任何风格）
};

/** 灵感模式候选生成的请求体 */
export interface InspirationOptionsRequest {
  step: 'title' | 'description' | 'theme' | 'genre';
  context: {
    title?: string;
    description?: string;
    theme?: string;
    original_idea?: string;
  };
  hint?: string;
  refinement_context?: {
    requirements?: string[];
    previous_options?: string[];
  };
}

/** 灵感模式候选生成的结果（任务 result 事件的 data；error 为软错误） */
export interface InspirationOptionsResult {
  prompt?: string;
  options: string[];
  error?: string;
}

/** 灵感模式智能补全的请求体 */
export interface InspirationQuickRequest {
  title?: string;
  description?: string;
  theme?: string;
  genre?: string | string[];
  narrative_perspective?: string;
}

/** 灵感模式智能补全的结果（任务 result 事件的 data；error 为软错误） */
export interface InspirationQuickResult {
  title: string;
  description: string;
  theme: string;
  genre: string[];
  narrative_perspective?: string;
  error?: string;
}

export const inspirationApi = {
  /** 生成选项建议：后台任务 + SSE（result 即原 JSON）POST /api/inspiration/generate-options-stream */
  generateOptionsStream: (data: InspirationOptionsRequest, options?: SSEClientOptions<InspirationOptionsResult>) =>
    ssePost<InspirationOptionsResult>('/api/inspiration/generate-options-stream', data, options),

  /** 智能补全缺失信息：后台任务 + SSE（result 即原 JSON）POST /api/inspiration/quick-generate-stream */
  quickGenerateStream: (data: InspirationQuickRequest, options?: SSEClientOptions<InspirationQuickResult>) =>
    ssePost<InspirationQuickResult>('/api/inspiration/quick-generate-stream', data, options),
};

export default api;


export const wizardStreamApi = {
  generateWorldBuildingStream: (
    data: {
      title: string;
      description: string;
      theme: string;
      genre: string | string[];
      generation_prompt?: string;
      narrative_perspective?: string;
      target_words?: number;
      chapter_count?: number;
      character_count?: number;
      provider?: string;
      model?: string;
      enable_mcp?: boolean;
      selected_plugins?: string[];
      // R8 拆书参考包显式参数（项目创建第一步，向后端透传）
      pack_ids?: string[];
      dimensions?: string[];
      strength?: 'light' | 'medium' | 'deep';
    },
    options?: SSEClientOptions<WorldBuildingResponse>
  ) => ssePost<WorldBuildingResponse>(
    '/api/wizard-stream/world-building',
    data,
    options
  ),

  generateCharactersStream: (
    data: {
      project_id: string;
      count?: number;
      world_context?: Record<string, string>;
      theme?: string;
      genre?: string;
      requirements?: string;
      provider?: string;
      model?: string;
      enable_mcp?: boolean;
      selected_plugins?: string[];
      // R8 拆书参考包显式参数
      pack_ids?: string[];
      dimensions?: string[];
      strength?: 'light' | 'medium' | 'deep';
    },
    options?: SSEClientOptions<GenerateCharactersResponse>
  ) => ssePost<GenerateCharactersResponse>(
    '/api/wizard-stream/characters',
    data,
    options
  ),

  /**
   * 生成高层故事大纲（向导/灵感模式）
   * 
   * 注意：此接口生成的是高层故事大纲（单个大纲对象），不再自动生成章节记录
   * 
   * @param data.project_id - 项目ID
   * @param data.chapter_count - 预估章节数（作为提示，不保证生成对应数量的章节）
   * @param data.narrative_perspective - 叙事视角
   * @param data.target_words - 目标字数
   * @param data.requirements - 其他要求
   * @param data.provider - AI提供商
   * @param data.model - AI模型
   * @param data.enable_mcp - 是否启用MCP工具增强（默认true）
   */
  generateCompleteOutlineStream: (
    data: {
      project_id: string;
      chapter_count?: number;  // 改为可选，作为预估提示
      narrative_perspective: string;
      target_words?: number;
      requirements?: string;
      provider?: string;
      model?: string;
      enable_mcp?: boolean;  // 是否启用MCP
      selected_plugins?: string[];  // 选择的插件列表
      // R8：拆书参考包显式参数（任一为空数组/undefined 都走"自动模式"）
      pack_ids?: string[];
      dimensions?: string[];
      strength?: 'light' | 'medium' | 'deep';
    },
    options?: SSEClientOptions<GenerateOutlineResponse>
  ) => ssePost<GenerateOutlineResponse>(
    '/api/wizard-stream/outline',
    data,
    options
  ),

  // 向导步骤 4：生成主线 + 支线（含节点），主线预计章节数 = chapter_count
  generatePlotLinesStream: (
    data: WizardPlotLinesRequest,
    options?: SSEClientOptions<WizardPlotLinesResponse>
  ) => ssePost<WizardPlotLinesResponse>(
    '/api/wizard-stream/plot-lines',
    data,
    options
  ),

  regenerateWorldBuildingStream: (
    projectId: string,
    data?: {
      provider?: string;
      model?: string;
      title?: string;
      description?: string;
      theme?: string;
      genre?: string | string[];
      generation_prompt?: string;
      enable_mcp?: boolean;
      selected_plugins?: string[];
      // R8 拆书参考包显式参数
      pack_ids?: string[];
      dimensions?: string[];
      strength?: 'light' | 'medium' | 'deep';
    },
    options?: SSEClientOptions<WorldBuildingResponse>
  ) => ssePost<WorldBuildingResponse>(
    '/api/wizard-stream/world-building',
    { ...(data || {}), project_id: projectId, mode: 'regenerate' },
    options
  ),

  cleanupWizardDataStream: (
    projectId: string,
    options?: SSEClientOptions<{ message: string; deleted: { characters: number; outlines: number; chapters: number } }>
  ) => ssePost<{ message: string; deleted: { characters: number; outlines: number; chapters: number } }>(
    `/api/wizard-stream/cleanup/${projectId}`,
    {},
    options
  ),
};

export const mcpPluginApi = {
  // 获取所有插件
  getPlugins: (params?: { enabled_only?: boolean }) =>
    api.get<unknown, MCPPlugin[]>('/mcp/plugins', { params }),
  
  // 获取单个插件
  createPlugin: (data: MCPPluginCreate) =>
    api.post<unknown, MCPPlugin>('/mcp/plugins', data),
  
  // 简化创建插件（通过标准MCP配置JSON）
  createPluginSimple: (data: MCPPluginSimpleCreate) =>
    api.post<unknown, MCPPlugin>('/mcp/plugins/simple', data),
  
  // 更新插件
  updatePlugin: (id: string, data: MCPPluginUpdate) =>
    api.put<unknown, MCPPlugin>(`/mcp/plugins/${id}`, data),
  
  // 删除插件
  deletePlugin: (id: string) =>
    api.delete<unknown, { message: string }>(`/mcp/plugins/${id}`),
  
  // 启用/禁用插件
  togglePlugin: (id: string, enabled: boolean) =>
    api.post<unknown, MCPPlugin>(`/mcp/plugins/${id}/toggle`, null, { params: { enabled } }),
  
  // 测试插件连接
  testPlugin: (id: string) =>
    api.post<unknown, MCPTestResult>(`/mcp/plugins/${id}/test`),
  
  // 获取插件工具列表
  getPluginTools: (id: string) =>
    api.get<unknown, { tools: MCPTool[] }>(`/mcp/plugins/${id}/tools`),
  
  // 调用工具
};

// MCP 商城（内置精选目录 + 一键安装）
export const mcpMarketplaceApi = {
  // 目录列表（含当前用户的已安装标记）
  list: () =>
    api.get<unknown, MCPMarketplaceListResponse>('/mcp/marketplace'),

  // 一键安装：inputs 为占位符 → 用户填写的 API Key 等
  install: (itemId: string, data: MCPMarketplaceInstallRequest = {}) =>
    api.post<unknown, MCPPlugin>(`/mcp/marketplace/${itemId}/install`, data),
};

// 管理员API
export const adminApi = {
  // 获取用户列表
  getUsers: () =>
    api.get<unknown, { total: number; users: User[] }>('/admin/users'),
  
  // 添加用户
  createUser: (data: {
    username: string;
    display_name: string;
    password?: string;
    avatar_url?: string;
    trust_level?: number;
    is_admin?: boolean;
  }) =>
    api.post<unknown, {
      success: boolean;
      message: string;
      user: User;
      default_password?: string;
    }>('/admin/users', data),
  
  // 编辑用户
  updateUser: (userId: string, data: {
    display_name?: string;
    avatar_url?: string;
    trust_level?: number;
  }) =>
    api.put<unknown, {
      success: boolean;
      message: string;
      user: User;
    }>(`/admin/users/${userId}`, data),
  
  // 切换用户状态（启用/禁用）
  toggleUserStatus: (userId: string, isActive: boolean) =>
    api.post<unknown, {
      success: boolean;
      message: string;
      is_active: boolean;
    }>(`/admin/users/${userId}/toggle-status`, { is_active: isActive }),
  
  // 重置密码
  resetPassword: (userId: string, newPassword?: string) =>
    api.post<unknown, {
      success: boolean;
      message: string;
      new_password: string;
    }>(`/admin/users/${userId}/reset-password`, { new_password: newPassword }),
  
  // 删除用户
  deleteUser: (userId: string) =>
    api.delete<unknown, {
      success: boolean;
      message: string;
    }>(`/admin/users/${userId}`),

  // 登录方式设置（Linux.do / 邮箱 开关与凭据；秘密字段只回传 *_set）
  getAuthSettings: () => api.get<unknown, AuthSettingsView>('/admin/auth-settings'),

  updateAuthSettings: (data: AuthSettingsUpdate) =>
    api.put<unknown, AuthSettingsView>('/admin/auth-settings', data),

  sendTestEmail: (to: string) =>
    api.post<unknown, { success: boolean; message: string }>('/admin/auth-settings/test-email', { to }),

  // 公告弹窗设置
  getAnnouncement: () => api.get<unknown, AnnouncementSettingsView>('/admin/announcement'),

  updateAnnouncement: (data: AnnouncementUpdate) =>
    api.put<unknown, AnnouncementSettingsView>('/admin/announcement', data),

  uploadAnnouncementImage: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<unknown, { image_url: string }>('/admin/announcement/image', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};

// 登录后公告弹窗（内容由管理员在用户管理页配置）
export const announcementApi = {
  get: () => api.get<unknown, AnnouncementView>('/announcement'),
};

// 剧情卡片 API
export const plotCardApi = {
  // 获取项目的剧情卡片列表
  getPlotCards: (projectId: string, params?: {
    skip?: number;
    limit?: number;
    card_type?: string;
    chapter_outline_id?: string;
  }) =>
    api.get<unknown, PlotCardListResponse>(`/plot-cards/project/${projectId}`, { params }),

  // 获取单个剧情卡片
  createPlotCard: (data: PlotCardCreate) =>
    api.post<unknown, PlotCard>('/plot-cards', data),

  // 更新剧情卡片
  updatePlotCard: (cardId: string, data: PlotCardUpdate) =>
    api.put<unknown, PlotCard>(`/plot-cards/${cardId}`, data),

  // 删除剧情卡片
  deletePlotCard: (cardId: string) =>
    api.delete<unknown, { message: string }>(`/plot-cards/${cardId}`),

  // 重排序剧情卡片
  reorderPlotCards: (data: PlotCardReorderRequest) =>
    api.post<unknown, { message: string }>('/plot-cards/reorder', data),

  /** AI 生成剧情卡片：后台任务 + SSE（重连 / 停止走 aiJobsApi）POST /api/plot-cards/generate-stream */
  generatePlotCardsStream: (data: PlotCardGenerateRequest, options?: SSEClientOptions<PlotCard[]>) =>
    ssePost<PlotCard[]>('/api/plot-cards/generate-stream', data, options),

  // 获取项目中使用的卡片类型
  getCardTypes: (projectId: string) =>
    api.get<unknown, { types: Array<{ type: string; count: number }> }>(`/plot-cards/project/${projectId}/types`),
};

// 剧情线 API
export const plotLineApi = {
  // 获取项目的剧情线列表
  getPlotLines: (projectId: string, params?: {
    skip?: number;
    limit?: number;
    line_type?: string;
  }) =>
    api.get<unknown, PlotLineListResponse>(`/plot-lines/project/${projectId}`, { params }),

  // 获取单个剧情线
  createPlotLine: (data: PlotLineCreate) =>
    api.post<unknown, PlotLine>('/plot-lines', data),

  // 更新剧情线
  updatePlotLine: (lineId: string, data: PlotLineUpdate) =>
    api.put<unknown, PlotLine>(`/plot-lines/${lineId}`, data),

  // 删除剧情线
  deletePlotLine: (lineId: string) =>
    api.delete<unknown, { message: string }>(`/plot-lines/${lineId}`),

  // 重排序剧情线
  reorderPlotLines: (data: PlotLineReorderRequest) =>
    api.post<unknown, { message: string }>('/plot-lines/reorder', data),

  /** AI 生成剧情线：后台任务 + SSE（重连 / 停止走 aiJobsApi）POST /api/plot-lines/generate-stream */
  generatePlotLinesStream: (data: PlotLineGenerateRequest, options?: SSEClientOptions<PlotLine[]>) =>
    ssePost<PlotLine[]>('/api/plot-lines/generate-stream', data, options),

  // 获取项目中使用的剧情线类型
  getLineTypes: (projectId: string) =>
    api.get<unknown, { types: Array<{ type: string; count: number }> }>(`/plot-lines/project/${projectId}/types`),

  // 向剧情线添加剧情卡片
  addCardsToLine: (lineId: string, cardIds: string[]) =>
    api.post<unknown, { message: string }>(`/plot-lines/${lineId}/add-cards`, cardIds),

  // 从剧情线移除剧情卡片
  removeCardsFromLine: (lineId: string, cardIds: string[]) =>
    api.delete<unknown, { message: string }>(`/plot-lines/${lineId}/remove-cards`, { data: cardIds }),

  // 获取剧情线写作进度
  getPlotLineProgress: (lineId: string) =>
    api.get<unknown, PlotLineProgress>(`/plot-lines/${lineId}/progress`),

  // 更新时间线数据
};

// 章纲 API
export const chapterOutlineApi = {
  // 获取项目的章纲列表
  getChapterOutlines: (projectId: string, params?: {
    skip?: number;
    limit?: number;
    plot_line_id?: string;
  }) =>
    api.get<unknown, ChapterOutlineListResponse>(`/chapter-outlines/project/${projectId}`, { params }),

  // 获取单个章纲
  createChapterOutline: (data: ChapterOutlineCreate) =>
    api.post<unknown, ChapterOutline>('/chapter-outlines', data),

  // 更新章纲
  updateChapterOutline: (outlineId: string, data: ChapterOutlineUpdate) =>
    api.put<unknown, ChapterOutline>(`/chapter-outlines/${outlineId}`, data),

  // 删除章纲
  deleteChapterOutline: (outlineId: string) =>
    api.delete<unknown, { message: string }>(`/chapter-outlines/${outlineId}`),

  // 重排序章纲
  reorderChapterOutlines: (data: ChapterOutlineReorderRequest) =>
    api.post<unknown, { message: string }>('/chapter-outlines/reorder', data),

  // 批量创建章纲
  batchCreateChapterOutlines: (data: ChapterOutlineBatchCreateRequest) =>
    api.post<unknown, ChapterOutline[]>('/chapter-outlines/batch', data),

  // 获取项目章纲统计信息
  getChapterOutlineStatistics: (projectId: string) =>
    api.get<unknown, {
      total_count: number;
      total_target_words: number;
      line_statistics: Array<{
        plot_line_id: string | null;
        chapter_count: number;
        total_target_words: number;
      }>;
    }>(`/chapter-outlines/project/${projectId}/statistics`),
};

// ============================================
// 关联管理 API
// ============================================


// 章纲关联管理 API
export const chapterOutlineLinkApi = {
  // 查询关联
  getPlotLines: (outlineId: string) =>
    api.get<unknown, PlotLineWithLinks[]>(`/chapter-outlines/${outlineId}/plot-lines`),

  getPlotCards: (outlineId: string) =>
    api.get<unknown, PlotCardWithLinks[]>(`/chapter-outlines/${outlineId}/plot-cards`),

  // 管理关联
  linkPlotLines: (outlineId: string, data: { plot_line_ids: string[]; role?: string }) =>
    api.post<unknown, { message: string; created_count: number; skipped_count: number }>(
      `/chapter-outlines/${outlineId}/link-plot-lines`,
      {
        plot_line_ids: data.plot_line_ids,
        role: data.role || 'main'
      }
    ),

  unlinkPlotLines: (outlineId: string, plotLineIds: string[]) =>
    api.delete<unknown, { message: string; removed_count: number }>(
      `/chapter-outlines/${outlineId}/unlink-plot-lines`,
      {
        data: { ids: plotLineIds }
      }
    ),

};


// 世界规则系统 API
export const worldRulesApi = {
  // 获取世界规则列表
  list: (projectId: string, category?: 'cultivation_realm' | 'equipment_template' | 'map_location') =>
    api.get<unknown, WorldRuleListResponse>(
      `/projects/${projectId}/world-rules`,
      { params: category ? { category } : {} }
    ),

  // 创建世界规则
  create: (projectId: string, data: WorldRuleCreate) =>
    api.post<unknown, WorldRule>(`/projects/${projectId}/world-rules`, data),

  // 更新世界规则
  update: (ruleId: string, data: WorldRuleUpdate) =>
    api.put<unknown, WorldRule>(`/world-rules/${ruleId}`, data),

  // 删除世界规则
  delete: (ruleId: string) =>
    api.delete<unknown, { message: string }>(`/world-rules/${ruleId}`),
};

// 场景生成 API（简化版 - 按剧情卡片分段生成）
export const sceneGenerationApi = {
  // 获取章纲关联的剧情卡片
  getPlotCards: (chapterOutlineId: string) =>
    api.get<unknown, {
      chapter_outline_id: string;
      plot_cards: Array<{
        id: string;
        title: string;
        content?: string;
        generation_status: string;
        word_count_target: number;
        word_count_actual: number;
        generation_order: number;
      }>;
    }>(`/scene-generation/chapter-outlines/${chapterOutlineId}/plot-cards`),

  // 流式生成场景（使用 ssePost，携带认证拦截）
  generateSceneStream: (
    data: {
      chapter_outline_id: string;
      plot_card_id: string;
      writing_style_id?: string;
      previous_generated_content?: string;
      // R8 拆书参考包显式参数
      pack_ids?: string[];
      dimensions?: string[];
      strength?: 'light' | 'medium' | 'deep';
    },
    options?: SSEClientOptions
  ) => ssePost('/api/scene-generation/generate-scene-stream', data, options),

  // 流式生成场景的 URL（兼容现有裸 fetch 用法）
};

// ============================================
// 关系 API
// ============================================
export const relationshipApi = {
  // 获取关系类型列表
  getTypes: () =>
    api.get<unknown, Array<{
      id: number;
      name: string;
      category: string;
      reverse_name?: string;
      intimacy_range?: string;
      icon?: string;
      description?: string;
    }>>('/relationships/types'),

  // 获取项目关系列表
  getProjectRelationships: (projectId: string) =>
    api.get<unknown, Array<Record<string, unknown>>>(`/relationships/project/${projectId}`),

  // 获取关系图谱数据
  createRelationship: (data: {
    project_id: string;
    character_from_id: string;
    character_to_id: string;
    relationship_type_id?: number;
    relationship_name?: string;
    intimacy_level?: number;
    status?: string;
    description?: string;
    started_at?: string;
    ended_at?: string;
  }) =>
    api.post<unknown, Record<string, unknown>>('/relationships/', data),

  // 更新关系
  updateRelationship: (relationshipId: string, data: {
    relationship_type_id?: number;
    relationship_name?: string;
    intimacy_level?: number;
    status?: string;
    description?: string;
  }) =>
    api.put<unknown, Record<string, unknown>>(`/relationships/${relationshipId}`, data),

  // 删除关系
  deleteRelationship: (relationshipId: string) =>
    api.delete<unknown, { message: string }>(`/relationships/${relationshipId}`),
};

// ============================================
// 组织 API
// ============================================
export const organizationApi = {
  // 获取项目组织列表
  getProjectOrganizations: (projectId: string) =>
    api.get<unknown, Array<Record<string, unknown>>>(`/organizations/project/${projectId}`),

  // 获取组织详情
  createOrganization: (data: {
    character_id: string;
    project_id: string;
    parent_org_id?: string;
    level?: number;
    power_level?: number;
    location?: string;
    motto?: string;
    color?: string;
  }) =>
    api.post<unknown, Record<string, unknown>>('/organizations', data),

  // 更新组织
  updateOrganization: (orgId: string, data: {
    parent_org_id?: string;
    level?: number;
    power_level?: number;
    location?: string;
    motto?: string;
    color?: string;
  }) =>
    api.put<unknown, Record<string, unknown>>(`/organizations/${orgId}`, data),

  // 删除组织
  deleteOrganization: (orgId: string) =>
    api.delete<unknown, { message: string }>(`/organizations/${orgId}`),

  // 获取组织成员
  getMembers: (orgId: string) =>
    api.get<unknown, Array<Record<string, unknown>>>(`/organizations/${orgId}/members`),

  // 添加成员
  addMember: (orgId: string, data: {
    character_id: string;
    position: string;
    rank?: number;
    status?: string;
    joined_at?: string;
    left_at?: string;
    loyalty?: number;
    contribution?: number;
    notes?: string;
  }) =>
    api.post<unknown, Record<string, unknown>>(`/organizations/${orgId}/members`, data),

  // 更新成员
  updateMember: (memberId: string, data: {
    position?: string;
    rank?: number;
    status?: string;
    joined_at?: string;
    left_at?: string;
    loyalty?: number;
    contribution?: number;
    notes?: string;
  }) =>
    api.put<unknown, Record<string, unknown>>(`/organizations/members/${memberId}`, data),

  // 移除成员
  removeMember: (memberId: string) =>
    api.delete<unknown, { message: string }>(`/organizations/members/${memberId}`),

  /** AI 生成组织：后台任务 + SSE（重连 / 停止走 aiJobsApi）POST /api/organizations/generate-stream */
  generateOrganizationStream: (
    data: {
      project_id: string;
      name?: string;
      organization_type?: string;
      background?: string;
      requirements?: string;
      enable_mcp?: boolean;
      selected_plugins?: string[];
    },
    options?: SSEClientOptions<Character>,
  ) => ssePost<Character>('/api/organizations/generate-stream', data, options),
};

// ============================================
// 记忆系统 API
// ============================================
export const memoryApi = {
  // 分析章节记忆
  getProjectMemories: (projectId: string, params?: {
    memory_type?: string;
    chapter_id?: string;
    limit?: number;
  }) =>
    api.get<unknown, { success: boolean; memories: Array<Record<string, unknown>>; total: number }>(`/memories/projects/${projectId}/memories`, { params }),

  // 获取章节分析结果
  searchMemories: (projectId: string, data: {
    query: string;
    memory_types?: string[];
    limit?: number;
    min_importance?: number;
  }) =>
    api.post<unknown, { success: boolean; query: string; memories: Array<Record<string, unknown>>; total: number }>(
      `/memories/projects/${projectId}/search`,
      null,
      { params: data }
    ),

  // 获取未解决伏笔
  getForeshadows: (projectId: string, currentChapter: number) =>
    api.get<unknown, { success: boolean; foreshadows: Array<Record<string, unknown>>; total: number }>(`/memories/projects/${projectId}/foreshadows`, { params: { current_chapter: currentChapter } }),

  // 获取记忆统计
  getStats: (projectId: string) =>
    api.get<unknown, { success: boolean; stats: Record<string, unknown> }>(`/memories/projects/${projectId}/stats`),

  // 删除章节记忆
  deleteChapterMemories: (projectId: string, chapterId: string) =>
    api.delete<unknown, { success: boolean; message: string }>(`/memories/projects/${projectId}/chapters/${chapterId}/memories`),
};


// ============================================
// 拆书参考 API
// ============================================
export const bookDissectApi = {
  /** 上传 txt/md 参考书，返回 task_id + 切分预览（不接 LLM） */
  upload: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<unknown, BookDissectUploadResponse>('/book-dissect/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  /** 查询单个任务状态 + 元信息 + 结果 */
  getTask: (taskId: string) =>
    api.get<unknown, BookDissectTask>(`/book-dissect/${taskId}`),

  /** 列出当前用户所有拆书任务（按创建时间倒序） */
  listTasks: () => api.get<unknown, BookDissectTask[]>('/book-dissect'),

  /** 启动 LLM 抽取（V2 引擎：逐章抽取 + 全书聚合）。 */
  startExtraction: (
    taskId: string,
    params?: {
      sampling_mode?: string
      sampling_param?: number
      extraction_engine?: 'auto' | 'chunked' | 'long_context'
    },
  ) =>
    api.post<unknown, BookDissectTask>(
      `/book-dissect/${taskId}/start-extraction`,
      params ?? { sampling_mode: 'all', sampling_param: 1 },
    ),

  /** 删除任务并清理磁盘文件 */
  deleteTask: (taskId: string) =>
    api.delete<unknown, { message: string; task_id: string }>(`/book-dissect/${taskId}`),

  // V3 R6 废弃：applyToWizard() 已移除。
  // 后端端点统一返 410 Gone；改用 imitationApi.preview / imitationApi.streamUrl
  // 配合 referencePackApi.attach 在用户自己项目内做「一键仿写」。

  // ----- V2 浏览 -----
  v2GetOverview: (taskId: string) =>
    api.get<unknown, BookDissectV2Overview>(`/book-dissect/${taskId}/v2/overview`),

  v2ListChapters: (taskId: string) =>
    api.get<unknown, BookDissectV2ChapterSummary[]>(`/book-dissect/${taskId}/v2/chapters`),

  v2GetChapterDetail: (taskId: string, chapterNumber: number) =>
    api.get<unknown, BookDissectV2ChapterDetail>(
      `/book-dissect/${taskId}/v2/chapters/${chapterNumber}`,
    ),

  v2ListDictionary: (taskId: string) =>
    api.get<unknown, BookDissectV2DictionaryEntry[]>(`/book-dissect/${taskId}/v2/dictionary`),

  v2ListEntities: (taskId: string, entityType?: string, slim = false) =>
    api.get<unknown, BookDissectV2Entity[]>(
      `/book-dissect/${taskId}/v2/entities`,
      {
        params: {
          ...(entityType ? { entity_type: entityType } : {}),
          ...(slim ? { slim: true } : {}),
        },
      },
    ),

  v2GetEntity: (taskId: string, entityId: string) =>
    api.get<unknown, BookDissectV2Entity>(
      `/book-dissect/${taskId}/v2/entities/${entityId}`,
    ),

  v2ListRelations: (taskId: string, category?: string) =>
    api.get<unknown, BookDissectV2Relation[]>(
      `/book-dissect/${taskId}/v2/relations`,
      { params: category ? { relation_category: category } : undefined },
    ),

  v2ListEvents: (taskId: string, importance?: string) =>
    api.get<unknown, BookDissectV2Event[]>(
      `/book-dissect/${taskId}/v2/events`,
      { params: importance ? { importance } : undefined },
    ),
};


// ============================================
// 拆书 V3 仿写：参考包 API
// ============================================
import type {
  ReferencePackSummary,
  ReferencePackDetail,
  ProjectReferencePackItem,
  AttachReferencePackRequest,
  AttachReferencePackResponse,
  UpdateAttachmentRequest,
} from '@/types/reference_pack';

export const referencePackApi = {
  /** 列出当前用户的所有参考包（不含 5 tab 详细内容） */
  list: () => api.get<unknown, ReferencePackSummary[]>('/reference-packs'),

  /** 参考包详情（含 5 tab 完整 JSON） */
  get: (packId: string) =>
    api.get<unknown, ReferencePackDetail>(`/reference-packs/${packId}`),

  /** 删除参考包（同时清理所有项目挂载关联） */
  delete: (packId: string) =>
    api.delete<unknown, { deleted: string }>(`/reference-packs/${packId}`),

  /** 列出某项目已挂载的参考包 */
  listAttachments: (projectId: string) =>
    api.get<unknown, ProjectReferencePackItem[]>(
      `/projects/${projectId}/reference-packs`,
    ),

  /** 挂载参考包到项目 */
  attach: (projectId: string, payload: AttachReferencePackRequest) =>
    api.post<unknown, AttachReferencePackResponse>(
      `/projects/${projectId}/reference-packs`,
      payload,
    ),

  /** 更新挂载配置（默认维度 / 强度） */
  updateAttachment: (
    projectId: string,
    packId: string,
    payload: UpdateAttachmentRequest,
  ) =>
    api.patch<unknown, ProjectReferencePackItem>(
      `/projects/${projectId}/reference-packs/${packId}`,
      payload,
    ),

  /** 卸载参考包（保留项目本体） */
  detach: (projectId: string, packId: string) =>
    api.delete<unknown, { detached: string }>(
      `/projects/${projectId}/reference-packs/${packId}`,
    ),
};


// ============================================
// 拆书 V3 R5：一键仿写（preview / stream）
// ============================================
import type {
  ImitateChapterRequest,
  ImitatePromptPreview,
} from '@/types/reference_pack';

export const imitationApi = {
  /** Dry-run 预览：返回拼装后的 system/user prompt + 使用的 pack/维度/强度 */
  preview: (projectId: string, payload: ImitateChapterRequest) =>
    api.post<unknown, ImitatePromptPreview>(
      `/projects/${projectId}/imitate-chapter-preview`,
      payload,
    ),

  /** 一键仿写：后台任务 + SSE（meta / content / progress；重连 / 停止走 aiJobsApi）POST /api/projects/{id}/imitate-chapter-stream */
  imitateChapterStream: (projectId: string, payload: ImitateChapterRequest, options?: SSEClientOptions<ImitationJobResult>) =>
    ssePost<ImitationJobResult>(`/api/projects/${projectId}/imitate-chapter-stream`, payload, options),
};

/** 仿写任务的 result 事件 data */
export interface ImitationJobResult {
  chars: number;
  used_dimensions: string[];
  strength: string;
}
