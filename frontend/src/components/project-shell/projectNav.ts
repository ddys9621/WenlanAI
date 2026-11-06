/**
 * 项目工作台的导航（左栏「设定 / 大纲 / 目录 / 资料」四个页签，每个页面一张入口卡片）。
 * 路由不变，只决定页面入口放在哪个页签、卡片怎么写；智能助笔的「当前页面」仍按改版前的页面键与名称登记（sectionOf）。
 */
import type { LucideIcon } from 'lucide-react'
import {
  BookOpen, BookOpenText, Brain, FileText, FolderOpen, GitBranch, Globe, Layers, Library, ListTree, Map as MapIcon,
  Palette, PenLine, ScrollText, Shapes, Shield, Users,
} from 'lucide-react'

export type NavTabKey = 'setting' | 'outline' | 'directory' | 'library'

/** 工作台各处显示的计数（卷纲 / 章纲在谋篇页加载过才有） */
export interface ProjectStats {
  outlines: number
  people: number
  organizations: number
  chapters: number
  words: number
  volumes: number
  chapterOutlines: number
}

export const PROJECT_STATUS_META = {
  planning: { label: '规划中', className: 'lj-badge lj-badge--muted' },
  writing: { label: '创作中', className: 'lj-badge lj-badge--ok' },
  revising: { label: '修改中', className: 'lj-badge lj-badge--draft' },
  completed: { label: '已完成', className: 'lj-badge lj-badge--candidate' },
} as const

export interface NavEntry {
  label: string
  icon: LucideIcon
  /** 相对 /project/:projectId/ 的路由 */
  path: string
  /** 卡片上的一句说明 */
  desc: string
}

export interface NavTab {
  key: NavTabKey
  label: string
  icon: LucideIcon
  entries: NavEntry[]
}

export const NAV_TABS: NavTab[] = [
  {
    key: 'setting',
    label: '设定',
    icon: BookOpenText,
    entries: [
      { label: '世界设定', icon: Globe, path: 'world-setting', desc: '时代、地点、氛围与规则分开整理，先立框架再填细节' },
      { label: '世界规则', icon: Shield, path: 'world-rules', desc: '修炼境界、装备模板与地图位置，写作时保持设定一致' },
      { label: '设定条目', icon: Shapes, path: 'setting-entries', desc: '术语、铁律、势力分条整理，写作时按需检索带上' },
      { label: '世界地图', icon: MapIcon, path: 'world-map', desc: '地图位置落成的地点、坐标与档案' },
      { label: '角色与组织', icon: Users, path: 'characters', desc: '故事里的人物与势力，AI 续写时作为上下文' },
      { label: '关系管理', icon: GitBranch, path: 'relationships', desc: '角色两两之间的关系、亲密度与当前状态' },
    ],
  },
  {
    key: 'outline',
    label: '大纲',
    icon: ListTree,
    entries: [
      { label: '总纲', icon: FileText, path: 'outline', desc: '全书主线、金手指与卖点，定下整本书往哪走' },
      { label: '卷纲', icon: Layers, path: 'outline/volumes', desc: '每卷拆成几件完整的事，线索怎么编排' },
      { label: '章纲', icon: BookOpen, path: 'outline/chapters', desc: '把每件事落到章，确认后才写正文' },
    ],
  },
  {
    key: 'directory',
    label: '目录',
    icon: PenLine,
    entries: [
      { label: '章节写作', icon: PenLine, path: 'chapter-analysis', desc: '码字、候选稿与历史版本' },
    ],
  },
  {
    key: 'library',
    label: '资料',
    icon: FolderOpen,
    entries: [
      { label: '写作风格', icon: Palette, path: 'writing-styles', desc: '叙述语气与遣词习惯，生成正文时按默认风格执行' },
      { label: '提示词', icon: ScrollText, path: 'prompts', desc: '按本书改写 AI 的写作指导，只影响这个项目' },
      { label: '仿写参考', icon: Library, path: 'knowledge', desc: '选一本知识库里的书做对标，学它的节奏和结构' },
      { label: '故事账本', icon: Brain, path: 'memories', desc: '伏笔、人物状态、章节档案与时间线' },
    ],
  },
]

/** 智能助笔登记的「当前页面」：页面键与名称沿用改版前（后端 PAGES、核对清单跳转都按这套键），顺序决定匹配先后 */
const SECTIONS: { path: string; label: string }[] = [
  { path: 'world-setting', label: '世界设定' },
  { path: 'world-rules', label: '世界规则' },
  { path: 'setting-entries', label: '设定条目' },
  { path: 'world-map', label: '世界地图' },
  { path: 'characters', label: '角色与组织' },
  { path: 'relationships', label: '关系管理' },
  { path: 'outline', label: '谋篇（总纲·卷纲·章纲）' },
  { path: 'chapter-analysis', label: '章节写作' },
  { path: 'writing-styles', label: '写作风格' },
  { path: 'prompts', label: '提示词' },
  { path: 'knowledge', label: '仿写参考' },
  { path: 'memories', label: '故事账本' },
]

export function sectionOf(pathname: string): { page: string; label: string } {
  const hit = SECTIONS.find((s) => pathname.includes(s.path))
  return hit ? { page: hit.path, label: hit.label } : { page: '', label: '创作总览' }
}

/** 地址里 /project/:projectId/ 之后的部分，如 outline/volumes */
export function projectSubPath(pathname: string): string {
  const m = pathname.match(/^\/project\/[^/]+\/?(.*)$/)
  return m ? m[1].replace(/\/+$/, '') : ''
}

/** 地址对应的入口卡片：按路径段取最长匹配（outline/volumes 先于 outline） */
export function entryOf(pathname: string): NavEntry | undefined {
  const sub = projectSubPath(pathname)
  let best: NavEntry | undefined
  for (const tab of NAV_TABS) {
    for (const entry of tab.entries) {
      const hit = sub === entry.path || sub.startsWith(`${entry.path}/`)
      if (hit && (!best || entry.path.length > best.path.length)) best = entry
    }
  }
  return best
}

/** 地址所在的页签；不在任何入口下（如组织管理）归到「设定」 */
export function tabOf(pathname: string): NavTabKey {
  const entry = entryOf(pathname)
  return NAV_TABS.find((tab) => entry && tab.entries.includes(entry))?.key ?? 'setting'
}

/** 章节写作页铺满中栏：目录挪到左栏，正文编辑器自带工具栏和状态栏 */
export function isFullBleed(pathname: string): boolean {
  return /^chapter-analysis(\/|$)/.test(projectSubPath(pathname))
}

export function filterEntries(entries: NavEntry[], keyword: string): NavEntry[] {
  const k = keyword.trim().toLowerCase()
  if (!k) return entries
  return entries.filter((e) => e.label.toLowerCase().includes(k) || e.desc.toLowerCase().includes(k))
}

/** 左栏目录的搜索：标题包含关键字，或按章号（「12」「第12章」） */
export function filterChapters<T extends { title: string; chapter_number: number }>(chapters: T[], keyword: string): T[] {
  const k = keyword.trim()
  if (!k) return chapters
  return chapters.filter((c) => c.title.includes(k) || String(c.chapter_number) === k.replace(/^第|章$/g, ''))
}

/** 字数缩写：一万以上写「x.x万」 */
export function formatCount(n: number): string {
  return n >= 10000 ? `${(n / 10000).toFixed(1)}万` : String(n)
}
