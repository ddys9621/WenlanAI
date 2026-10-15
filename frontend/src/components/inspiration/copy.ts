/** 灵感模式 - 文案与静态配置（无组件） */

import { BookOpenText, GitBranch, Globe, Users, type LucideIcon } from 'lucide-react';
import type { FlowStep } from './flow';
import type { GenerationNodeKey } from './useProjectGeneration';
import type { GenStepStatus, OptionGenerationStep } from './types';

interface StepMeta {
  eyebrow: string;
  title: string;
  description: string;
  /** 选好之后会发生什么，用于阶段卡底部的"下一步"提示 */
  next: string;
  manualLabel: string;
  inputPlaceholder: string;
  /** 候选文案偏长时单列排布，短文案双列 */
  columns: 1 | 2;
}

export const STEP_META: Record<FlowStep, StepMeta> = {
  idea: {
    eyebrow: '灵感',
    title: '先写下你的故事种子',
    description: '一句话、一个画面或一段设定都可以，AI 会从这里出发帮你搭起整本书。',
    next: '下一步 AI 会先给出书名候选',
    manualLabel: '',
    inputPlaceholder: '例如：民国旧报馆里，一个专写奇闻的女记者，卷进带民俗色彩的连环失踪案……',
    columns: 2,
  },
  title: {
    eyebrow: '书名',
    title: '挑一个抓人的书名方向',
    description: '选一个候选，或者直接写下你自己的书名。',
    next: '选好后 AI 会据此生成简介候选',
    manualLabel: '自己写书名',
    inputPlaceholder: '写一版你自己的书名',
    columns: 2,
  },
  description: {
    eyebrow: '简介',
    title: '把简介收紧成一句主卖点',
    description: '讲清前提和主冲突即可，细节留给后面的大纲。',
    next: '选好后 AI 会从简介里提炼主题',
    manualLabel: '自己写简介',
    inputPlaceholder: '直接写你想要的简介版本',
    columns: 1,
  },
  theme: {
    eyebrow: '主题',
    title: '确认作品真正想讨论的主题',
    description: '选一个最贴近的，或写下你想表达的。',
    next: '选好后 AI 会组合类型标签',
    manualLabel: '自己写主题',
    inputPlaceholder: '如果候选都不对，直接写下你要表达的主题',
    columns: 1,
  },
  genre: {
    eyebrow: '类型',
    title: '选出最贴近的类型组合',
    description: '可以多选，组合越具体越好。',
    next: '确认后进入视角选择',
    manualLabel: '自己写类型',
    inputPlaceholder: '例如：洪荒流、系统流、轻喜剧修仙',
    columns: 2,
  },
  perspective: {
    eyebrow: '视角',
    title: '决定叙事视角',
    description: '视角决定读者跟谁走、知道多少。',
    next: '选好后进入创建前的最终确认',
    manualLabel: '其他视角',
    inputPlaceholder: '例如：限知第三人称、双主角交替视角',
    columns: 2,
  },
  confirm: {
    eyebrow: '确认',
    title: '信息已收齐，创建前再看一眼',
    description: '确认后 AI 将依次生成世界观、角色、总纲与卷纲。',
    next: '',
    manualLabel: '',
    inputPlaceholder: '',
    columns: 2,
  },
};

/** 等待候选时轮播的状态短句，让用户知道 AI 在做什么 */
export const THINKING_PHASES: Record<OptionGenerationStep | 'quick', string[]> = {
  title: ['正在拆解灵感里的关键词', '提炼核心冲突与意象', '组合书名候选'],
  description: ['正在围绕书名铺开前提', '锁定主冲突与卖点', '收紧简介候选'],
  theme: ['正在从简介里提炼主题', '对比不同的表达方向', '整理主题候选'],
  genre: ['正在匹配类型标签', '评估常见的类型组合', '整理类型候选'],
  quick: ['正在综合已确定的信息', '补全剩余字段', '整理确认清单'],
};

/** 视角候选的一句话说明（后端固定给这三项，其他值不加说明） */
export const PERSPECTIVE_HINTS: Record<string, string> = {
  第一人称: '以「我」讲述，代入感强，信息受限',
  第三人称: '跟随主角视角，灵活又克制',
  全知视角: '上帝视角，可自由切换人物与时间线',
};

/** 灵感阶段的示例种子，点一下直接填入输入框 */
export const SAMPLE_SEEDS = [
  '民国旧报馆里，一个专写奇闻的女记者，卷进带民俗色彩的连环失踪案',
  '末世后漂在海上的拼装城市，修船匠捡到一个能听懂潮汐的孩子',
  '修仙界的外卖员，靠送餐结识各路大佬，却被卷进宗门秘辛',
];

interface NodeMeta {
  key: GenerationNodeKey;
  label: string;
  hint: string;
  icon: LucideIcon;
}

export const NODE_META: NodeMeta[] = [
  { key: 'worldBuilding', label: '世界观', hint: '先把舞台和规则搭稳', icon: Globe },
  { key: 'characters', label: '角色', hint: '再补主角群和关系', icon: Users },
  { key: 'outline', label: '总纲', hint: '落成故事前提与全书主线', icon: BookOpenText },
  { key: 'volumes', label: '卷纲', hint: '按总纲分卷，第 1 卷拆成剧情单元', icon: GitBranch },
];

/** 创建过程可能长达数分钟，底部轮播一些"接下来能做什么"，让等待有内容可读 */
export const GENERATION_TIPS = [
  '每个环节完成后都会在上方留下一行摘要，全部完成后可以逐项重跑。',
  '世界观里的时代、地点与规则，会作为后续角色、大纲和正文生成的统一约束。',
  '角色会带着动机与关系一起生成，进入项目后可在「角色」「关系」页继续细调。',
  '总纲落成后按卷规划：每卷拆成几件完整的事（剧情单元），再逐件展开成章纲。',
  '中途离开当前页面会中断后续环节；已完成的部分会保留在项目里。',
];

export const NODE_STATUS_LABEL: Record<GenStepStatus, string> = {
  pending: '等待',
  processing: '进行中',
  completed: '已完成',
  error: '失败',
};

export const CONFIRM_CREATE_OPTION = '✅ 确认创建';

/** 状态机里表示"我自己写"的候选项，不作为选项卡片展示 */
export const MANUAL_INPUT_OPTIONS = new Set(['我自己输入书名', '我自己输入']);
/** 状态机里表示"重试"的候选项，改由错误提示条上的按钮触发 */
export const REGENERATE_OPTIONS = new Set(['重新生成', '让AI重新生成']);
export const CHOICE_STEPS = new Set<FlowStep>(['title', 'description', 'theme', 'genre', 'perspective']);
