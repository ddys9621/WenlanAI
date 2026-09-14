/**
 * 拆书参考包类型定义（V5）
 *
 * 参见：@/agent-docs/features/book_dissect_v5_design.md §5-§6
 * 后端 schema：@/backend/app/schemas/reference_pack.py
 */

export type ReferencePackStatus = 'generating' | 'ready' | 'partial' | 'failed';

/**
 * 注入维度（与后端 ReferenceDimension Literal 一致，否则挂载请求会 422）
 */
export type ReferenceDimension =
  | 'synopsis' // 全书骨架（类型 / 前提 / 大矛盾 / 金手指 / 阶段 / 爽点）
  | 'bridges' // 桥段库（情节单元聚合 + 典型单元）
  | 'style' // 文风指纹（prompt_content + 量化指标 + 例句）
  | 'character_archive' // 人物功能谱
  | 'methodology' // 写法手册
  | 'structure' // 结构统计（钩子 / 节奏 / 爽点密度 / 张力曲线）
  | 'corpus'; // 拆书卡检索（按本次内容 BM25 命中原书章）

export type ReferenceStrength = 'light' | 'medium' | 'deep';

/** V5 流水线版本号；小于此值的参考包为 V2-V4 老包（只读，建议重新抽取） */
export const V5_PIPELINE_VERSION = 5;

export function isV5Pack(pack: { pipeline_version?: number | null } | null | undefined): boolean {
  return (pack?.pipeline_version ?? 2) >= V5_PIPELINE_VERSION;
}

/**
 * 参考包列表项（不含维度正文）
 */
export interface ReferencePackSummary {
  id: string;
  user_id: string;
  task_id: string;
  source_book_title: string;
  status: ReferencePackStatus;
  generated_dimensions: string[];
  /** 2 = V2-V4 老包；5 = V5 */
  pipeline_version: number;
  error_message: string | null;
  attached_project_count: number;
  created_at: string;
  updated_at: string | null;
}

/**
 * 参考包详情（六个维度正文一次返回）
 *
 * 维度内部为灵活的 dict；null 表示该维度未生成（partial 状态下常见）。
 * pipeline_version >= 5 时六个字段是下方 *Data 形状；老包同名字段是 V2-V4 形状，前端只读 JSON 展示。
 */
export interface ReferencePackDetail extends ReferencePackSummary {
  synopsis: Record<string, unknown> | null;
  bridges: Record<string, unknown> | null;
  style: Record<string, unknown> | null;
  character_archive: Record<string, unknown> | null;
  methodology: Record<string, unknown> | null;
  structure: Record<string, unknown> | null;
}

/**
 * 项目已挂载参考包列表项
 */
export interface ProjectReferencePackItem {
  id: string; // 关联表主键
  project_id: string;
  pack_id: string;
  pack_summary: ReferencePackSummary;
  default_dimensions: ReferenceDimension[];
  default_strength: ReferenceStrength;
  attached_at: string;
}

/**
 * 挂载参考包请求 body
 */
export interface AttachReferencePackRequest {
  pack_id: string;
  default_dimensions?: ReferenceDimension[];
  default_strength?: ReferenceStrength;
}

export interface UpdateAttachmentRequest {
  default_dimensions?: ReferenceDimension[];
  default_strength?: ReferenceStrength;
}

export interface AttachReferencePackResponse {
  attachment_id: string;
  project_id: string;
  pack_id: string;
  default_dimensions: ReferenceDimension[];
  default_strength: ReferenceStrength;
}

// ============================================================
// V5 六个维度的"软约束"类型（实际仍为 Record<string, unknown>，
// 此处仅作 IDE 自动补全提示，方便组件渲染时识别字段名）
// 后端产出：skeleton_builder / style_fingerprint / dissect_stats
// ============================================================

/** 全书骨架里的一个阶段（skeleton_builder.build_stages） */
export interface SkeletonStage {
  title?: string;
  core_conflict?: string;
  protagonist_goal?: string;
  key_upgrades?: string;
  signature_arc?: string;
  ending_hook?: string;
  arc_start?: number;
  arc_end?: number;
  chapter_start?: number;
  chapter_end?: number;
  status?: string;
  origin?: 'llm' | 'fallback' | string;
  [k: string]: unknown;
}

/** synopsis：全书骨架（skeleton_builder.build_skeleton） */
export interface SkeletonData {
  genre_tag?: string;
  one_line_premise?: string;
  main_conflict?: string;
  golden_finger?: { what?: string; how_it_works?: string; evolution?: string[]; [k: string]: unknown } | string | null;
  stages?: SkeletonStage[];
  top_payoffs?: Array<{ stage?: string; arcs?: string; buildup?: string; trigger?: string; reward?: string; [k: string]: unknown }>;
  growth_system?: string;
  power_system?: string;
  long_foreshadowing?: Array<{ setup?: string; payoff?: string; role?: string; [k: string]: unknown }>;
  reading_promise?: string;
  opening_strategy?: string;
  pipeline_version?: number;
  [k: string]: unknown;
}

/** 情节单元（v5_types.StoryArc；bridges.typical_arcs 与 GET /arcs 同形） */
export interface StoryArcData {
  arc_index: number;
  start_chapter: number;
  end_chapter: number;
  title?: string;
  function?: string;
  boundary_reason?: string;
  structure?: string;
  protagonist_chain?: string;
  emotion_curve?: string;
  payoff?: string;
  payoff_type?: string;
  golden_finger_usage?: string;
  character_changes?: string;
  gains_costs?: string;
  foreshadowing?: string;
  chapter_roles?: Record<string, string>;
  tension_peak_chapter?: number | null;
  origin?: 'llm' | 'fallback' | string;
  [k: string]: unknown;
}

/** bridges：桥段库聚合（dissect_stats.build_bridges_payload） */
export interface BridgesV5Data {
  pipeline_version?: number;
  arc_count?: number;
  avg_arc_length?: number;
  arc_length_distribution?: Record<string, number>;
  payoff_type_distribution?: Record<string, number>;
  payoff_density?: string;
  typical_arcs?: StoryArcData[];
  role_pattern?: { avg_intro_chapters?: number; avg_build_chapters?: number; payoff_position_ratio?: number; [k: string]: unknown };
  [k: string]: unknown;
}

/** style：文风指纹（style_fingerprint.StyleFingerprintBuilder.build） */
export interface StyleFingerprintData {
  name?: string;
  description?: string;
  prompt_content?: string;
  traits?: string[];
  dialogue_style?: string;
  narration_habits?: string;
  avoid_list?: string[];
  /** style_stats.compute_style_metrics 的量化指标 */
  metrics?: Record<string, unknown>;
  examples?: Array<{ kind?: string; chapter?: number; text?: string }>;
  pipeline_version?: number;
  [k: string]: unknown;
}

/** 老包 / 通用文风字段（导入写作风格库只用到这几项） */
export type StyleData = Pick<StyleFingerprintData, 'name' | 'description' | 'prompt_content' | 'traits'>;

/** character_archive：人物功能谱（skeleton_builder.build_character_functions） */
export interface CharacterFunctionsData {
  protagonist?: {
    name?: string;
    persona?: string;
    golden_finger?: string;
    flaws_and_pressure?: string;
    growth_track?: Array<{ stage?: string; state?: string }>;
    [k: string]: unknown;
  } | null;
  allies?: Array<{ name?: string; function_role?: string; arc_span?: string; technique?: string; [k: string]: unknown }>;
  antagonists?: Array<{ name?: string; tier?: string; conflict_nature?: string; escalation?: string; outcome?: string; [k: string]: unknown }>;
  function_slots?: Array<{ slot?: string; how_used?: string; [k: string]: unknown }>;
  pipeline_version?: number;
  [k: string]: unknown;
}

/** structure：结构统计（dissect_stats.build_structure_stats） */
export interface StructureStatsData {
  chapter_count?: number;
  avg_chapter_words?: number;
  pace_distribution?: Record<string, number>;
  tension_by_decile?: number[];
  hook_type_distribution?: Record<string, number>;
  hook_rate?: number;
  payoff_chapter_rate?: number;
  payoff_density_chapters?: number;
  function_tag_distribution?: Record<string, number>;
  function_tags_by_decile?: string[][];
  arc_count?: number;
  avg_arc_length?: number;
  arc_length_distribution?: Record<string, number>;
  payoff_type_distribution?: Record<string, number>;
  hook_examples?: Array<{ chapter?: number; type?: string; text?: string }>;
  [k: string]: unknown;
}

/** methodology：写法手册（V3 五键形状未变） */
export interface MethodologyData {
  golden_finger_pattern?: {
    type?: string;
    balance_mechanism?: string;
    evolution_pattern?: string;
    writing_tips?: string;
    [k: string]: unknown;
  } | null;
  opening_hook_pattern?: {
    hook_type?: string;
    first_chapter_strategy?: string;
    writing_tips?: string;
    [k: string]: unknown;
  } | null;
  facepunch_rhythm?: {
    small_facepunch_freq?: string;
    big_facepunch_freq?: string;
    three_elements_pattern?: string;
    writing_tips?: string;
    [k: string]: unknown;
  } | null;
  power_progression?: {
    system_type?: string;
    level_count?: number;
    pace?: string;
    writing_tips?: string;
    [k: string]: unknown;
  } | null;
  highlight_density?: {
    small_per_n_chapters?: number;
    medium_per_n_chapters?: number;
    big_per_n_chapters?: number;
    writing_tips?: string;
    [k: string]: unknown;
  } | null;
}

// ============================================================
// 一键仿写（V3 R5）
// 后端 schema：@/backend/app/schemas/imitation.py
// ============================================================

/**
 * 一键仿写请求体
 *
 * pack_ids / dimensions / strength 全部可省略：
 * - 省略 pack_ids → 使用项目所有已挂载且 ready 的参考包
 * - 省略 dimensions → 取所选 pack 挂载关联的 default_dimensions 并集
 * - 省略 strength → 取所选 pack 中"最深"者
 */
export interface ImitateChapterRequest {
  user_intent: string;
  target_chapter_id?: string;
  pack_ids?: string[];
  dimensions?: ReferenceDimension[];
  strength?: ReferenceStrength;
  target_word_count?: number;
  style_id?: number;
}

export interface ImitationPackUsage {
  pack_id: string;
  source_book_title: string;
  dimensions: string[];
}

export interface ImitatePromptPreview {
  system_prompt: string;
  user_prompt: string;
  used_packs: ImitationPackUsage[];
  used_dimensions: string[];
  strength: ReferenceStrength;
  target_word_count: number;
  project_context_chars: number;
  reference_chars: number;
  extras?: Record<string, unknown>;
}

/** SSE 流式事件载荷（meta 事件） */

