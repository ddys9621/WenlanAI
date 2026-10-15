/** 稿纸「版式」弹层（参考岚笺）：只改变阅读与输入方式；「一键排版」才会整理文字。偏好存本机。 */
import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import { EDITOR_PREF_LIMITS, type EditorFont, type EditorPrefs, type GuideStyle, type PaperTheme } from '@/utils/editorPrefs'

const FONTS: [EditorFont, string][] = [['serif', '思源宋体'], ['song', '系统宋体'], ['kai', '系统楷体'], ['sans', '系统黑体']]
const GUIDES: [GuideStyle, string][] = [['off', '无'], ['solid', '实线'], ['dashed', '虚线']]
const PAPERS: [PaperTheme, string, string][] = [['rice', '米纸', '#fffdf7'], ['green', '护眼', '#edf4e9'], ['gray', '雾灰', '#eff1ef'], ['night', '夜墨', '#242a28']]

interface Props {
  prefs: EditorPrefs
  onChange: (patch: Partial<EditorPrefs>) => void
  onReset: () => void
  onClose: () => void
}

export function ManuscriptLayoutPanel({ prefs, onChange, onReset, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [onClose])

  const range = (key: 'fontSize' | 'leading' | 'pageWidth', step: number) => {
    const [min, max] = EDITOR_PREF_LIMITS[key]
    return (
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={prefs[key]}
        onChange={(e) => onChange({ [key]: Number(e.target.value) })}
        className="w-full accent-brand"
      />
    )
  }

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="正文版式"
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}
      className="absolute left-0 top-full z-30 mt-1.5 w-[min(26rem,calc(100vw-2rem))] rounded border border-surface-border bg-white px-4 shadow-lg"
    >
      <header className="flex items-start justify-between gap-3 border-b border-surface-border-light py-3">
        <div>
          <p className="text-sm font-semibold text-content">正文版式</p>
          <p className="mt-0.5 text-xs text-content-tertiary">只改变阅读与输入方式；「一键排版」才会整理文字。</p>
        </div>
        <button onClick={onClose} className="hh-btn-ghost hh-btn-sm">关闭</button>
      </header>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 py-3 text-xs text-content-secondary">
        <label className="grid gap-1.5">
          字体
          <select
            value={prefs.fontFamily}
            onChange={(e) => onChange({ fontFamily: e.target.value as EditorFont })}
            className="h-8 rounded border border-surface-border bg-white px-2 text-xs text-content"
          >
            {FONTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="grid gap-1.5">
          <span>字号 <em className="not-italic text-content-tertiary tabular-nums">{prefs.fontSize}px</em></span>
          {range('fontSize', 1)}
        </label>
        <label className="grid gap-1.5">
          <span>行距 <em className="not-italic text-content-tertiary tabular-nums">{prefs.leading.toFixed(2)}</em></span>
          {range('leading', 0.05)}
        </label>
        <label className="grid gap-1.5">
          <span>行宽 <em className="not-italic text-content-tertiary tabular-nums">{prefs.pageWidth}px</em></span>
          {range('pageWidth', 20)}
        </label>
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2 pb-3 text-xs text-content">
        <label className="flex cursor-pointer items-center gap-1.5">
          <input type="checkbox" checked={prefs.firstLineIndent} onChange={(e) => onChange({ firstLineIndent: e.target.checked })} className="accent-brand" />
          首行缩进
        </label>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input type="checkbox" checked={prefs.paragraphSpacing} onChange={(e) => onChange({ paragraphSpacing: e.target.checked })} className="accent-brand" />
          段间空行
        </label>
      </div>
      <div className="flex items-center gap-3 border-t border-surface-border-light py-3 text-xs text-content-secondary">
        <span className="w-8 shrink-0">横线</span>
        <div className="flex gap-1.5">
          {GUIDES.map(([value, label]) => (
            <button
              key={value}
              onClick={() => onChange({ guideStyle: value })}
              aria-pressed={prefs.guideStyle === value}
              className={cn('hh-chip px-2.5 py-1', prefs.guideStyle === value && 'hh-chip--active')}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-3 pb-3 text-xs text-content-secondary">
        <span className="w-8 shrink-0">纸色</span>
        <div className="grid flex-1 grid-cols-4 gap-1.5">
          {PAPERS.map(([value, label, color]) => (
            <button
              key={value}
              onClick={() => onChange({ paper: value })}
              aria-pressed={prefs.paper === value}
              className={cn(
                'flex flex-col items-center gap-1 rounded border px-1 py-1.5 text-[11px]',
                prefs.paper === value ? 'border-brand text-brand' : 'border-surface-border text-content-secondary hover:border-brand/50',
              )}
            >
              <i className="h-4 w-full rounded-sm border border-black/10" style={{ background: color }} />
              {label}
            </button>
          ))}
        </div>
      </div>
      <footer className="flex items-center justify-between gap-3 border-t border-surface-border-light py-2.5 text-[11px] text-content-tertiary">
        <span>回车按「段间空行 / 首行缩进」续下一段，Shift+回车普通换行。</span>
        <button onClick={onReset} className="hh-btn-ghost hh-btn-sm shrink-0">恢复默认</button>
      </footer>
    </div>
  )
}
