/**
 * 拆书参考包类型定义
 *
 * 维度与作者自己的规划链对应：synopsis（全书骨架 ≈ 总纲）/ bridges（剧情单元库 ≈ 卷纲里的一件件事）/ 拆书卡（≈ 章纲）。
 * 后端 schema：@/backend/app/schemas/reference_pack.py
 */

export type ReferencePackStatus = 'generating' | 'ready' | 'partial' | 'failed';

/**
 * 注入维度（与后端 ReferenceDimension Literal 一致，否则挂载请求会 422）
 */
export type ReferenceDimension =
  | 'synopsis' // 全书骨架（梗概 / 全书主线 / 分卷 / 卖点 / 成长路线）
  | 'bridges' // 剧情单元库（单元长短 / 强弱交替 / 兑现方式 + 典型单元；键名沿用 bridges）
  | 'style' // 文风指纹（prompt_content + 量化指标 + 例句）
  | 'character_archive' // 人物功能谱
  | 'methodology' // 写法手册
  | 'structure' // 结构统计（钩子 / 节奏 / 兑现密度 / 张力曲线）
  | 'corpus'; // 拆书卡检索（按本次内容 BM25 命中原书章）

export type ReferenceStrength = 'light' | 'medium' | 'deep';

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
  /** 拆书流水线版本（参考包内容格式） */
  pipeline_version: number;
  error_message: string | null;
  attached_project_count: number;
  created_at: string;
  updated_at: string | null;
}

/**
 * 参考包详情（六个维度正文一次返回）
 *
 * 维度内部为灵活的 dict（形状见下方 *Data）；null 表示该维度未生成（partial 状态下常见）。
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
// 六个维度的"软约束"类型（实际仍为 Record<string, unknown>，
// 此处仅作 IDE 自动补全提示，方便组件渲染时识别字段名）
// 后端产出：skeleton_builder / style_fingerprint / dissect_stats
// ============================================================

/** 原书的一卷（skeleton_builder.build_volumes，对应作者的卷纲） */
export interface SkeletonVolume {
  title?: string;
  summary?: string;
  goal?: string;
  climax?: string;
  ending_hook?: string;
  threads?: string[];
  growth?: string;
  arc_start?: number;
  arc_end?: number;
  chapter_start?: number;
  chapter_end?: number;
  status?: string;
  origin?: 'llm' | 'fallback' | string;
  [k: string]: unknown;
}

/** synopsis：全书骨架（skeleton_builder.build_skeleton，对应作者的总纲） */
export interface SkeletonData {
  genre_tag?: string;
  premise?: string;
  main_plot?: string;
  main_conflict?: string;
  /** 主角的特殊能力 / 核心优势；没有时为「无」 */
  golden_finger?: { what?: string; how_it_works?: string; limits?: string; evolution?: string[]; [k: string]: unknown } | string | null;
  selling_points?: string[];
  main_tropes?: string[];
  growth_route?: string;
  power_system?: string;
  ultimate_goal?: string;
  volumes?: SkeletonVolume[];
  high_points?: Array<{ volume?: string; arcs?: string; setup?: string; trigger?: string; result?: string; [k: string]: unknown }>;
  long_foreshadowing?: Array<{ setup?: string; payoff?: string; role?: string; [k: string]: unknown }>;
  opening_strategy?: string;
  [k: string]: unknown;
}

/** 剧情单元（v5_types.StoryArc；bridges.typical_arcs 与 GET /arcs 同形）：一件完整的事 */
export interface StoryArcData {
  arc_index: number;
  start_chapter: number;
  end_chapter: number;
  title?: string;
  function?: string;
  boundary_reason?: string;
  story?: string;
  structure?: string;
  approach?: string;
  turn?: string;
  emotion_curve?: string;
  payoff?: string;
  payoff_type?: string;
  character_changes?: string;
  gains_costs?: string;
  foreshadowing?: string;
  chapter_roles?: Record<string, string>;
  tension_peak_chapter?: number | null;
  origin?: 'llm' | 'fallback' | string;
  [k: string]: unknown;
}

/** bridges：剧情单元库（dissect_stats.build_units_payload） */
export interface UnitsData {
  arc_count?: number;
  avg_arc_length?: number;
  arc_length_distribution?: Record<string, number>;
  payoff_type_distribution?: Record<string, number>;
  payoff_density?: string;
  typical_arcs?: StoryArcData[];
  role_pattern?: { avg_open_chapters?: number; avg_advance_chapters?: number; turn_position_ratio?: number; [k: string]: unknown };
  /** 单元强弱序列，如「强中弱强」 */
  unit_rhythm?: string;
  /** 强单元后面接缓和的比例（0-1） */
  relief_after_strong?: number;
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
  [k: string]: unknown;
}

/** 导入写作风格库只用到这几项 */
export type StyleData = Pick<StyleFingerprintData, 'name' | 'description' | 'prompt_content' | 'traits'>;

/** character_archive：人物功能谱（skeleton_builder.build_character_functions） */
export interface CharacterFunctionsData {
  protagonist?: {
    name?: string;
    persona?: string;
    /** 核心优势 / 特殊能力；没有时为「无」 */
    advantage?: string;
    flaws_and_pressure?: string;
    growth_track?: Array<{ volume?: string; state?: string }>;
    [k: string]: unknown;
  } | null;
  allies?: Array<{ name?: string; function_role?: string; arc_span?: string; technique?: string; [k: string]: unknown }>;
  antagonists?: Array<{ name?: string; tier?: string; conflict_nature?: string; escalation?: string; outcome?: string; [k: string]: unknown }>;
  function_slots?: Array<{ slot?: string; how_used?: string; [k: string]: unknown }>;
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
  unit_rhythm?: string;
  relief_after_strong?: number;
  hook_examples?: Array<{ chapter?: number; type?: string; text?: string }>;
  [k: string]: unknown;
}

/** 写法手册的一条：模式 + 依据（章号 / 单元编号）+ 给作者的建议 */
export interface MethodologyItem {
  pattern?: string;
  evidence?: string;
  writing_tips?: string;
  [k: string]: unknown;
}

/** methodology：写法手册（skeleton_builder.build_methodology） */
export interface MethodologyData {
  opening_pattern?: MethodologyItem | null;
  volume_rhythm?: MethodologyItem | null;
  unit_design?: MethodologyItem | null;
  tension_rhythm?: MethodologyItem | null;
  growth_progression?: MethodologyItem | null;
  advantage_usage?: MethodologyItem | null;
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

