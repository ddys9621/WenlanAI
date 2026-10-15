/** 码字编辑器偏好（本机 localStorage，参考岚笺「版式」）：AI 补全、字体字号行距行宽、首行缩进 / 段间空行、横线、纸色、跟随输入。 */

export type CompletionLength = 'sentence' | 'paragraph'
export type EditorFont = 'serif' | 'song' | 'kai' | 'sans'
export type GuideStyle = 'off' | 'solid' | 'dashed'
export type PaperTheme = 'rice' | 'green' | 'gray' | 'night'

export interface EditorPrefs {
  /** AI 行内补全开关（默认关：作者主动打开才会在停笔时调用模型） */
  completion: boolean
  completionLength: CompletionLength
  fontFamily: EditorFont
  fontSize: number
  leading: number
  pageWidth: number
  firstLineIndent: boolean
  paragraphSpacing: boolean
  guideStyle: GuideStyle
  paper: PaperTheme
  /** 跟随输入：输入时当前行保持在视野中央 */
  typewriter: boolean
}

export const DEFAULT_EDITOR_PREFS: EditorPrefs = {
  completion: false,
  completionLength: 'paragraph',
  fontFamily: 'serif',
  fontSize: 17,
  leading: 1.9,
  pageWidth: 820,
  firstLineIndent: true,
  paragraphSpacing: true,
  guideStyle: 'solid',
  paper: 'rice',
  typewriter: false,
}

export const EDITOR_FONT_CSS: Record<EditorFont, string> = {
  serif: '"Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", "SimSun", serif',
  song: '"SimSun", "Songti SC", "STSong", serif',
  kai: '"KaiTi", "Kaiti SC", "STKaiti", serif',
  sans: '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif',
}

export const EDITOR_PREF_LIMITS = {
  fontSize: [14, 22],
  leading: [1.6, 2.4],
  pageWidth: [620, 980],
} as const

const KEY = 'wenlan-editor-prefs'

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>

function browserStorage(): StorageLike | null {
  return typeof localStorage === 'undefined' ? null : localStorage
}

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

function clamp(value: unknown, [min, max]: readonly [number, number], fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

export function loadEditorPrefs(storage: StorageLike | null = browserStorage()): EditorPrefs {
  const d = DEFAULT_EDITOR_PREFS
  let v: Partial<Record<keyof EditorPrefs, unknown>> = {}
  try {
    v = JSON.parse(storage?.getItem(KEY) || '{}') ?? {}
  } catch {
    return { ...d }
  }
  return {
    completion: bool(v.completion, d.completion),
    completionLength: pick(v.completionLength, ['sentence', 'paragraph'] as const, d.completionLength),
    fontFamily: pick(v.fontFamily, ['serif', 'song', 'kai', 'sans'] as const, d.fontFamily),
    fontSize: clamp(v.fontSize, EDITOR_PREF_LIMITS.fontSize, d.fontSize),
    leading: clamp(v.leading, EDITOR_PREF_LIMITS.leading, d.leading),
    pageWidth: clamp(v.pageWidth, EDITOR_PREF_LIMITS.pageWidth, d.pageWidth),
    firstLineIndent: bool(v.firstLineIndent, d.firstLineIndent),
    paragraphSpacing: bool(v.paragraphSpacing, d.paragraphSpacing),
    guideStyle: pick(v.guideStyle, ['off', 'solid', 'dashed'] as const, d.guideStyle),
    paper: pick(v.paper, ['rice', 'green', 'gray', 'night'] as const, d.paper),
    typewriter: bool(v.typewriter, d.typewriter),
  }
}

export function saveEditorPrefs(prefs: EditorPrefs, storage: StorageLike | null = browserStorage()): void {
  try {
    storage?.setItem(KEY, JSON.stringify(prefs))
  } catch {
    /* 隐私模式等写不进 localStorage：仅本次会话生效 */
  }
}
