/** 写作链路（候选稿 / 历史版本 / 遵循度审校 / 智能助笔 / 世界地图）的前后端契约类型。 */

export interface AdherenceEventCheck {
  event: string;
  covered: boolean;
  quote: string;
  verified: boolean;
}

export interface AdherenceIssueCheck {
  issue: string;
  quote: string;
  verified: boolean;
}

export interface AdherenceTaskCheck {
  task: string;
  done: boolean;
  quote: string;
  verified: boolean;
}

/** 章纲遵循度审校报告：status=error 表示审校调用失败（不阻断），passed=null */
export interface AdherenceReport {
  status: 'ok' | 'error';
  passed: boolean | null;
  issues: string[];
  unverified: string[];
  message?: string;
  key_events?: AdherenceEventCheck[];
  ending?: { reached: boolean; quote: string; verified: boolean } | null;
  overreach?: AdherenceIssueCheck[];
  new_settings?: AdherenceIssueCheck[];
  narrative_tasks?: AdherenceTaskCheck[];
  summary?: string;
}

export interface CandidateQuality {
  score?: number;
  issues?: string[];
  word_count_ratio?: number | null;
  [key: string]: unknown;
}

export type CandidateSource = 'ai_generate' | 'deai_rewrite' | 'assistant';
export type CandidateMode = 'replace_all' | 'append' | 'replace_range';
export type CandidateStatus = 'pending' | 'adopted' | 'discarded' | 'superseded';

export interface CandidateSummary {
  id: string;
  chapter_id: string;
  source: CandidateSource;
  source_label: string;
  mode: CandidateMode;
  status: CandidateStatus;
  word_count: number;
  preview: string;
  outline_changed: boolean;
  /** 生成后正文被改过（整章候选采用要确认覆盖） */
  base_stale: boolean;
  range_start: number | null;
  range_end: number | null;
  original_text: string | null;
  quality: CandidateQuality | null;
  adherence: AdherenceReport | null;
  meta: Record<string, unknown> | null;
  created_at: string | null;
  decided_at: string | null;
}

export interface CandidateDetail extends CandidateSummary {
  content: string;
}

export interface CandidateAdoptRequest {
  content?: string;
  force?: boolean;
  auto_analyze?: boolean;
}

export interface CandidateAdoptResult {
  chapter: { id: string; project_id: string; chapter_number: number; title: string; content: string; word_count: number; status: string };
  candidate_id: string;
  changed: boolean;
  purged_memories: number;
  snapshot_version_id: string | null;
  analysis_task_id: string | null;
  analysis_job_id: string | null;
}

export interface ChapterVersionSummary {
  id: string;
  chapter_id: string;
  version_number: number;
  word_count: number;
  reason: 'manual_edit' | 'adopt_candidate' | 'restore' | 'assistant' | string;
  note: string | null;
  preview: string;
  created_at: string | null;
}

export interface ChapterVersionDetail extends ChapterVersionSummary {
  content: string;
}

export interface ChapterVersionRestoreResult {
  id: string;
  content: string;
  word_count: number;
  status: string;
  purged_memories: number;
  snapshot_version_id: string | null;
}

/* ─── 世界地图 ─── */

export type MapLocationKind =
  | 'city' | 'town' | 'village' | 'sect' | 'palace' | 'mountain' | 'forest' | 'river' | 'lake' | 'sea'
  | 'desert' | 'ruin' | 'pass' | 'island' | 'other';

export interface MapLocation {
  id: string;
  name: string;
  x: number | null;
  y: number | null;
  kind: MapLocationKind;
  region: string | null;
  description: string | null;
  source_names: string[];
  origin: 'author' | 'ai' | 'rule';
  /** 对应的世界规则「地图位置」；空 = 还没登记到世界规则 */
  rule_id?: string | null;
}

export interface MapLocationRule {
  id: string;
  key: string;
  name: string;
  summary: string | null;
  details: string | null;
}

export interface MapTerrain {
  sea?: 'east' | 'west' | 'north' | 'south' | 'none' | null;
  mountains?: { x: number; y: number; r: number }[];
  rivers?: { points: [number, number][] }[];
  regions?: { name: string; x: number; y: number }[];
}

export interface StoryLocation {
  name: string;
  mentions: number;
  first_chapter: number | null;
  last_chapter: number | null;
  sources: string[];
  bound_to: string | null;
}

export interface WorldMapView {
  map: { seed: number; style: string; terrain: MapTerrain; revision: number; has_candidate: boolean };
  locations: MapLocation[];
  story_locations: StoryLocation[];
}

export interface MapLocationMention {
  chapter_number: number;
  chapter_title: string | null;
  source: 'timeline' | 'signal' | 'outline';
  raw_location: string;
  text: string;
}

export interface MapLocationDossier {
  location: MapLocation;
  /** 世界规则里的设定（规则地点才有） */
  rule: MapLocationRule | null;
  mentions: MapLocationMention[];
}

export interface MapLayoutCandidate {
  terrain: MapTerrain;
  locations: Array<Omit<MapLocation, 'id' | 'origin' | 'rule_id'>>;
}
