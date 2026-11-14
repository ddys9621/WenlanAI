/** 故事账本（原「记忆系统」）：/api/memories/projects/{id}/... 的数据结构 */
import type { ChapterAnalysisStatus, ChapterDigestView } from './index';

export interface LedgerOverview {
  latest_chapter: number;
  chapters: { written: number; ok: number; stale: number; missing: number; failed: number; running: number };
  promises: { active: number; resolved: number; abandoned: number; overdue: number; dropout: number };
  index: { available: boolean; model: string | null; count: number; ledger_items: number; rebuilding: boolean };
}

export type PromiseStatus = 'open' | 'progressing' | 'resolved' | 'broken' | 'abandoned';
export type PromiseType = 'foreshadow' | 'promise' | 'mystery' | 'conflict' | 'secret';
export type PromisePriority = 'low' | 'medium' | 'high' | 'critical';

export interface LedgerPromise {
  id: string;
  promise_type: PromiseType;
  title: string;
  content: string;
  priority: PromisePriority;
  status: PromiseStatus;
  status_label: string;
  source_chapter_number: number;
  resolved_chapter_number: number | null;
  deadline_chapter: number | null;
  last_activated_chapter: number | null;
  /** 超期 / 临近 / 掉线 等提醒（已回收的为空） */
  flag: string;
  owner_name: string | null;
  target_name: string | null;
  resolution_note: string | null;
  evidence: string | null;
  /** 作者改过的字段（重新分析不覆盖）；["*"] = 作者新建 */
  locked_fields: string[];
}

export interface PromiseUpdate {
  title?: string;
  content?: string;
  promise_type?: PromiseType;
  priority?: PromisePriority;
  /** 0 = 清除计划回收章 */
  deadline_chapter?: number;
  status?: 'open' | 'resolved' | 'abandoned';
  resolved_chapter_number?: number;
  /** 本章强化：最近提及章挪到这一章，未回收的转推进中 */
  activated_chapter_number?: number;
  note?: string;
}

/** 写第 N 章时该照应的一条伏笔（章纲要回收 / 推进、超期 / 临近、掉线）；flag 按第 N 章算 */
export interface PromiseReminder extends LedgerPromise {
  /** 列出来的原因：本章章纲要回收 / 本章章纲要推进 / 已在本章回收 / 超期、临近、掉线的提醒 */
  reason: string;
  planned: 'resolve' | 'advance' | null;
  /** 章纲里写的怎么回收 / 推进 */
  how: string;
  resolved_here: boolean;
  reinforced_here: boolean;
}

export interface PromiseCreate {
  title: string;
  content?: string;
  promise_type: PromiseType;
  priority: PromisePriority;
  source_chapter_number: number;
  deadline_chapter?: number | null;
}

export interface CharacterStateRow {
  name: string;
  role: string | null;
  life: string | null;
  life_chapter: number | null;
  location: string | null;
  realm: string | null;
  items: string[];
  injuries: string[];
  abilities: string[];
  goal: string | null;
  last_seen: number | null;
  /** 作者修正条数 */
  corrections: number;
}

export interface CharacterHistoryRow {
  id: string;
  source: 'ai' | 'author';
  chapter_number: number;
  signal_type: string;
  label: string;
  signal_key: string | null;
  signal_value: string;
  evidence: string | null;
}

export type CorrectionType = 'life_state' | 'location' | 'realm' | 'item' | 'injury' | 'goal' | 'ability' | 'story_time';

export interface StateCorrectionCreate {
  character_name: string;
  chapter_number: number;
  signal_type: CorrectionType;
  signal_key?: string;
  signal_value: string;
  note?: string;
}

export interface DigestRow {
  chapter_id: string;
  chapter_number: number;
  title: string;
  digest: ChapterDigestView | null;
  analysis_status: ChapterAnalysisStatus;
  analysis_message: string | null;
}

export interface TimelineItem {
  kind: 'event' | 'causal';
  id: string;
  chapter_number: number;
  event_type?: string;
  title?: string;
  description?: string;
  location?: string | null;
  time_marker?: string | null;
  cause?: string;
  event?: string;
  effect?: string;
  decision?: string | null;
  importance?: number | null;
  actors: string[];
  targets: string[];
  visibility?: string;
}

export interface RecallSection {
  key: string;
  title: string;
  text: string;
  chars: number;
}

export interface RecallItem {
  id: string;
  kind: string;
  chapter_number: number;
  text: string;
  score: number;
  reasons: string[];
}

export interface RecallPreview {
  chapter_number: number;
  sections: RecallSection[];
  relevant_items: RecallItem[];
  stats: Record<string, number>;
}

export interface LedgerSearchItem {
  id: string;
  kind: string;
  kind_label: string;
  chapter_number: number;
  text: string;
  score: number;
  match: 'keyword' | 'semantic' | 'both';
}

export interface BatchAnalyzeRequest {
  from_chapter: number;
  to_chapter: number;
  mode: 'missing' | 'stale' | 'all';
}

export interface BatchAnalyzeResult {
  total: number;
  analyzed: number[];
  failed: { chapter_number: number; error: string }[];
  skipped: number[];
  message: string;
}
