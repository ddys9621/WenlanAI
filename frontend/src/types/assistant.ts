/** 全局智能助笔的前后端契约（对应 backend/app/api/assistant.py）。 */

export interface AssistantSelectionCtx {
  start: number
  end: number
  text: string
}

/** 作者发消息时所在的页面（只带上下文，不是权限边界） */
export interface AssistantPageContext {
  page: string
  label: string
  chapter_id?: string | null
  character_id?: string | null
  outline_id?: string | null
  location_id?: string | null
  selection?: AssistantSelectionCtx | null
}

export interface AssistantStep {
  tool: string
  label: string
  ok: boolean
  summary: string
  args?: Record<string, unknown>
}

export interface AssistantQuestionOption {
  id: string
  label: string
  description?: string
  recommended?: boolean
}

export interface AssistantQuestion {
  id: string
  prompt: string
  mode: 'single' | 'multiple' | 'text'
  options: AssistantQuestionOption[]
}

export interface AssistantQuestionCard {
  questions: AssistantQuestion[]
}

export interface AssistantAnswer {
  id: string
  choices: string[]
  text: string
  skipped: boolean
}

export interface AssistantChapterCandidateRef {
  id: string
  chapter_id: string
  chapter_number: number
  chapter_title: string
  mode: string
  word_count: number
  preview: string
}

/** 共创室成员（主编 / 世界观设定师 / 人物设计师 / 总纲策划师 / 章节策划师 / 正文作者 / 审校编辑） */
export interface AssistantMember {
  id: string
  name: string
  initials: string
  color: string
  responsibility: string
  /** 该成员用的模型；null = 跟随项目模型 */
  model: string | null
}

export interface AssistantStarter {
  id: string
  label: string
  hint: string
  message: string
}

export interface AssistantTeam {
  members: AssistantMember[]
  starters: AssistantStarter[]
}

/** 规划工具产出的草案卡片：作者在卡片上确认才算定稿 */
export type AssistantPlan =
  | {
    kind: 'volumes'
    title: string
    volumes: { id: string; volume_number: number; title: string; chapter_start: number; chapter_end: number; summary: string; unit_count: number }[]
  }
  | {
    kind: 'units'
    title: string
    volume: {
      id: string; volume_number: number; title: string; chapter_start: number; chapter_end: number; summary: string; unit_count: number
      units: { index: number; title: string; chapter_start: number; chapter_end: number; story: string }[]
      threads: string[]
    }
  }
  | {
    kind: 'outlines'
    title: string
    volume_id: string
    unit_index: number
    chapters: { id: string; chapter_number: number; title: string; plot_points: string }[]
  }

export interface AssistantProgress {
  text: string
  next_step: { action: string; label: string; [key: string]: unknown }
}

export interface AssistantMessageView {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string | null
  run_id: string | null
  steps: AssistantStep[]
  candidates: string[]
  chapter_candidates: AssistantChapterCandidateRef[]
  question?: AssistantQuestionCard | null
  answer?: AssistantAnswer[] | null
  page?: AssistantPageContext | null
  plans?: AssistantPlan[]
  /** 发言的成员（作者消息为 null） */
  member?: AssistantMember | null
  /** 主编交给成员处理后，成员以自己名义的回复 */
  delegated?: boolean
}

export type AssistantCandidateStatus = 'candidate' | 'applied' | 'undone' | 'rejected'

export interface AssistantFieldCandidate {
  id: string
  field_id: string
  target_id: string
  entity: string | null
  label: string
  page: string | null
  before: unknown
  after: unknown
  reason: string
  status: AssistantCandidateStatus
  run_id: string | null
  created_at: string | null
  decided_at: string | null
}

/** interrupted：库里残留 running 但没有在跑的任务（服务重启 / 任务异常），只在读取时这样显示 */
export type AssistantRunStatus = 'running' | 'waiting_input' | 'completed' | 'failed' | 'cancelled' | 'interrupted'

export interface AssistantRunView {
  id: string
  session_id: string
  goal: string
  status: AssistantRunStatus
  message: string
  step_count: number
  question: AssistantQuestionCard | null
  steps: AssistantStep[]
  created_at: string | null
  updated_at: string | null
}

export interface AssistantSessionInfo {
  id: string
  title: string
  archived: boolean
  created_at: string | null
  updated_at: string | null
  message_count?: number
}

export interface AssistantSessionView {
  session: AssistantSessionInfo | null
  messages: AssistantMessageView[]
  active_run: AssistantRunView | null
  candidates: AssistantFieldCandidate[]
}

export interface AssistantRunResult {
  run: AssistantRunView
  message: AssistantMessageView
  candidates: AssistantFieldCandidate[]
  chapter_candidates: AssistantChapterCandidateRef[]
}

export interface AssistantPreview {
  message: string
  page: string
  history_count: number
  sections: { label: string; content: string }[]
  rules: string
}

export interface AssistantCheckItem {
  kind: 'outline_unconfirmed' | 'analysis_missing' | 'analysis_stale' | 'candidate_pending' | 'field_candidate' | 'consistency' | string
  severity: string
  title: string
  detail: string
  page: string
  target_id?: string
  chapter_number?: number
}

export interface AssistantChecks {
  items: AssistantCheckItem[]
  counts: Record<string, number>
}
