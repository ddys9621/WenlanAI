/**
 * V4.1 K2 桥段四章结构 - 前端类型定义
 *
 * 对应后端 PlotBridge model（详见 backend/app/models/plot_bridge.py）
 */

type BridgePosition = 'intro' | 'build' | 'payoff' | 'aftermath';

/** 题材族模板 key（对应 backend/app/services/bridge_templates.py） */
type BridgeTemplateKey = 'showoff' | 'mystery' | 'romance' | 'infinite';

export const BRIDGE_TEMPLATE_UI: Record<
  BridgeTemplateKey,
  { name: string; payoffLabel: string; positions: Record<BridgePosition, string>; hints: Record<BridgePosition, string> }
> = {
  showoff: {
    name: '爽文装逼打脸流',
    payoffLabel: '装逼点',
    positions: { intro: 'C1 代入', build: 'C2 拉扯', payoff: 'C3 兑现', aftermath: 'C4 善后' },
    hints: { intro: '5:5', build: '9:1 章尾开装', payoff: '无钩子', aftermath: '承上启下' },
  },
  mystery: {
    name: '悬疑反转流',
    payoffLabel: '反转点',
    positions: { intro: 'C1 异象疑点', build: 'C2 追查误导', payoff: 'C3 反转揭示', aftermath: 'C4 余波新疑' },
    hints: { intro: '5:5', build: '9:1 章尾关键线索', payoff: '无钩子', aftermath: '承上启下' },
  },
  romance: {
    name: '言情推拉流',
    payoffLabel: '情感兑现点',
    positions: { intro: 'C1 情感缺口', build: 'C2 推拉误会', payoff: 'C3 情感兑现', aftermath: 'C4 新状态' },
    hints: { intro: '5:5', build: '9:1 章尾心动动作', payoff: '无钩子', aftermath: '承上启下' },
  },
  infinite: {
    name: '无限流规则破局',
    payoffLabel: '破局点',
    positions: { intro: 'C1 入局规则', build: 'C2 试探代价', payoff: 'C3 破局兑现', aftermath: 'C4 结算' },
    hints: { intro: '5:5', build: '9:1 章尾看破规则', payoff: '无钩子', aftermath: '承上启下' },
  },
};

/** 把后端返回的 template 字符串收敛成已知 key（未知 / 缺失 → showoff） */
export function resolveTemplateKey(key: string | null | undefined): BridgeTemplateKey {
  return key && key in BRIDGE_TEMPLATE_UI ? (key as BridgeTemplateKey) : 'showoff';
}

/** 桥段填充溯源（plot_bridges.generation_meta，后端 build_fill_provenance 产出） */
export interface BridgeGenerationMeta {
  version: number;
  generated_at: string;
  scene: string;
  model: string;
  model_tier: string;
  template: string;
  reference_pack: { title: string; dimensions: Record<string, string> } | null;
  slots: { filled: string[]; truncated: string[]; skipped: string[] };
  inputs: {
    story_outline_fields: string[];
    beat: { index: number; title: string };
    next_beat_title: string | null;
    prev_bridge_number: number | null;
    ledger_bridge_numbers: number[];
    opening_rules: boolean;
    bridge_numbers: number[];
  };
  tokens_estimate: number;
  warnings: string[];
}

/** fill-stream 的 meta 事件（每个子批一次） */
export interface FillMetaEvent {
  type: 'meta';
  beat_index: number;
  bridge_numbers: number[];
  provenance: BridgeGenerationMeta;
  seq?: number;
}

/** 打字机快照：LLM 已写出的字段（半截 JSON 容错解析结果） */
export type PartialBridge = { bridge_number: number } & Partial<
  Pick<
    PlotBridge,
    'title' | 'goal' | 'showoff_point' | 'golden_finger_usage' | 'c1_intro' | 'c2_build' | 'c3_payoff' | 'c4_aftermath' | 'next_bridge_hook'
  >
>;

export interface FillPartialEvent {
  type: 'partial';
  beat_index: number;
  bridge_numbers: number[];
  bridges: PartialBridge[];
  content_chars: number;
  elapsed: number;
  seq?: number;
}

/** 推理模型思考中 / 网络静默心跳：只有计数与计时，不含思考文本 */
export interface FillThinkingEvent {
  type: 'thinking';
  beat_index: number;
  bridge_numbers: number[];
  reasoning_chars: number;
  content_chars: number;
  elapsed: number;
  seq?: number;
}

/** 一个子批落库后的完整桥段（卡片 draft → ready） */
export interface FillBridgesEvent {
  type: 'bridges';
  beat_index: number;
  bridges: PlotBridge[];
  seq?: number;
}

export type BridgeStatus = 'draft' | 'ready' | 'generating' | 'completed';

export const BRIDGE_STATUS_LABEL: Record<BridgeStatus, string> = {
  draft: '草稿',
  ready: '就绪',
  generating: '生成中',
  completed: '已展开',
};

/** 副线任务：支线/角色线节点挂到主线桥段（由后端 bridge_slot_planner 计算） */
export interface SecondaryBeatTask {
  plot_line_id: string;
  line_title: string;
  line_type: string;
  beat_index: number;
  beat_title: string;
  beat_description: string;
  coverage_start: number;
  coverage_end: number;
  /** primary = 本桥段主 B 线（须推进）；mention = 保温提及一句。旧数据缺省按 primary */
  role?: 'primary' | 'mention';
  /** offset = 与主线错峰；merge = 汇入主线节点兑现桥段 */
  relation?: 'offset' | 'merge';
}

type LineMode = 'companion' | 'inserted' | 'converge';

export const LINE_MODE_LABEL: Record<LineMode, string> = {
  companion: '伴生',
  inserted: '插入',
  converge: '汇流',
};

/** 一条副线在本次规划中的预算账（plan-preview.line_budgets） */
export interface LineBudget {
  plot_line_id: string;
  line_title: string;
  line_type: string;
  anchored: boolean;
  mode: LineMode | null;
  anchor_start_beat: number | null;
  anchor_end_beat: number | null;
  estimated_chapters: number | null;
  /** 锚定线：round(预算章数/4)；未锚定线：0（不限） */
  primary_quota: number;
  primary_bridges: number;
  mention_bridges: number;
}

export const isPrimaryTask = (t: SecondaryBeatTask) => (t.role ?? 'primary') !== 'mention';

export interface PlotBridge {
  id: string;
  project_id: string;
  bridge_number: number;
  title: string;
  goal: string;
  showoff_point: string;
  golden_finger_usage: string | null;
  c1_intro: string | null;
  c2_build: string | null;
  c3_payoff: string | null;
  c4_aftermath: string | null;
  next_bridge_hook: string | null;
  status: BridgeStatus;
  order_index: number | null;
  // 桥段 ↔ 主线节点绑定字段（代码写入，非 LLM）
  plot_line_id: string | null;
  beat_index: number | null;
  beat_coverage_start: number | null;
  beat_coverage_end: number | null;
  /** 副线任务列表 */
  secondary_beats: SecondaryBeatTask[];
  /** 确定性章号范围：第 4(n-1)+1 … 4n 章 */
  chapter_start: number;
  chapter_end: number;
  /** 最近一次 LLM 填充的溯源；draft / 旧数据为 null */
  generation_meta?: BridgeGenerationMeta | null;
  /** 填充时使用的题材模板 key；null 时按 showoff 展示 */
  template?: string | null;
}

/** GET /projects/{id}/bridges/plan-preview 返回的槽位表（纯计算，不写库） */
export interface BridgeSlotPreview {
  main_line_id: string;
  total_bridges: number;
  total_chapters: number;
  /** beat_index(字符串) → 该节点桥段数 */
  beat_quotas: Record<string, number>;
  slots: Array<{
    bridge_number: number;
    plot_line_id: string;
    beat_index: number;
    beat_title: string;
    beat_description: string;
    beat_weight: number;
    coverage_start: number;
    coverage_end: number;
    chapter_start: number;
    chapter_end: number;
    secondary: SecondaryBeatTask[];
  }>;
  /** 每条副线的预算账 */
  line_budgets: LineBudget[];
}

/** POST /projects/{id}/bridges/fill-stream 请求体 */
export interface FillBridgesRequest {
  model?: string;
  /** 只填充该主线节点的 draft 桥段 */
  beat_index?: number;
}

/** fill-stream 的 result 事件 */
export interface FillBridgesResult {
  type: 'done';
  filled: number;
  remaining_drafts: number;
}

export interface ExpandBridgeRequest {
  model?: string;
}

export interface ExpandBridgeResponse {
  success: boolean;
  bridge_id: string;
  chapter_count: number;
  chapter_ids: string[];
}

export interface UpdateBridgeRequest {
  title?: string;
  goal?: string;
  showoff_point?: string;
  golden_finger_usage?: string;
  c1_intro?: string;
  c2_build?: string;
  c3_payoff?: string;
  c4_aftermath?: string;
  next_bridge_hook?: string;
  status?: BridgeStatus;
}

/** 批量展开请求（按 bridge_number 顺序，首个失败即停止）。 */
export interface ExpandAllBridgesRequest {
  model?: string;
}

/** 批量展开结果（后台任务 result 事件的 data；服务层汇总字典，没有 success 字段）。 */
export interface ExpandAllBridgesResponse {
  success?: boolean;
  total: number;
  succeeded: string[];
  failed: Array<{ bridge_id: string; error: string }>;
  created_chapter_count: number;
}
