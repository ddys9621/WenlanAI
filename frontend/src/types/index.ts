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

// 管理员操作记录（用户管理页「操作记录」卡；detail 不含密码）
export interface AdminAuditLog {
  id: string;
  actor_id: string;
  actor_name: string | null;
  action: string;
  target_id: string | null;
  target_name: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
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
  /** 采样多样性开关：关闭后不传 top_p / 频率惩罚 / 存在惩罚（模型不支持这些参数时关闭） */
  sampling_enabled?: boolean;
  reasoning_enabled: boolean;
  reasoning_effort: ReasoningEffort;
  thinking_budget_tokens?: number | null;
  /** 分析 / 实体抽取 / 剧情摘要专用模型（同一接口下的便宜快模型）；空 = 跟随主模型 */
  analysis_model?: string | null;
  /** 编辑器行内补全专用模型（同一接口下响应快的模型）；空 = 跟随项目模型 */
  completion_model?: string | null;
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
  sampling_enabled?: boolean;
  reasoning_enabled?: boolean;
  reasoning_effort?: ReasoningEffort;
  thinking_budget_tokens?: number | null;
  analysis_model?: string | null;
  completion_model?: string | null;
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
  /** 本项目的采样多样性开关（项目单独换了不支持 top_p / 惩罚参数的模型时关闭） */
  sampling_enabled: boolean | null;
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

/** 平台预设：决定单章字数默认值、章末钩子默认值与正文写法提示 */
export type PlatformPreset = 'qidian' | 'fanqie' | 'jinjiang' | 'qimao';

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
  platform_preset?: PlatformPreset | null;
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
  platform_preset?: PlatformPreset;
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
  /** null = 通用（不套平台写法） */
  platform_preset?: PlatformPreset | null;
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
  /** 说话风格 / 口头禅 / 称呼习惯（角色声音卡，正文按出场角色注入） */
  speech_style?: string | null;
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
  speech_style?: string | null;
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
  /** 正文指纹（详情 / 更新接口返回）：编辑器自动保存时作为 base_hash 回传，防止覆盖别处的修改 */
  content_hash?: string;
  /** 列表接口附带的写作链路状态 */
  outline_changed?: boolean;           // 正文写完（采用）后章纲又改过
  outline_review_status?: 'draft' | 'confirmed' | null;  // 关联章纲：draft = AI 草拟待确认
  outline_upstream_stale?: boolean;    // 关联章纲的上游（卷纲 / 总纲）已改
  pending_candidates?: number;         // 待采用的候选稿数
  /** 列表接口附带的分析状态（无正文为 null）：已分析 / 正文改过待重新分析 / 未分析 / 最近一次失败 / 分析中 */
  analysis_status?: ChapterAnalysisStatus | null;
  analysis_message?: string | null;    // 失败原因 / 降级说明
}

export type ChapterAnalysisStatus = 'ok' | 'stale' | 'missing' | 'failed' | 'running';

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
  /** 编辑器自动保存：所依据的正文指纹；与服务端当前正文不符返回 409 */
  base_hash?: string;
}

// 章节生成请求类型
export interface ChapterGenerateRequest {
  style_id?: number;
  target_word_count?: number;
  enable_mcp?: boolean;
  /** 写完后另起一次模型调用审校章纲遵循度，报告附在候选稿上（默认开） */
  adherence_review?: boolean;
  selected_plugins?: string[];
  /** 仿写参考：本次对标原书第几章（留空按章纲引用 / 位置自动对位） */
  kb_chapter?: number;
}

/** 服务端批量生成（后台任务，关掉浏览器也不停；已有正文的章节自动跳过 → 同范围重新发起即续跑） */
export interface ChapterBatchRequest {
  from_chapter: number;
  to_chapter: number;
  pause_on_critical?: boolean;
  quality_gate?: boolean;
  ai_flavor_threshold?: number;
  max_retries?: number;
  pipeline?: boolean;
  auto_expand?: boolean;
  style_id?: number;
  enable_mcp?: boolean;
  target_word_count?: number;
  /** 只写已确认的章纲：遇到 AI 草拟 / 上游已改的章纲就停 */
  require_confirmed_outline?: boolean;
  /** 章纲遵循度审校不通过时重写一次（默认开） */
  adherence_gate?: boolean;
}

/** 批量任务里每章的状态事件 */
export interface ChapterBatchEvent {
  type: 'batch_chapter';
  chapter_number: number;
  chapter_id: string | null;
  status: 'generating' | 'retrying' | 'quality_retry' | 'generated' | 'analyzing' | 'analysis_failed'
    | 'done' | 'skipped' | 'failed' | 'paused' | 'no_outline' | 'outline_unconfirmed';
  attempt?: number;
  error?: string;
  reason?: string;
  word_count?: number;
  quality_score?: number;
  critical?: number;
}

export interface ChapterBatchResult {
  status: 'completed' | 'paused' | 'stopped';
  completed: number[];
  skipped: number[];
  failed: { chapter_number: number; error: string }[];
  paused_at: number | null;
  warnings: string[];
  message: string;
}

/** 本章叙事任务（章纲展开时规划：要回收 / 推进 / 埋下的伏笔） */
export interface NarrativeTasks {
  resolve: { promise_id: string | null; title: string; how?: string }[];
  advance: { promise_id: string | null; title: string; how?: string }[];
  plant: { title: string; content: string; payoff_after?: number | null }[];
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
}

/** 项目内 AI 批量生成角色与组织（POST /api/characters/batch-generate-stream）：人物 0-10、组织 0-5，合计至少 1 个 */
export interface CharacterBatchGenerateRequest {
  project_id: string;
  character_count: number;
  organization_count: number;
  requirements?: string;
  enable_mcp?: boolean;
  selected_plugins?: string[];
}

/** 批量生成的结果（任务 result 事件的 data）：只含本次新建的名单，列表靠刷新取 */
export interface CharacterBatchResult {
  message: string;
  characters: number;
  organizations: number;
  relationships: number;
  memberships: number;
  created: { id: string; name: string; is_organization: boolean; role_type?: string | null }[];
  /** 和已有角色 / 组织重名而没建的名字 */
  skipped: string[];
}

/** 谋篇页 AI 生成总纲（POST /api/projects/{id}/story-outlines/generate-stream）：视角 / 章数 / 字数留空按项目设置 */
export interface StoryOutlineGenerateRequest {
  narrative_perspective?: string;
  chapter_count?: number;
  target_words?: number;
  requirements?: string;
  enable_mcp?: boolean;
  selected_plugins?: string[];
}

/** 谋篇页 AI 生成总纲的结果：新总纲存成活跃版本，旧版本保留；stale = 标「上游已改」的卷纲 + 章纲条数 */
export interface StoryOutlineGenerateResult {
  message: string;
  outline: Outline;
  previous_versions: number;
  stale: number;
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

/** 向导步骤 4：卷纲生成请求（POST /api/wizard-stream/volumes）：按总纲分卷 + 细化第 1 卷 */
export interface WizardVolumesRequest {
  project_id: string;
  chapter_count: number;
  model?: string;
}

/** 向导步骤 4：卷纲生成结果 */
export interface WizardVolumesResponse {
  message: string;
  chapter_count: number;
  volumes: Volume[];
  detailed_volume_id: string | null;
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

/** 章节档案：摘要 + 章末状态（作者改过的重新分析不覆盖，AI 新结果放进 suggestion） */
export interface ChapterDigestView {
  chapter_id: string;
  summary: string;
  end_state: string;
  source: 'ai' | 'author';
  suggestion: { summary: string; end_state: string } | null;
  /** 档案是按旧正文分析的（正文后来改过） */
  stale: boolean;
  updated_at?: string | null;
}

/** 本章结算出的硬性状态变化（生死 / 位置 / 境界 / 物品 / 伤势 / 目标 / 能力 / 故事时间） */
export interface ChapterStateChange {
  signal_type: string;
  label: string;
  character_name?: string | null;
  signal_key?: string | null;
  signal_value: string;
  evidence?: string | null;
}

/** 分析记录本身：标注、出场人物变化、地点、正文指纹 */
export interface ChapterAnalysisRecord {
  id: string;
  chapter_id: string;
  annotations: unknown[];
  character_states: Array<{ character_name: string; state_after?: string }>;
  locations: string[];
  content_hash?: string | null;
  created_at?: string | null;
}

// 章节分析结果响应（GET /chapters/{id}/analysis；没分析过也没档案 → 404）
export interface ChapterAnalysisResponse {
  chapter_id: string;
  analyzed: boolean;
  is_stale: boolean;
  content_updated_at?: string | null;
  analysis: ChapterAnalysisRecord | null;
  digest: ChapterDigestView | null;
  state_changes: ChapterStateChange[];
  narrative_state?: ChapterNarrativeState;
  consistency_audit?: ConsistencyAuditView;
  /** 最近一次分析任务：failed 时 message 是原因（之前的结果仍在用）；completed 带 message = 降级说明 */
  task?: { status: string; message?: string | null; completed_at?: string | null } | null;
  created_at?: string | null;
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

// 卷纲：总纲 → 卷纲（剧情单元 + 线索编排）→ 章纲
/** 剧情单元：一件完整的事，长短按事件大小定 */
export interface VolumeUnit {
  index: number;
  title: string;
  chapter_start: number;
  chapter_end: number;
  /** 这件事的经过：起因 → 经过（阻碍、选择、代价）→ 结果 */
  story: string;
  /** 单元结束时局面怎样变化 */
  turn: string;
}

export interface Volume {
  id: string;
  project_id: string;
  volume_number: number;
  title: string;
  chapter_start: number;
  chapter_end: number;
  summary: string;
  goal: string;
  climax: string;
  ending_hook: string;
  units: VolumeUnit[];
  /** 线索编排：感情线 / 支线 / 伏笔本卷推进到哪 */
  threads: string[];
  /** 上一卷卷末复盘回写的修正意见 */
  review_note: string;
  review_status: 'draft' | 'confirmed';
  confirmed_at?: string | null;
  upstream_stale: boolean;
  upstream_reason: string;
  outline_count: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface VolumeListResponse {
  items: Volume[];
  chapter_count?: number | null;
}

export type VolumeUnitInput = Pick<VolumeUnit, 'title' | 'chapter_start' | 'chapter_end' | 'story' | 'turn'>;

export interface VolumeFields {
  title?: string;
  summary?: string;
  goal?: string;
  climax?: string;
  ending_hook?: string;
  review_note?: string;
  chapter_start?: number;
  chapter_end?: number;
  units?: VolumeUnitInput[];
  threads?: string[];
}

export interface VolumePlanRequest {
  total_chapters?: number;
  volume_count?: number;
  instruction?: string;
  model?: string;
}

export interface VolumeGenerateRequest {
  instruction?: string;
  model?: string;
}

/** 卷纲规划任务的结果（skeleton → volumes；detail → volume；outlines → 章号与章纲 ID） */
export interface VolumeJobResult {
  action: 'skeleton' | 'detail' | 'outlines';
  volumes?: Volume[];
  volume?: Volume;
  volume_id?: string;
  unit_index?: number;
  chapter_numbers?: number[];
  outline_ids?: string[];
}

// 章纲类型定义 - 专业网文版
export interface ChapterOutline {
  id: string;
  project_id: string;
  chapter_number: number;
  title: string;
  // 场景信息（新增）
  scene?: string;                // 场景地点，如"拳击场→后台"
  pov?: string;                  // 视角角色名
  // 剧情信息
  plot_points?: string;          // 剧情要点（含情感变化）
  key_events?: string[];         // 关键事件，最后一条为章末钩子
  characters_involved?: string[];
  narrative_tasks?: NarrativeTasks | null;  // 本章叙事任务（伏笔 / 承诺）
  // 章节契约：开头承接 / 写到哪停 / 不能提前发生的事
  entry_state?: string | null;
  exit_state?: string | null;
  forbidden?: string[];
  // 确认与上游过期
  review_status?: 'draft' | 'confirmed';
  confirmed_at?: string | null;
  upstream_stale?: boolean;
  upstream_reason?: string | null;
  /** 所属卷纲与剧情单元（NULL = 手建 / 旧数据） */
  volume_id?: string | null;
  unit_index?: number | null;
  // 旧字段（保留兼容）
  summary?: string;              // 已废弃，保留兼容旧数据
  // 系统字段
  target_word_count: number;
  order_index?: number;
  created_at: string;
  updated_at: string;
}

export interface ChapterOutlineCreate {
  project_id: string;
  volume_id?: string;
  unit_index?: number;
  chapter_number: number;
  title: string;
  // 场景信息（新增）
  scene?: string;
  pov?: string;
  // 剧情信息
  plot_points?: string;
  key_events?: string[];
  characters_involved?: string[];
  entry_state?: string;
  exit_state?: string;
  forbidden?: string[];
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
  entry_state?: string;
  exit_state?: string;
  forbidden?: string[];
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
  outlines: ChapterOutlineCreate[];
}

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

// 世界设定条目类型（术语 / 铁律 / 势力 / 通用规则等，与世界规则的境界·装备·地图三类互补）
export type SettingEntryCategory = 'term' | 'law' | 'faction' | 'rule' | 'other';

export interface SettingEntry {
  id: string;
  project_id: string;
  category: SettingEntryCategory | string;
  title: string;
  summary?: string;
  content?: string;
  order_index: number;
  created_at: string;
  updated_at: string;
}

export interface SettingEntryCreate {
  category: string;
  title: string;
  summary?: string;
  content?: string;
  order_index?: number;
}

export interface SettingEntryUpdate {
  category?: string;
  title?: string;
  summary?: string;
  content?: string;
  order_index?: number;
}

export interface SettingEntryListResponse {
  total: number;
  items: SettingEntry[];
}

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

/** interrupted：库里还是 running、但没有流水线在跑（服务重启 / 程序退出前没跑完），只在读取时这样显示，可直接继续抽取 */
export type BookDissectStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
/** 运行方式：full 删掉拆书卡从头抽 / resume 只抽失败和没抽过的章 / rebuild_post 拆书卡不动，只重建后续产物 */
export type BookDissectRunMode = 'full' | 'resume' | 'rebuild_post';
/** 拆书流水线阶段：切章 → 拆书卡 → 剧情单元 → 分卷 / 骨架 → 文风 → 拆书结果 */
export type BookDissectStage =
  | 'split_done'
  | 'queued'
  | 'splitting'
  | 'cards'
  | 'arcs'
  | 'skeleton'
  | 'style'
  | 'pack'
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
  version?: number;
  extraction_phase?: string | null;
  chapters_total?: number;
  chapters_extracted?: number;
  chapters_failed?: number;
  sampling_mode?: string;
  sampling_param?: number;
  extraction_engine?: BookDissectExtractionEngine;
  /** 每次 LLM 请求抽取的章节数；0 = 自动规划 */
  chapters_per_request?: number;
  /** 只抽取前 N 章；0 = 全部 */
  chapter_limit?: number;
  /** 正在运行的抽取对应的通用 AI 任务 id（接入弹窗 / 托盘）；未运行为 null */
  job_id?: string | null;
  /** 拆书结果状态：ready / partial / failed；还没有结果为 null */
  pack_status?: string | null;
  /** 拆书结果不完整的原因（缺哪些维度 / 章节覆盖率） */
  pack_error?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export type BookDissectExtractionEngine = 'auto' | 'chunked' | 'long_context';

export interface BookDissectExtractionOptions {
  mode?: BookDissectRunMode;
  sampling_mode?: string;
  sampling_param?: number;
  extraction_engine?: BookDissectExtractionEngine;
  chapters_per_request?: number;
  chapter_limit?: number;
}

/** 启动前的分批预估（POST /book-dissect/{id}/extraction-plan） */
export interface BookDissectExtractionPlan {
  chapter_count: number;
  target_chapters: number;
  batch_count: number;
  mode: 'single' | 'batched' | 'one_shot';
  chapters_per_request: number;
  max_chapters_by_output: number;
  model: string;
  context_window: number;
  max_tokens: number;
  dictionary_calls: number;
  /** 拆书卡之后的调用估算：剧情单元 + 分卷 + 骨架 / 人物谱 / 手册 + 文风定性与例句 */
  post_calls: number;
  /** 其中剧情单元识别的轮数 = ceil(目标章数 / arc_window) */
  arc_calls: number;
  /** 剧情单元识别每轮喂的拆书卡数（按模型上下文 / Max Tokens 规划，8-60） */
  arc_window: number;
  estimated_llm_calls: number;
  warnings: string[];
  /** 这份预估对应的运行方式 */
  run_mode: BookDissectRunMode;
  /** 范围内已经成功的拆书卡数 */
  existing_cards: number;
  /** 这次要抽拆书卡的章数（继续只算失败 / 没抽过的；只重建为 0） */
  pending_chapters: number;
}

/** 章节目录一行（GET /book-dissect/{id}/chapters）：切章结果 + 这一章拆书卡的状态 */
export interface BookDissectChapterItem {
  number: number;
  title: string;
  raw_title: string;
  word_count: number;
  kind: string;
  /** success / failed；null = 还没抽 */
  status: 'success' | 'failed' | null;
  error: string | null;
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

// ============================================================
// 拆书浏览类型（拆书卡 / 剧情单元）
// 后端 schema：@/backend/app/schemas/book_dissect.py
// ============================================================

/** 拆书卡精简行（GET /book-dissect/{id}/cards），不含章纲正文 */
export interface BookDissectChapterCardListItem {
  chapter_number: number;
  title: string;
  function_tags: string[];
  pace: string;
  tension: number;
  ending_hook_type: string;
  payoff_count: number;
  word_count: number;
  extraction_status: string;
  /** 单章超长、只送了章首章尾 */
  truncated_input?: boolean;
  /** 失败原因（截前 200 字）；成功为 null */
  extraction_error?: string | null;
}

/** 整张拆书卡（GET /book-dissect/{id}/cards/{chapter_number}） */
export interface BookDissectChapterCard {
  chapter_number: number;
  title: string;
  outline: string;
  function_tags: string[];
  pace: string;
  tension: number;
  emotion_tone: string;
  ending_hook_type: string;
  ending_hook_text: string;
  payoff_points: string[];
  highlights: string[];
  characters: string[];
  protagonist_delta: string;
  new_settings: string[];
  word_count: number;
  truncated_input: boolean;
  extraction_status: string;
  extraction_error: string | null;
}

/** 剧情单元（GET /book-dissect/{id}/arcs），与拆书结果 bridges.typical_arcs 同形：一件完整的事 */
export interface BookDissectStoryArc {
  arc_index: number;
  start_chapter: number;
  end_chapter: number;
  title: string;
  function: string;
  boundary_reason: string;
  /** 经过：起因 → 经过（阻碍、选择、代价）→ 结果 */
  story: string;
  structure: string;
  /** 主角靠什么推进 / 解决 */
  approach: string;
  /** 单元结束时局面怎样变化 */
  turn: string;
  emotion_curve: string;
  payoff: string;
  payoff_type: string;
  character_changes: string;
  gains_costs: string;
  foreshadowing: string;
  chapter_roles: Record<string, string>;
  tension_peak_chapter: number | null;
  origin: string;
}
