// 用户类型定义
export interface User {
  user_id: string;
  username: string;
  display_name: string;
  avatar_url?: string;
  trust_level: number;
  is_admin: boolean;
  is_active?: boolean;
  linuxdo_id: string;
  email?: string | null;
  created_at: string;
  last_login: string;
}

// 登录页可用的登录方式（后端返回的是「有效开关」：开关开着且凭据齐全）
export interface AuthConfig {
  local_auth_enabled: boolean;
  linuxdo_login_enabled: boolean;
  linuxdo_register_enabled: boolean;
  email_login_enabled: boolean;
  email_register_enabled: boolean;
}

export type SmtpEncryption = 'ssl' | 'starttls' | 'none';

// 管理员「登录方式设置」视图：秘密字段不回传，只给 *_set
export interface AuthSettingsView {
  linuxdo_login_enabled: boolean;
  linuxdo_register_enabled: boolean;
  linuxdo_client_id: string;
  linuxdo_client_secret_set: boolean;
  linuxdo_redirect_uri: string;
  email_login_enabled: boolean;
  email_register_enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_encryption: SmtpEncryption;
  smtp_username: string;
  smtp_password_set: boolean;
  smtp_from: string;
}

// PUT 部分更新：不传 = 不改；秘密字段传空串 = 清空
export interface AuthSettingsUpdate {
  linuxdo_login_enabled?: boolean;
  linuxdo_register_enabled?: boolean;
  linuxdo_client_id?: string;
  linuxdo_client_secret?: string;
  linuxdo_redirect_uri?: string;
  email_login_enabled?: boolean;
  email_register_enabled?: boolean;
  smtp_host?: string;
  smtp_port?: number;
  smtp_encryption?: SmtpEncryption;
  smtp_username?: string;
  smtp_password?: string;
  smtp_from?: string;
}

// 公告弹窗：显示频率 —— once 内容不改只弹一次 / daily 每天一次 / always 每个浏览器会话一次
export type AnnouncementFrequency = 'once' | 'daily' | 'always';

// 展示字段（登录用户与管理员视图共用）
export interface AnnouncementContent {
  badge: string;
  title: string;
  content: string;
  image_url: string;
  button_text: string;
  link_text: string;
  link_url: string;
}

// GET /announcement：不生效时只有 active=false
export type AnnouncementView =
  | { active: false }
  | (AnnouncementContent & { active: true; revision: string; frequency: AnnouncementFrequency });

// 管理员视图：全部字段 + 当前是否生效
export interface AnnouncementSettingsView extends AnnouncementContent {
  enabled: boolean;
  frequency: AnnouncementFrequency;
  start_at: string | null;
  end_at: string | null;
  active: boolean;
  revision: string;
}

// PUT 部分更新：不传 = 不改；start_at / end_at 传空串 = 清空
export interface AnnouncementUpdate extends Partial<AnnouncementContent> {
  enabled?: boolean;
  frequency?: AnnouncementFrequency;
  start_at?: string;
  end_at?: string;
}

// 思考/推理强度档位（统一档位，同时作为 OpenAI reasoning_effort 的取值）
export type ReasoningEffort = 'none' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';

// 设置类型定义
export interface Settings {
  id: string;
  user_id: string;
  api_provider: string;
  api_key: string;
  api_base_url: string;
  llm_model: string;
  temperature: number;
  max_tokens: number;
  top_p: number;
  frequency_penalty: number;
  presence_penalty: number;
  reasoning_enabled: boolean;
  reasoning_effort: ReasoningEffort;
  thinking_budget_tokens?: number | null;
  preferences?: string;
  created_at: string;
  updated_at: string;
}

export interface SettingsUpdate {
  api_provider?: string;
  api_key?: string;
  api_base_url?: string;
  llm_model?: string;
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  frequency_penalty?: number;
  presence_penalty?: number;
  reasoning_enabled?: boolean;
  reasoning_effort?: ReasoningEffort;
  thinking_budget_tokens?: number | null;
  preferences?: string;
}

/** 模型列表条目（/settings/models 与 /settings/saved-models 同格式） */
export interface AIModelOption {
  value: string;
  label: string;
  description: string;
}

// 项目级 AI 偏好：在全局设置之上按项目覆盖模型与参数（null = 跟随全局）；接口三要素永远取全局
export interface ProjectAIOverrides {
  llm_model: string | null;
  temperature: number | null;
  max_tokens: number | null;
  top_p: number | null;
  frequency_penalty: number | null;
  presence_penalty: number | null;
  reasoning_enabled: boolean | null;
  reasoning_effort: ReasoningEffort | null;
  thinking_budget_tokens: number | null;
}

/** 合并后的实际生效配置（接口信息不含密钥） */
export interface EffectiveAIConfig extends ProjectAIOverrides {
  api_provider: string | null;
  api_base_url: string | null;
}

export interface ProjectAIPreference {
  project_id: string;
  overrides: ProjectAIOverrides;
  effective: EffectiveAIConfig;
  global_defaults: EffectiveAIConfig;
}

/** 桥段 C3 兑现章末尾：none 不留钩子（默认，付费文）/ soft 收束 + 半钩（免费平台章末钩子） */
export type C3HookStyle = 'none' | 'soft';

// 项目类型定义
export interface Project {
  id: string;  // UUID字符串
  title: string;
  description?: string;
  theme?: string;
  genre?: string;
  target_words?: number;
  generation_prompt?: string;
  current_words: number;
  status: 'planning' | 'writing' | 'revising' | 'completed';
  wizard_status?: 'incomplete' | 'completed';
  wizard_step?: number;
  world_time_period?: string;
  world_location?: string;
  world_atmosphere?: string;
  world_rules?: string;
  chapter_count?: number;
  narrative_perspective?: string;
  character_count?: number;
  c3_hook_style?: C3HookStyle | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreate {
  title: string;
  description?: string;
  theme?: string;
  genre?: string;
  target_words?: number;
  generation_prompt?: string;
  narrative_perspective?: string;
  chapter_count?: number;
  character_count?: number;
  wizard_status?: 'incomplete' | 'completed';
  wizard_step?: number;
  world_time_period?: string;
  world_location?: string;
  world_atmosphere?: string;
  world_rules?: string;
}

export interface ProjectUpdate {
  title?: string;
  description?: string;
  theme?: string;
  genre?: string;
  target_words?: number;
  generation_prompt?: string;
  status?: 'planning' | 'writing' | 'revising' | 'completed';
  world_time_period?: string;
  world_location?: string;
  world_atmosphere?: string;
  world_rules?: string;
  chapter_count?: number;
  narrative_perspective?: string;
  character_count?: number;
  c3_hook_style?: C3HookStyle;
  // current_words 由章节内容自动计算，不在此接口中
}

export interface WorldBuildingResponse {
  project_id: string;
  time_period: string;
  location: string;
  atmosphere: string;
  rules: string;
}

// 大纲类型定义
export interface Outline {
  id: string;
  project_id: string;
  title: string;
  content: string; // 故事前提（premise）
  version?: number;
  status?: string;
  editor_id?: string;
  is_active?: boolean;
  order_index: number;
  created_at: string;
  updated_at: string;
}

export interface OutlineCreate {
  project_id: string;
  title: string;
  content: string; // 故事前提（premise）
  order_index: number;
}

export interface OutlineUpdate {
  title?: string;
  content?: string; // 故事前提（premise）
  status?: string;
  version?: number; // 用于乐观锁
}

// 角色类型定义
export interface Character {
  id: string;
  project_id: string;
  name: string;
  age?: string;
  gender?: string;
  is_organization: boolean;
  role_type?: string;
  personality?: string;
  background?: string;
  appearance?: string;
  relationships?: string;
  organization_type?: string;
  organization_purpose?: string;
  organization_members?: string;
  traits?: string;
  avatar_url?: string;
  // 组织扩展字段（从Organization表关联）
  power_level?: number;
  location?: string;
  motto?: string;
  color?: string;
  // 组织在籍成员名：后端按成员关系表读时派生（无关系记录时回退到 organization_members 快照）
  member_names?: string[];
  created_at: string;
  updated_at: string;
}

export interface CharacterUpdate {
  name?: string;
  age?: string;
  gender?: string;
  is_organization?: boolean;
  role_type?: string;
  personality?: string;
  background?: string;
  appearance?: string;
  relationships?: string;
  organization_type?: string;
  organization_purpose?: string;
  organization_members?: string;
  traits?: string;
  // 组织扩展字段
  power_level?: number;
  location?: string;
  motto?: string;
  color?: string;
}

// 章节类型定义
export interface Chapter {
  id: string;
  project_id: string;
  chapter_outline_id?: string;
  title: string;
  content?: string;
  summary?: string;
  chapter_number: number;
  word_count: number;
  status: 'draft' | 'writing' | 'completed';
  created_at: string;
  updated_at: string;
}

export interface ChapterCreate {
  project_id: string;
  chapter_outline_id?: string;
  title: string;
  chapter_number: number;
  content?: string;
  summary?: string;
  status?: 'draft' | 'writing' | 'completed';
}

export interface ChapterUpdate {
  title?: string;
  content?: string;
  // chapter_number 不允许修改，由大纲顺序决定
  summary?: string;
  // word_count 自动计算，不允许手动修改
  status?: 'draft' | 'writing' | 'completed';
}

// 章节生成请求类型
export interface ChapterGenerateRequest {
  style_id?: number;
  target_word_count?: number;
  enable_mcp?: boolean;
  auto_analyze?: boolean;
  selected_plugins?: string[];
  // R8 拆书参考包显式参数（任一为空则走默认）
  pack_ids?: string[];
  dimensions?: string[];
  strength?: 'light' | 'medium' | 'deep';
}

// 章节生成检查响应
export interface ChapterCanGenerateResponse {
  can_generate: boolean;
  reason: string;
  previous_chapters: {
    id: string;
    chapter_number: number;
    title: string;
    has_content: boolean;
    word_count: number;
  }[];
  chapter_number: number;
}

export interface GenerateCharacterRequest {
  project_id: string;
  name?: string;
  role_type?: string;
  background?: string;
  requirements?: string;
  provider?: string;
  model?: string;
  enable_mcp?: boolean;
  selected_plugins?: string[];
  // R8 拆书参考包显式参数（任一为空则走默认）
  pack_ids?: string[];
  dimensions?: string[];
  strength?: 'light' | 'medium' | 'deep';
}

// 向导API响应类型
export interface GenerateCharactersResponse {
  message?: string;
  count?: number;
  batches?: number;
  characters: Character[];
}

export interface GenerateOutlineResponse {
  message?: string;
  outline?: Outline;
  outlines?: Outline[];
  total_chapters?: number;
}

/** 向导步骤 4：剧情线生成请求（POST /api/wizard-stream/plot-lines） */
export interface WizardPlotLinesRequest {
  project_id: string;
  chapter_count: number;
  sub_line_count?: number;
  requirements?: string;
  enable_mcp?: boolean;
  selected_plugins?: string[];
  pack_ids?: string[];
  dimensions?: string[];
  strength?: 'light' | 'medium' | 'deep';
}

/** 向导步骤 4：剧情线生成结果 */
export interface WizardPlotLinesResponse {
  message: string;
  main_line: { id: string; title: string; estimated_chapters: number; beat_count: number };
  sub_lines: Array<{ id: string; title: string }>;
  plan_preview: { total_bridges: number; total_chapters: number };
}

// 写作风格类型定义
export interface WritingStyle {
  id: number;
  project_id: string;
  name: string;
  style_type: 'preset' | 'custom';
  preset_id?: string;
  description?: string;
  prompt_content: string;
  is_default: boolean;
  order_index: number;
  created_at: string;
  updated_at: string;
}

export interface WritingStyleCreate {
  project_id: string;
  name: string;
  style_type: 'preset' | 'custom';
  preset_id?: string;
  description?: string;
  prompt_content: string;
  is_default?: boolean;
}

export interface WritingStyleUpdate {
  name?: string;
  description?: string;
  prompt_content?: string;
  order_index?: number;
}

export interface PresetStyle {
  id: string;
  name: string;
  description: string;
  prompt_content: string;
}

export interface WritingStyleListResponse {
  styles: WritingStyle[];
  total: number;
}

export interface PaginationResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// API 错误响应类型
export interface ApiError {
  response?: {
    data?: {
      detail?: string;
    };
  };
  message?: string;
}

// 分析结果 - 钩子
interface AnalysisHook {
  type: string;
  content: string;
  strength: number;
  position: string;
}

// 分析结果 - 伏笔
interface AnalysisForeshadow {
  content: string;
  type: 'planted' | 'resolved';
  strength: number;
  subtlety: number;
  reference_chapter?: number;
}

// 分析结果 - 角色状态
interface AnalysisCharacterState {
  character_name: string;
  state_before: string;
  state_after: string;
  psychological_change: string;
  key_event: string;
  relationship_changes: Record<string, string>;
}

// 分析结果 - 情节点
interface AnalysisPlotPoint {
  content: string;
  type: 'revelation' | 'conflict' | 'resolution' | 'transition';
  importance: number;
  impact: string;
}

// 分析结果 - 场景
interface AnalysisScene {
  location: string;
  atmosphere: string;
  duration: string;
}

// 完整分析数据 - 匹配后端PlotAnalysis模型
export interface AnalysisData {
  id: string;
  chapter_id: string;
  plot_stage: string;
  conflict_level: number;
  conflict_types: string[];
  emotional_tone: string;
  emotional_intensity: number;
  hooks: AnalysisHook[];
  hooks_count: number;
  foreshadows: AnalysisForeshadow[];
  foreshadows_planted: number;
  foreshadows_resolved: number;
  plot_points: AnalysisPlotPoint[];
  plot_points_count: number;
  character_states: AnalysisCharacterState[];
  scenes?: AnalysisScene[];
  pacing: string;
  overall_quality_score: number;
  pacing_score: number;
  engagement_score: number;
  coherence_score: number;
  analysis_report: string;
  suggestions: string[];
  dialogue_ratio: number;
  description_ratio: number;
  created_at: string;
}

// 记忆片段
export interface StoryMemory {
  id: string;
  type: 'hook' | 'foreshadow' | 'plot_point' | 'character_event';
  title: string;
  content: string;
  importance: number;
  tags: string[];
  is_foreshadow: 0 | 1 | 2; // 0=普通, 1=已埋下, 2=已回收
}

// 章节分析结果响应 - 匹配后端API返回
export interface ChapterAnalysisResponse {
  chapter_id: string;
  analysis: AnalysisData;  // 注意：后端返回的是analysis而不是analysis_data
  memories: StoryMemory[];
  narrative_state?: ChapterNarrativeState;
  consistency_audit?: ConsistencyAuditView;
  created_at: string;
}

interface ChapterCausalLinkView {
  cause: string;
  event: string;
  effect: string;
  decision: string;
  importance: number;
  reversible: boolean;
  actor_names: string[];
  target_names: string[];
  evidence?: string | null;
}

interface NarrativePromiseView {
  id: string;
  promise_type: 'foreshadow' | 'promise' | 'mystery' | 'conflict' | string;
  title: string;
  content: string;
  priority: 'low' | 'medium' | 'high' | 'critical' | string;
  status: 'open' | 'progressing' | 'resolved' | 'broken' | string;
  source_chapter_number?: number | null;
  resolved_chapter_number?: number | null;
  deadline_chapter?: number | null;
  owner_character_name?: string | null;
  target_character_name?: string | null;
  resolution_note?: string | null;
}

interface TimelineEventView {
  id: string;
  event_type: string;
  title: string;
  description: string;
  location?: string | null;
  time_marker?: string | null;
  actor_names: string[];
  target_names: string[];
  public_visibility?: 'public' | 'private' | 'secret' | string;
}

interface RelationshipGraphNode {
  id: string;
  label: string;
}

interface RelationshipGraphEdge {
  source: string;
  target: string;
  delta: number;
  reason?: string | null;
  new_status?: string | null;
  intimacy_level?: number | null;
}

interface RelationshipGraphView {
  nodes: RelationshipGraphNode[];
  edges: RelationshipGraphEdge[];
}

interface ConsistencyAuditIssue {
  severity: 'critical' | 'high' | 'medium' | 'low' | string;
  issue_type: string;
  rule_code: string;
  title: string;
  details: string;
  evidence?: string | null;
  character_name?: string | null;
  signal_key?: string | null;
  reference_chapter_number?: number | null;
}

interface ConsistencyAuditSummary {
  total: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface ConsistencyAuditView {
  summary: ConsistencyAuditSummary;
  issues: ConsistencyAuditIssue[];
}

export interface ChapterNarrativeState {
  causal_links: ChapterCausalLinkView[];
  promises: NarrativePromiseView[];
  timeline_events: TimelineEventView[];
  relationship_graph: RelationshipGraphView;
}

// MCP 插件类型定义 - 优化后只包含必要字段
export interface MCPPlugin {
  id: string;
  plugin_name: string;
  display_name: string;
  description?: string;
  plugin_type: 'http' | 'stdio';
  category: string;
  
  // HTTP类型字段
  server_url?: string;
  headers?: Record<string, string>;
  transport?: 'streamable_http' | 'sse' | null;
  
  // Stdio类型字段
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  
  // 状态字段
  enabled: boolean;
  status: 'active' | 'inactive' | 'error';
  last_error?: string;
  last_test_at?: string;
  
  // 时间戳
  created_at: string;
}

export interface MCPPluginCreate {
  plugin_name: string;
  display_name?: string;
  description?: string;
  plugin_type: 'http' | 'stdio';
  server_url?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  headers?: Record<string, string>;
  enabled?: boolean;
}

export interface MCPPluginUpdate {
  display_name?: string;
  description?: string;
  server_url?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  headers?: Record<string, string>;
  enabled?: boolean;
}

export interface MCPTool {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

export interface MCPTestResult {
  success: boolean;
  message: string;
  tools?: MCPTool[];
  tools_count?: number;
  response_time_ms?: number;
  error?: string;
  error_type?: string;
  suggestions?: string[];
}

// MCP 商城（内置精选目录 + 一键安装）
export interface MCPMarketplaceInput {
  key: string;
  label: string;
  required: boolean;
  secret: boolean;
  placeholder?: string | null;
  help_url?: string | null;
  /** 链接文案，缺省「获取 Key」 */
  help_label?: string | null;
  help_text?: string | null;
}

export interface MCPMarketplaceItem {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  transport: 'streamable_http' | 'sse';
  server_url: string;
  inputs: MCPMarketplaceInput[];
  homepage: string;
  official: boolean;
  region: 'cn' | 'global';
  pricing: string;
  notes?: string | null;
  recommended: boolean;
  verified_at?: string | null;
  installed_plugin_id?: string | null;
  installed_status?: 'active' | 'inactive' | 'error' | null;
}

export interface MCPMarketplaceCategory {
  id: string;
  label: string;
}

export interface MCPMarketplaceListResponse {
  categories: MCPMarketplaceCategory[];
  items: MCPMarketplaceItem[];
}

export interface MCPMarketplaceInstallRequest {
  inputs?: Record<string, string>;
  enabled?: boolean;
}

// 剧情卡片类型定义
export interface PlotCard {
  id: string;
  project_id: string;
  outline_id?: string;
  chapter_outline_id?: string;
  title: string;
  content?: string;
  card_type: string;
  order_index?: number;
  tags?: string[];
  created_at: string;
  updated_at: string;
  // 关联字段（从API返回时可能包含）
  plot_lines?: PlotLine[];
  chapter_outlines?: ChapterOutline[];
  // 统计字段
  plot_line_count?: number;
  chapter_outline_count?: number;
}

export interface PlotCardCreate {
  project_id: string;
  outline_id?: string;
  chapter_outline_id?: string;
  title: string;
  content?: string;
  card_type: string;
  order_index?: number;
  tags?: string[];
}

export interface PlotCardUpdate {
  title?: string;
  content?: string;
  card_type?: string;
  order_index?: number;
  tags?: string[];
  chapter_outline_id?: string;
}

export interface PlotCardGenerateRequest {
  project_id: string;
  outline_id?: string;
  chapter_outline_id?: string;
  prompt?: string;
  card_type: string;
  count: number;
  extend_from_card_id?: string;
  enable_mcp?: boolean;
  selected_plugins?: string[];
}

export interface PlotCardReorderRequest {
  orders: Array<{
    id: string;
    order_index: number;
  }>;
}

export interface PlotCardListResponse {
  total: number;
  items: PlotCard[];
}

// 剧情线类型定义
export interface PlotLine {
  id: string;
  project_id: string;
  outline_id?: string;
  title: string;
  description?: string;
  line_type: string;
  order_index?: number;
  plot_cards?: string[];
  timeline_data?: TimelineData;
  estimated_chapters?: number;  // 预计章节数
  created_at: string;
  updated_at: string;
  // 关联字段（从API返回时可能包含）
  chapter_outlines?: ChapterOutline[];
  // 统计字段
  chapter_outline_count?: number;
  plot_card_count?: number;
}

export interface PlotLineCreate {
  project_id: string;
  outline_id?: string;
  title: string;
  description?: string;
  line_type: string;
  order_index?: number;
  plot_cards?: string[];
  timeline_data?: TimelineData;
  estimated_chapters?: number;  // 预计章节数
}

export interface PlotLineUpdate {
  title?: string;
  description?: string;
  line_type?: string;
  order_index?: number;
  plot_cards?: string[];
  timeline_data?: TimelineData;
  estimated_chapters?: number;  // 预计章节数
}

export interface PlotLineGenerateRequest {
  project_id: string;
  story_outline_id?: string;
  prompt?: string;
  line_type: string;
  based_on_cards?: string[];
  based_on_lines?: string[];
  extend_existing: boolean;
  count: number;
  enable_mcp?: boolean;
  selected_plugins?: string[];
}

export interface PlotLineReorderRequest {
  orders: Array<{
    id: string;
    order_index: number;
  }>;
}

export interface PlotLineListResponse {
  total: number;
  items: PlotLine[];
}

// 剧情线进度相关类型定义
export interface PlotLineBeatProgress {
  index: number;
  key?: string;
  title: string;
  description?: string;
  weight: number;
  coverage: number;
  status: 'completed' | 'in_progress' | 'not_started';
}

export interface PlotLineProgress {
  plot_line_id: string;
  plot_line_title: string;
  has_beats: boolean;
  total_progress: number | null;
  beats: PlotLineBeatProgress[];
  linked_chapters_count: number;
  message?: string;
}

// 时间线相关类型定义
export interface TimelineBeat {
  index: number;
  key: string;
  title: string;
  description?: string;
  weight: number;
}

export interface TimelineData {
  beats: TimelineBeat[];
}

// 节点覆盖度相关类型定义
export interface BeatCoverage {
  beat_index: number;
  coverage: number;  // 本章对该节点的贡献度(0-1,表示0%-100%)
}

// 章纲类型定义
// 章纲类型定义 - 专业网文版
export interface ChapterOutline {
  id: string;
  project_id: string;
  plot_line_id?: string;
  chapter_number: number;
  title: string;
  // 场景信息（新增）
  scene?: string;                // 场景地点，如"拳击场→后台"
  pov?: string;                  // 视角角色名
  // 剧情信息
  plot_points?: string;          // 剧情要点（含情感变化）
  key_events?: string[];         // 关键事件，最后一条为章末钩子
  characters_involved?: string[];
  // 旧字段（保留兼容）
  summary?: string;              // 已废弃，保留兼容旧数据
  // 系统字段
  target_word_count: number;
  order_index?: number;
  created_at: string;
  updated_at: string;
  // 关联字段（从API返回时可能包含）
  plot_lines?: PlotLine[];
  plot_cards?: PlotCard[];
  // 统计字段
  plot_line_count?: number;
  plot_card_count?: number;
}

export interface ChapterOutlineCreate {
  project_id: string;
  plot_line_id?: string;
  chapter_number: number;
  title: string;
  // 场景信息（新增）
  scene?: string;
  pov?: string;
  // 剧情信息
  plot_points?: string;
  key_events?: string[];
  characters_involved?: string[];
  // 旧字段（保留兼容）
  summary?: string;
  // 系统字段
  target_word_count: number;
  order_index?: number;
}

export interface ChapterOutlineUpdate {
  chapter_number?: number;
  title?: string;
  // 场景信息（新增）
  scene?: string;
  pov?: string;
  // 剧情信息
  plot_points?: string;
  key_events?: string[];
  characters_involved?: string[];
  // 旧字段（保留兼容）
  summary?: string;
  // 系统字段
  target_word_count?: number;
  order_index?: number;
}

export interface ChapterOutlineReorderRequest {
  orders: Array<{
    id: string;
    order_index: number;
    chapter_number: number;
  }>;
}

export interface ChapterOutlineListResponse {
  total: number;
  items: ChapterOutline[];
}

export interface ChapterOutlineBatchCreateRequest {
  project_id: string;
  plot_line_id?: string;
  outlines: ChapterOutlineCreate[];
}

// ============================================
// 关联关系类型定义
// ============================================

// 章纲-剧情线关联

// 剧情卡片-剧情线关联

// 剧情卡片-章纲关联

// 扩展响应类型（包含关联信息）
export interface PlotLineWithLinks {
  id: string;
  title: string;
  description?: string;
  line_type: string;
  chapter_count: number;
  card_count: number;
  link_id?: string;  // 章纲-剧情线关联ID（用于更新覆盖度）
  timeline_data?: TimelineData;  // 时间线数据
  timeline_coverage?: {  // 节点覆盖度数据
    beats_covered: BeatCoverage[];
  };
}

export interface PlotCardWithLinks {
  id: string;
  title: string;
  content?: string;
  card_type: string;
  plot_line_count: number;
  chapter_count: number;
}

// 关联管理请求类型

// 世界规则系统类型定义
export interface WorldRule {
  id: string;
  project_id: string;
  category: 'cultivation_realm' | 'equipment_template' | 'map_location';
  key: string;
  name: string;
  order_index: number;
  summary?: string;
  details?: string;
  created_at: string;
  updated_at: string;
}

export interface WorldRuleCreate {
  category: 'cultivation_realm' | 'equipment_template' | 'map_location';
  key: string;
  name: string;
  order_index: number;
  summary?: string;
  details?: string;
}

export interface WorldRuleUpdate {
  category?: 'cultivation_realm' | 'equipment_template' | 'map_location';
  key?: string;
  name?: string;
  order_index?: number;
  summary?: string;
  details?: string;
}

export interface WorldRuleListResponse {
  total: number;
  items: WorldRule[];
}

// ============================================
// 场景生成相关类型定义（场景级创作循环）
// ============================================

// 创建会话请求

// 会话响应

// 会话状态响应

// 剧情卡片状态（场景生成用）

// 生成场景请求

// 反馈请求

// 重生成请求

// 完成会话响应

// SSE 流式响应数据

// ============================================
// 拆书参考（Book Dissect）
// ============================================

export interface BookDissectChapterMeta {
  number: number;
  title: string;
  raw_title: string;
  word_count: number;
  kind: 'chapter' | 'special' | 'english' | 'preamble';
}

// V1 采样式 schema（DissectResult / DissectProjectSchema 等）已随 V1 逻辑一并移除。

export type BookDissectStatus = 'pending' | 'running' | 'completed' | 'failed';
export type BookDissectStage =
  | 'split_done'
  | 'queued'
  | 'splitting'
  | 'scanning'
  | 'dictionary'
  | 'extracting'
  | 'aggregating'
  | 'synthesizing'
  | 'done'
  | string;

export interface BookDissectTask {
  id: string;
  user_id: string;
  status: BookDissectStatus;
  progress: number;
  stage?: BookDissectStage | null;
  error_message?: string | null;
  file_name?: string | null;
  file_size: number;
  encoding?: string | null;
  chapter_count: number;
  total_words: number;
  chapters_meta?: BookDissectChapterMeta[] | null;
  // V2 字段
  version?: number;
  extraction_phase?: string | null;
  chapters_total?: number;
  chapters_extracted?: number;
  chapters_failed?: number;
  sampling_mode?: string;
  sampling_param?: number;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface BookDissectUploadResponse {
  task_id: string;
  file_name: string;
  file_size: number;
  encoding: string;
  chapter_count: number;
  total_words: number;
  preview: BookDissectChapterMeta[];
}

// V3 R6 废弃：BookDissectApplyField / BookDissectApplyRequest / BookDissectApplyResponse 已移除。
// 后端 POST /api/book-dissect/{task_id}/apply-to-wizard 现返 410 Gone；
// 请改用参考包挂载 + 一键仿写路径，详见 @/frontend/src/components/ImitationDialog.tsx。

// ============================================================
// 拆书 V2 浏览类型
// ============================================================

export interface BookDissectV2Overview {
  task_id: string;
  version: number;
  extraction_phase: string | null;
  chapters_total: number;
  chapters_extracted: number;
  chapters_failed: number;
  sampling_mode: string;
  sampling_param: number;
  stats: Record<string, unknown>;
  synopsis: Record<string, unknown> | null;
}

export interface BookDissectV2ChapterSummary {
  id: string;
  chapter_number: number;
  chapter_title: string | null;
  summary: string | null;
  extraction_status: string;
  extraction_error: string | null;
}

export interface BookDissectV2ChapterDetail extends BookDissectV2ChapterSummary {
  fact: Record<string, unknown> | null;
  is_truncated: boolean;
  segment_count: number;
}

export interface BookDissectV2DictionaryEntry {
  id: string;
  name: string;
  entity_type: string;
  aliases: string[];
  frequency: number;
  confidence: string;
  sample_context: string | null;
  source: string | null;
}

export interface BookDissectV2Entity {
  id: string;
  canonical_name: string;
  entity_type: string;
  aliases: string[];
  profile: Record<string, unknown>;
  first_chapter: number | null;
  last_chapter: number | null;
  appearance_count: number;
  role_type: string | null;
  parent_entity_id: string | null;
}

export interface BookDissectV2Relation {
  id: string;
  entity_a_id: string;
  entity_b_id: string;
  relation_type: string;
  relation_category: string | null;
  occurrence_count: number;
  first_chapter: number | null;
  evidence: Array<{ chapter: number; text: string }>;
}

export interface BookDissectV2Event {
  id: string;
  chapter_number: number;
  event_type: string;
  title: string;
  description: string | null;
  actors: string[];
  location: string | null;
  importance: string;
  evidence: string | null;
}
