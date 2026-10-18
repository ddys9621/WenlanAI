/** 项目内 AI 批量生成角色与组织（后端 services/character_batch_service.py） */

/** 与后端 api/characters.batch_generate_characters_stream 的任务 kind 一致 */
export const CAST_BATCH_JOB_KIND = 'character_batch_generate'

/** 与后端 CharacterBatchGenerateRequest 的上限一致 */
export const CAST_BATCH_LIMITS = { characters: 10, organizations: 5 } as const

/** 任务标题：和后端 batch_title 一致（发起时先用它，刷新后托盘里是后端给的同一个标题） */
export function castBatchTitle(characters: number, organizations: number): string {
  const parts = [characters ? `${characters} 个人物` : '', organizations ? `${organizations} 个组织` : ''].filter(Boolean)
  return `AI 批量生成：${parts.join(' · ')}`
}

/** 数量输入框 → 0..max 的整数（空 / 非数字当 0） */
export function clampCastCount(value: string, max: number): number {
  const n = Math.trunc(Number(value))
  return Number.isFinite(n) ? Math.min(max, Math.max(0, n)) : 0
}
