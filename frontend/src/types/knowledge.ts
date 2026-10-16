/** 知识库（用户级、跨项目）：来源 → 条目。字段与后端 app/schemas/knowledge.py 一一对应。 */
export type KbLayer = 'index' | 'fact' | 'method' | 'style';

export type KbEntryType =
  | 'guide'
  | 'synopsis'
  | 'characters'
  | 'methodology'
  | 'structure'
  | 'style'
  | 'excerpt'
  | 'volume'
  | 'arc'
  | 'chapter';

export interface KbSource {
  id: string;
  kind: 'dissect' | 'manual';
  title: string;
  author: string | null;
  genre: string | null;
  dissect_task_id: string | null;
  chapter_count: number;
  total_words: number;
  notes: string | null;
  entry_counts: Partial<Record<KbEntryType, number>>;
  created_at: string | null;
  updated_at: string | null;
}

export interface KbSourceUpdate {
  title?: string;
  author?: string | null;
  genre?: string | null;
  notes?: string | null;
}

export interface KbEntrySummary {
  id: string;
  source_id: string;
  entry_key: string;
  entry_type: KbEntryType;
  layer: KbLayer;
  title: string;
  summary: string;
  chapter_start: number | null;
  chapter_end: number | null;
  volume_index: number | null;
  arc_index: number | null;
  origin: 'generated' | 'author';
  status: 'unreviewed' | 'confirmed';
  upstream_changed: boolean;
  revision: number;
}

export interface KbEntry extends KbEntrySummary {
  body: string;
  denamed_body: string;
  data: Record<string, unknown>;
  tags: string[];
  position: number | null;
}

export interface KbEntryUpdate {
  title?: string;
  summary?: string;
  body?: string;
  denamed_body?: string;
}

export interface KbSearchHit extends KbEntrySummary {
  source_title: string;
}

export interface KbSearchResult {
  items: KbSearchHit[];
  total: number;
}

/** 仿写方式：跟写结构 / 借鉴节奏（默认）/ 只学文风（只影响正文）/ 关闭 */
export type KbMode = 'follow' | 'borrow' | 'style' | 'off';

/** 建项目时（向导 / 灵感模式）选的对标书；sourceId 为空 = 不对标 */
export interface KbSourceChoice {
  sourceId: string;
  mode: KbMode;
}

export type KbScene =
  | 'worldview'
  | 'characters'
  | 'story_outline'
  | 'volume_skeleton'
  | 'volume_detail'
  | 'unit_outline'
  | 'chapter';

export interface KbSourceVolume {
  index: number;
  title: string;
  chapter_start: number;
  chapter_end: number;
}

/** 项目的对标书（一个项目一本） */
export interface KbProjectLink {
  source_id: string;
  source_title: string;
  mode: KbMode;
  /** 本书卷号 → 原书卷号；没写的卷按全书位置自动对齐 */
  volume_map: Record<string, number>;
  source_chapter_count: number;
  source_volumes: KbSourceVolume[];
  dissected_range: [number, number] | null;
}

export interface KbProjectLinkInput {
  source_id: string;
  mode: KbMode;
  volume_map?: Record<string, number>;
}

export interface KbRef {
  key: string;
  entry_id: string;
  entry_type: KbEntryType;
  label: string;
  prompt_label: string;
  reason: string;
}

export interface KbPreviewInput {
  scene: KbScene;
  volume_id?: string;
  unit_index?: number;
  chapter_outline_id?: string;
  kb_chapter?: number;
}

/** 某个场景会注入的仿写参考（text 进 user 提示词，style 进 system） */
export interface KbPreview {
  scene: KbScene;
  mode: KbMode;
  text: string;
  style: string;
  ref_instruction: string;
  refs: KbRef[];
}

export type KbCitationTarget = 'volume' | 'unit' | 'chapter_outline' | 'chapter_candidate';

/** 生成结果的对标引用；条目改版或被删 → stale */
export interface KbCitation {
  entry_id: string;
  source_id: string;
  label: string;
  reason: string;
  scene: string;
  stale: boolean;
}
