import type { Project, StoryOutlineGenerateRequest } from '@/types'

/** 谋篇页「AI 生成总纲」的后台任务 kind（与后端 api/story_outlines.generate_story_outline_stream 一致） */
export const OUTLINE_JOB_KIND = 'story_outline_generate'

/** 这些任务在跑时不再发起总纲生成：本页的 AI 生成，以及向导 / 灵感模式正在给本项目生成总纲 */
export const OUTLINE_BUSY_KINDS = [OUTLINE_JOB_KIND, 'wizard_outline']

export interface OutlineGenerationForm {
  narrative_perspective: string
  chapter_count: number
  target_words: number
  requirements: string
}

/** 生成表单的初始值：视角 / 章数 / 字数取项目设置，没填才用通用默认值 */
export function outlineGenerationDefaults(project?: Pick<Project, 'narrative_perspective' | 'chapter_count' | 'target_words'> | null): OutlineGenerationForm {
  return {
    narrative_perspective: project?.narrative_perspective || '第三人称',
    chapter_count: project?.chapter_count || 30,
    target_words: project?.target_words || 100000,
    requirements: '',
  }
}

const positiveInt = (n: number) => (Number.isFinite(n) && n >= 1 ? Math.trunc(n) : undefined)

/** 表单 → 请求体：章数 / 字数取正整数，清空 / 0 / 乱填的留空（后端按项目设置补齐），免得撞上 422 */
export function outlineGenerationPayload(
  form: OutlineGenerationForm,
  mcp: { enable: boolean; selected: string[] },
): StoryOutlineGenerateRequest {
  return {
    narrative_perspective: form.narrative_perspective,
    chapter_count: positiveInt(form.chapter_count),
    target_words: positiveInt(form.target_words),
    requirements: form.requirements.trim() || undefined,
    enable_mcp: mcp.enable,
    selected_plugins: mcp.selected,
  }
}
