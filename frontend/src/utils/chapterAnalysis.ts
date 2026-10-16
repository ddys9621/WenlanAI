import type { ChapterDigestView, ChapterStateChange } from '@/types'

/** GET /chapters/{id}/analysis 规整后的结构（字段缺失时给空值，面板不用逐个判空） */
export interface NormalizedAnalysisData {
  /** 有分析记录（只有作者档案、没分析过为 false） */
  analyzed: boolean
  /** 章节档案：摘要 + 章末状态（作者版本 / AI 建议） */
  digest: ChapterDigestView | null
  /** 本章结算出的硬性状态变化 */
  state_changes: ChapterStateChange[]
  /** 出场人物与本章变化 */
  characters: Array<{ name: string; change: string }>
  locations: string[]
  /** 最近一次分析任务：failed 带原因（之前的结果仍在用）；completed 的 message 是降级说明 */
  task: { status: string; message: string } | null
  narrative_state: {
    causal_links: Array<Record<string, unknown>>
    promises: Array<Record<string, unknown>>
    timeline_events: Array<Record<string, unknown>>
    relationship_graph: {
      nodes: Array<Record<string, unknown>>
      edges: Array<Record<string, unknown>>
    }
  }
  consistency_audit: {
    summary: {
      total: number
      critical: number
      high: number
      medium: number
      low: number
    }
    issues: Array<Record<string, unknown>>
  }
  /** 章节内容在本次分析之后被修改过（分析/审计结果可能过期） */
  is_stale: boolean
}

function toRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function toRecordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter(Boolean).map(item => toRecord(item))
    : []
}

function toDigest(value: unknown): ChapterDigestView | null {
  const d = toRecord(value)
  if (!d.chapter_id && !d.summary) return null
  const suggestion = toRecord(d.suggestion)
  return {
    chapter_id: String(d.chapter_id || ''),
    summary: String(d.summary || ''),
    end_state: String(d.end_state || ''),
    source: d.source === 'author' ? 'author' : 'ai',
    suggestion: d.suggestion ? { summary: String(suggestion.summary || ''), end_state: String(suggestion.end_state || '') } : null,
    stale: Boolean(d.stale),
    updated_at: typeof d.updated_at === 'string' ? d.updated_at : null,
  }
}

export function normalizeAnalysisData(payload: Record<string, unknown>): NormalizedAnalysisData {
  const source = toRecord(payload)
  const analysis = toRecord(source.analysis)
  const narrativeStateSource = toRecord(source.narrative_state)
  const relationshipGraphSource = toRecord(narrativeStateSource.relationship_graph)
  const consistencyAuditSource = toRecord(source.consistency_audit)
  const consistencySummary = toRecord(consistencyAuditSource.summary)
  const task = toRecord(source.task)

  return {
    analyzed: Boolean(source.analyzed ?? source.analysis),
    digest: toDigest(source.digest),
    state_changes: toRecordArray(source.state_changes).map((s) => ({
      signal_type: String(s.signal_type || ''),
      label: String(s.label || s.signal_type || ''),
      character_name: s.character_name ? String(s.character_name) : null,
      signal_key: s.signal_key ? String(s.signal_key) : null,
      signal_value: String(s.signal_value || ''),
      evidence: s.evidence ? String(s.evidence) : null,
    })),
    characters: toRecordArray(analysis.character_states).map((c, index) => ({
      name: String(c.character_name || c.name || `角色 ${index + 1}`),
      change: String(c.state_after || c.status || ''),
    })),
    locations: Array.isArray(analysis.locations) ? analysis.locations.filter(Boolean).map(String) : [],
    task: task.status ? { status: String(task.status), message: String(task.message || '') } : null,
    narrative_state: {
      causal_links: toRecordArray(narrativeStateSource.causal_links),
      promises: toRecordArray(narrativeStateSource.promises),
      timeline_events: toRecordArray(narrativeStateSource.timeline_events),
      relationship_graph: {
        nodes: toRecordArray(relationshipGraphSource.nodes),
        edges: toRecordArray(relationshipGraphSource.edges),
      },
    },
    consistency_audit: {
      summary: {
        total: Number(consistencySummary.total || 0),
        critical: Number(consistencySummary.critical || 0),
        high: Number(consistencySummary.high || 0),
        medium: Number(consistencySummary.medium || 0),
        low: Number(consistencySummary.low || 0),
      },
      issues: toRecordArray(consistencyAuditSource.issues),
    },
    is_stale: Boolean(source.is_stale),
  }
}

/** 状态变化的一行说明：「林长老 · 生死：死亡」「林尘 · 境界：炼气五层」 */
const VALUE_LABELS: Record<string, string> = {
  dead: '死亡', missing: '失踪', revived: '复活', survived: '生还', alive: '在世',
  arrived: '抵达', left: '离开', current: '现在', gained: '获得', lost: '失去', used: '用掉',
  injured: '受伤', recovered: '痊愈', learned: '学会', mastered: '掌握', forgotten: '遗忘',
}

export function describeStateChange(change: ChapterStateChange): string {
  const who = change.character_name ? `${change.character_name} · ` : ''
  const value = VALUE_LABELS[change.signal_value] ?? change.signal_value
  if (change.signal_type === 'life_state') return `${who}${change.label}：${value}`
  if (change.signal_type === 'story_time') return `故事时间：${change.signal_key ?? ''}`
  if (change.signal_value === 'current') return `${who}${change.label}：${change.signal_key ?? ''}`
  return `${who}${change.label}：${value}${change.signal_key ? ` ${change.signal_key}` : ''}`
}
