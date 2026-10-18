import type { ProjectPromptGroup, ProjectPromptItem } from '@/types/prompts';

const VARIABLE = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g;

/** 与后端 utils/prompt_template 同一规则：只认 {英文名}，{主角} 这类中文花括号、JSON 示例都不算变量 */
export function unknownVariables(content: string, allowed: string[]): string[] {
  const known = new Set(allowed);
  const out: string[] = [];
  for (const match of content.matchAll(VARIABLE)) {
    if (!known.has(match[1]) && !out.includes(match[1])) out.push(match[1]);
  }
  return out;
}

export function insertAt(text: string, start: number, end: number, insert: string): { text: string; caret: number } {
  return { text: text.slice(0, start) + insert + text.slice(end), caret: start + insert.length };
}

export function groupPrompts(groups: ProjectPromptGroup[], items: ProjectPromptItem[]) {
  return groups
    .map((group) => ({ group, items: items.filter((item) => item.group === group.id) }))
    .filter((entry) => entry.items.length > 0);
}

export function countCustomized(items: ProjectPromptItem[]): number {
  return items.filter((item) => item.customized).length;
}
