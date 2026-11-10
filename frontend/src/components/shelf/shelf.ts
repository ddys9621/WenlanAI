/**
 * 书架（/projects）的纯逻辑：显示状态、搜索筛选、排序、分组、封面色调、本机偏好、字数与时间的写法。
 * 组件文件只导出组件（react-refresh），这些都放这里。
 */
import type { CSSProperties } from 'react'
import type { Project } from '@/types'
import { parseServerTime } from '@/utils/serverTime'

/* ─── 状态 ─── */

/** 书架上显示的状态。项目的 status 页面上改不了（新书一律 planning），所以有正文就算「创作中」；修改中、已完成照存的 */
export type ShelfState = Project['status']

export const SHELF_STATE_LABEL: Record<ShelfState, string> = {
  planning: '规划中',
  writing: '创作中',
  revising: '修改中',
  completed: '已完成',
}

/** 分组、筛选菜单里的顺序 */
export const SHELF_STATES: ShelfState[] = ['writing', 'planning', 'revising', 'completed']

export function shelfStateOf(p: Pick<Project, 'status' | 'current_words'>): ShelfState {
  if (p.status === 'completed' || p.status === 'revising') return p.status
  return p.status === 'writing' || (p.current_words || 0) > 0 ? 'writing' : 'planning'
}

export function countByState(list: Project[]): Record<ShelfState, number> {
  const counts: Record<ShelfState, number> = { planning: 0, writing: 0, revising: 0, completed: 0 }
  list.forEach((p) => { counts[shelfStateOf(p)] += 1 })
  return counts
}

export interface ShelfSummary {
  total: number
  writing: number
  completed: number
  words: number
}

export function shelfSummary(list: Project[]): ShelfSummary {
  const counts = countByState(list)
  return {
    total: list.length,
    writing: counts.writing,
    completed: counts.completed,
    words: list.reduce((sum, p) => sum + (p.current_words || 0), 0),
  }
}

/** 类型一栏常写成「玄幻,冒险」「都市、现实」：拆开取前几个 */
export function genresOf(genre: string | undefined, max = 2): string[] {
  return (genre ?? '').split(/[,，、/|]/).map((g) => g.trim()).filter(Boolean).slice(0, max)
}

/** 定了目标字数才有进度（0–100） */
export function progressOf(p: Pick<Project, 'current_words' | 'target_words'>): number | null {
  const target = p.target_words || 0
  if (target <= 0) return null
  return Math.min(100, Math.round(((p.current_words || 0) / target) * 100))
}

/* ─── 搜索 / 筛选 / 排序 / 分组 ─── */

export type ShelfFilter = 'all' | ShelfState
export type ShelfSort = 'updated' | 'created' | 'title' | 'words'
export type ShelfGroup = 'none' | 'state' | 'time'
export type ShelfView = 'grid' | 'list'

export const SORT_OPTIONS: Array<[ShelfSort, string]> = [
  ['updated', '最近编辑'],
  ['created', '创建时间'],
  ['title', '书名'],
  ['words', '字数'],
]

export const GROUP_OPTIONS: Array<[ShelfGroup, string]> = [
  ['none', '不分组'],
  ['state', '按状态'],
  ['time', '按更新时间'],
]

export function filterProjects(list: Project[], { query, filter }: { query: string; filter: ShelfFilter }): Project[] {
  const q = query.trim().toLowerCase()
  return list.filter((p) => {
    if (filter !== 'all' && shelfStateOf(p) !== filter) return false
    if (!q) return true
    return [p.title, p.description, p.genre].some((text) => text?.toLowerCase().includes(q))
  })
}

const timeOf = (value: string | undefined) => parseServerTime(value)?.getTime() ?? 0

export function sortProjects(list: Project[], sort: ShelfSort): Project[] {
  const next = [...list]
  switch (sort) {
    case 'created':
      return next.sort((a, b) => timeOf(b.created_at) - timeOf(a.created_at))
    case 'title':
      return next.sort((a, b) => displayTitle(a.title).localeCompare(displayTitle(b.title), 'zh-Hans-CN', { sensitivity: 'base', numeric: true }))
    case 'words':
      return next.sort((a, b) => (b.current_words || 0) - (a.current_words || 0))
    default:
      return next.sort((a, b) => timeOf(b.updated_at) - timeOf(a.updated_at))
  }
}

export interface ShelfGroupBlock {
  key: string
  label: string
  items: Project[]
}

const TIME_BUCKETS: Array<[string, number]> = [['今天', 0], ['最近 7 天', 6], ['最近 30 天', 29], ['更早', Infinity]]
const DAY = 86_400_000

/** 分组保持传进来的顺序（先排序再分组） */
export function groupProjects(list: Project[], group: ShelfGroup, now: Date = new Date()): ShelfGroupBlock[] {
  if (group === 'state') {
    return SHELF_STATES
      .map((state) => ({ key: state, label: SHELF_STATE_LABEL[state], items: list.filter((p) => shelfStateOf(p) === state) }))
      .filter((g) => g.items.length > 0)
  }
  if (group === 'time') {
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
    const daysAgo = (p: Project) => {
      const d = parseServerTime(p.updated_at)
      if (!d) return Infinity
      return Math.max(0, Math.round((today - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / DAY))
    }
    const blocks = TIME_BUCKETS.map(([label]) => ({ key: label, label, items: [] as Project[] }))
    list.forEach((p) => {
      const days = daysAgo(p)
      blocks[TIME_BUCKETS.findIndex(([, max]) => days <= max)].items.push(p)
    })
    return blocks.filter((g) => g.items.length > 0)
  }
  return [{ key: 'all', label: '', items: list }]
}

/* ─── 本机偏好（排序 / 分组 / 视图） ─── */

export interface ShelfPrefs {
  sort: ShelfSort
  group: ShelfGroup
  view: ShelfView
}

export const DEFAULT_SHELF_PREFS: ShelfPrefs = { sort: 'updated', group: 'none', view: 'grid' }

const PREFS_KEY = 'shelf-prefs'
const pick = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T =>
  allowed.includes(value as T) ? (value as T) : fallback

export function readShelfPrefs(storage: Pick<Storage, 'getItem'> | null): ShelfPrefs {
  try {
    const raw = JSON.parse(storage?.getItem(PREFS_KEY) || '{}') as Partial<Record<keyof ShelfPrefs, unknown>>
    return {
      sort: pick(raw.sort, SORT_OPTIONS.map(([v]) => v), DEFAULT_SHELF_PREFS.sort),
      group: pick(raw.group, GROUP_OPTIONS.map(([v]) => v), DEFAULT_SHELF_PREFS.group),
      view: pick(raw.view, ['grid', 'list'] as const, DEFAULT_SHELF_PREFS.view),
    }
  } catch {
    return DEFAULT_SHELF_PREFS
  }
}

export function writeShelfPrefs(storage: Pick<Storage, 'setItem'>, prefs: ShelfPrefs) {
  try {
    storage.setItem(PREFS_KEY, JSON.stringify(prefs))
  } catch {
    // 隐私模式等写不进去就算了，只是下次回到默认
  }
}

/* ─── 写法 ─── */

export function formatWords(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1).replace(/\.0$/, '')} 万`
  return n.toLocaleString('zh-CN')
}

/** 「6,774 字」「12.8 万字」 */
export function wordCount(n: number): string {
  return n >= 10000 ? `${formatWords(n)}字` : `${formatWords(n)} 字`
}

export function formatRelativeTime(value: string, now: Date = new Date()): string {
  const d = parseServerTime(value)
  if (!d) return ''
  const mins = Math.floor((now.getTime() - d.getTime()) / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return d.toLocaleDateString('zh-CN')
}

const TITLE_WRAPPERS: Record<string, string> = {
  '《': '》', '「': '」', '『': '』', '【': '】', '（': '）', '(': ')', '[': ']', '{': '}', '“': '”', '‘': '’', '"': '"', "'": "'",
}

/** 去掉包在书名外面的成对书名号 / 引号（作者常写成《书名》） */
export function displayTitle(title: string): string {
  let value = title.trim()
  while (value.length > 1) {
    const chars = Array.from(value)
    if (TITLE_WRAPPERS[chars[0]] !== chars[chars.length - 1]) break
    value = chars.slice(1, -1).join('').trim()
  }
  return value || title.trim() || '未命名作品'
}

/** 封面题签上的书名：先按字数截一刀，书封窄时再由样式按高度截（.shelf-label 的省略号） */
export function coverLabel(title: string, max = 12): string {
  const chars = Array.from(displayTitle(title))
  return chars.length > max ? `${chars.slice(0, max - 1).join('')}…` : chars.join('')
}

/* ─── 封面 ─── */

export interface CoverTone {
  name: string
  /** 底色渐变（左上 → 右下） */
  from: string
  via: string
  to: string
  /** 题签上的字 */
  ink: string
  /** 底纹的线 */
  line: string
  pattern: 'grid' | 'rings' | 'ruled' | 'hatch'
}

/** 六种淡色封面，全取自站内色板（青 / 朱 / 琥珀 / 黛 / 紫 / 苍）；按作品 id 固定一种，状态变了封面不变 */
export const COVER_TONES: CoverTone[] = [
  { name: '青', from: '#eef6f2', via: '#dfede6', to: '#c8e0d4', ink: '#1c463c', line: 'rgba(34, 87, 74, 0.16)', pattern: 'rings' },
  { name: '朱', from: '#fbf1ee', via: '#f6e1db', to: '#eecdc4', ink: '#6e2b24', line: 'rgba(138, 54, 44, 0.13)', pattern: 'grid' },
  { name: '琥珀', from: '#fbf6ec', via: '#f5e9cf', to: '#ebd5a8', ink: '#654416', line: 'rgba(128, 86, 26, 0.14)', pattern: 'ruled' },
  { name: '黛', from: '#f1f5f8', via: '#e1e9f0', to: '#cdd9e5', ink: '#31404f', line: 'rgba(62, 82, 101, 0.14)', pattern: 'hatch' },
  { name: '紫', from: '#f7f1f5', via: '#ede1e9', to: '#dfcbd9', ink: '#4a2e42', line: 'rgba(94, 58, 83, 0.14)', pattern: 'rings' },
  { name: '苍', from: '#f5f6f3', via: '#e8ebe5', to: '#d5dbd2', ink: '#2f3833', line: 'rgba(70, 83, 75, 0.14)', pattern: 'grid' },
]

export function coverToneOf(seed: string): CoverTone {
  let h = 0
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return COVER_TONES[h % COVER_TONES.length]
}

export function coverBackground(tone: CoverTone): CSSProperties {
  return { backgroundImage: `linear-gradient(145deg, ${tone.from} 0%, ${tone.via} 52%, ${tone.to} 100%)` }
}

/** 底纹：稿纸方格 / 同心圆 / 横线 / 斜线 */
export function coverPattern(tone: CoverTone): CSSProperties {
  const l = tone.line
  switch (tone.pattern) {
    case 'grid':
      return { backgroundImage: `linear-gradient(${l} 1px, transparent 1px), linear-gradient(90deg, ${l} 1px, transparent 1px)`, backgroundSize: '18px 18px' }
    case 'ruled':
      return { backgroundImage: `repeating-linear-gradient(to bottom, transparent 0 19px, ${l} 19px 20px)` }
    case 'hatch':
      return { backgroundImage: `repeating-linear-gradient(135deg, ${l} 0 1px, transparent 1px 12px)` }
    default:
      return {
        backgroundImage: [
          `radial-gradient(circle at 82% 70%, transparent 0 17%, ${l} 17% calc(17% + 1.5px), transparent calc(17% + 1.5px))`,
          `radial-gradient(circle at 82% 70%, transparent 0 29%, ${l} 29% calc(29% + 1.5px), transparent calc(29% + 1.5px))`,
          `radial-gradient(circle at 18% 92%, transparent 0 13%, ${l} 13% calc(13% + 1.5px), transparent calc(13% + 1.5px))`,
        ].join(', '),
      }
  }
}
