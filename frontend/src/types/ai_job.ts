/**
 * 通用 AI 后台任务 — 前端类型
 *
 * 对应 backend/app/services/ai_jobs.py（快照）与 generation_trace.py（事件）。
 * 事件契约见 agent-docs/plans/2026-09-11-ai-job-foundation.md「事件词汇」。
 */

export type AIJobStatus = 'running' | 'done' | 'error' | 'cancelled';
export type StageStatus = 'running' | 'done' | 'error' | 'skipped' | 'cancelled';
export type ToolCallStatus = 'running' | 'done' | 'error';
export type LLMPhase = 'start' | 'thinking' | 'streaming' | 'done' | 'error';

export interface AIJobProgressEvent {
  type: 'progress';
  message?: string;
  progress?: number;
  status?: string;
  word_count?: number;
  seq?: number;
}

export interface AIJobStageEvent {
  type: 'stage';
  name: string;
  label: string;
  status: StageStatus;
  elapsed?: number;
  detail?: Record<string, unknown>;
  error?: string;
  seq?: number;
}

export interface AIJobToolCallEvent {
  type: 'tool_call';
  call_id: string;
  tool: string;
  plugin: string;
  status: ToolCallStatus;
  args_preview?: string;
  elapsed_ms?: number;
  result_chars?: number;
  error?: string;
  seq?: number;
}

export interface AIJobReferenceItem {
  title: string;
  detail?: string;
  chars?: number;
}

export interface AIJobReferenceEvent {
  type: 'reference';
  kind: string;
  label: string;
  items: AIJobReferenceItem[];
  count: number;
  seq?: number;
  /** 各来源自带的附加信息（scene / strength / query / warnings …） */
  [key: string]: unknown;
}

export interface AIJobLLMEvent {
  type: 'llm';
  call_id: string;
  phase: LLMPhase;
  model: string;
  reasoning_chars: number;
  content_chars: number;
  elapsed: number;
  finish_reason?: string | null;
  prompt_chars?: number;
  tool_calls?: number;
  error?: string;
  seq?: number;
}

/** GET /api/ai-jobs[/{id}] 的快照（AIJob.snapshot()） */
export interface AIJobSnapshot {
  id: string;
  kind: string;
  title: string;
  project_id: string | null;
  scope: string | null;
  meta: Record<string, unknown>;
  status: AIJobStatus;
  started_at: number;
  finished_at: number | null;
  elapsed: number;
  seq: number;
  error: string | null;
  result: unknown;
  last_progress: AIJobProgressEvent | null;
  live: Partial<Record<'progress' | 'llm' | 'thinking' | 'partial', Record<string, unknown>>>;
}

/* ---------- 前端归约后的状态（utils/aiJobReducer.ts 产出） ---------- */

export interface AIJobStage {
  name: string;
  label: string;
  status: StageStatus;
  elapsed?: number;
  detail?: Record<string, unknown>;
  error?: string;
}

export interface AIJobToolCall {
  call_id: string;
  tool: string;
  plugin: string;
  status: ToolCallStatus;
  args_preview?: string;
  elapsed_ms?: number;
  result_chars?: number;
  error?: string;
}

export interface AIJobLLM {
  model: string;
  phase: LLMPhase;
  reasoning_chars: number;
  content_chars: number;
  elapsed: number;
  finish_reason: string | null;
}

/** 与后端事件流的连接状态（任务本身可能仍在跑） */
export type AIJobConnection = 'connecting' | 'live' | 'lost' | 'closed';

export interface AIJobState {
  id: string;
  kind: string;
  title: string;
  projectId: string | null;
  /** 业务附加信息（后端 AIJob.meta，如 chapter_id）；前端 start() 也可传 */
  meta: Record<string, unknown>;
  status: AIJobStatus;
  /** 毫秒时间戳 */
  startedAt: number;
  finishedAt: number | null;
  lastSeq: number;
  progress: { message: string; pct: number } | null;
  wordCount: number | null;
  stages: AIJobStage[];
  toolCalls: AIJobToolCall[];
  references: AIJobReferenceEvent[];
  llm: AIJobLLM | null;
  /** content / chunk 事件累积的正文 */
  content: string;
  result: unknown;
  error: string | null;
  errorCode: number | null;
  connection: AIJobConnection;
}

/**
 * 任务摘要：横幅 / 托盘 / 页面列表只需要这些字段。
 * 不含 content / stages / toolCalls / references / result，正文任务每秒几十条 content 事件就不会触发它们重渲染。
 */
export type AIJobSummary = Pick<
  AIJobState,
  'id' | 'kind' | 'title' | 'projectId' | 'meta' | 'status' | 'startedAt' | 'finishedAt' | 'progress' | 'wordCount' | 'llm' | 'error' | 'connection'
>;

export const AI_JOB_SUMMARY_KEYS: readonly (keyof AIJobSummary)[] = [
  'id', 'kind', 'title', 'projectId', 'meta', 'status', 'startedAt', 'finishedAt', 'progress', 'wordCount', 'llm', 'error', 'connection',
];

const AI_JOB_KIND_LABELS: Record<string, string> = {
  volume_plan: '卷纲规划',
  chapter_batch: '批量写作',
  character_generate: '角色生成',
  organization_generate: '组织生成',
  chapter_generate: '正文生成',
  chapter_regenerate: '去 AI 味重写',
  chapter_analyze: '章节分析',
  chapter_analyze_batch: '按章序分析',
  memory_index_rebuild: '重建检索索引',
  memory_index_rebuild_all: '换模型后重建检索索引',
  embedding_model_download: '下载向量模型',
  chapter_imitate: '一键仿写',
  book_dissect: '拆书抽取',
  wizard_world_building: '向导·世界构建',
  wizard_characters: '向导·角色',
  wizard_outline: '向导·总纲',
  wizard_volumes: '向导·卷纲',
  inspiration_options: '灵感候选',
  inspiration_quick: '灵感补全',
  assistant_run: '智能助笔',
  chapter_assistant: '智能助笔·单章',
  world_map_generate: '地图布局',
};

export const kindLabel = (kind: string) => AI_JOB_KIND_LABELS[kind] ?? kind;
