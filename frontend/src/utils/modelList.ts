import type { AIModelOption } from '@/types'

export interface ModelGroup {
  /** 分组名（vendor 前缀）；null = 不分组 */
  group: string | null
  items: AIModelOption[]
}

const OTHER_GROUP = '其他'

/** 大小写不敏感的子串过滤（value / label 任一命中）；空查询返回全部 */
export function filterModels(models: AIModelOption[], query: string): AIModelOption[] {
  const q = query.trim().toLowerCase()
  if (!q) return models
  return models.filter((m) => m.value.toLowerCase().includes(q) || m.label.toLowerCase().includes(q))
}

/** 网关模型 id 多为 vendor/model：≥8 个且过半带斜杠时按 vendor 分组（保持首次出现顺序），否则单组 */
export function groupModels(models: AIModelOption[]): ModelGroup[] {
  const slashed = models.filter((m) => m.value.indexOf('/') > 0).length
  if (models.length < 8 || slashed * 2 < models.length) return [{ group: null, items: models }]
  const map = new Map<string, AIModelOption[]>()
  for (const m of models) {
    const i = m.value.indexOf('/')
    const key = i > 0 ? m.value.slice(0, i) : OTHER_GROUP
    const list = map.get(key)
    if (list) list.push(m)
    else map.set(key, [m])
  }
  return [...map.entries()].map(([group, items]) => ({ group, items }))
}

/** 条目显示名：分组内去掉 vendor 前缀；不分组用 label（无则 value） */
export function displayName(m: AIModelOption, group: string | null): string {
  if (group && m.value.startsWith(group + '/')) return m.value.slice(group.length + 1)
  return m.label || m.value
}
