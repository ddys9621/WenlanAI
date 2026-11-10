/**
 * 书封：按作品 id 固定一种淡色和底纹（状态变了封面不变），左侧一道书脊阴影，左上角竖排题签（线装书的样子）；
 * 大封面左下角标状态，定了目标字数的底边一条进度。
 */
import { cn } from '@/lib/utils'
import type { Project } from '@/types'
import { SHELF_STATE_LABEL, coverBackground, coverLabel, coverPattern, coverToneOf, progressOf, shelfStateOf, type ShelfState } from './shelf'

const STATE_DOT: Record<ShelfState, string> = {
  planning: 'bg-content-tertiary/70',
  writing: 'bg-brand',
  revising: 'bg-gold',
  completed: 'bg-cinnabar',
}

export function StateBadge({ state, className }: { state: ShelfState; className?: string }) {
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-[3px] text-[11px] leading-none', className)}>
      <i className={cn('h-1.5 w-1.5 rounded-full', STATE_DOT[state])} aria-hidden />
      {SHELF_STATE_LABEL[state]}
    </span>
  )
}

export function BookCover({ project, size = 'lg', className }: { project: Project; size?: 'lg' | 'sm'; className?: string }) {
  const tone = coverToneOf(project.id)
  const pct = progressOf(project)

  return (
    <div
      className={cn(
        'shelf-cover relative aspect-[3/4] overflow-hidden border border-black/[0.06] shadow-xs',
        size === 'lg' ? 'rounded-[14px]' : 'rounded-[10px]',
        className,
      )}
      style={coverBackground(tone)}
    >
      <div className="absolute inset-0" style={coverPattern(tone)} aria-hidden />
      <div className="absolute inset-y-0 left-0 w-[7%] bg-gradient-to-r from-black/[0.07] to-transparent" aria-hidden />
      <div className="absolute inset-y-0 left-[7%] w-px bg-white/60" aria-hidden />
      <div
        className={cn(
          'shelf-label absolute border bg-[#fffdf8]/90 font-serif font-semibold',
          size === 'lg' ? 'left-[16%] top-[9%] max-h-[66%]' : 'shelf-label--sm left-[18%] top-[8%] max-h-[84%]',
        )}
        style={{ borderColor: tone.line, color: tone.ink }}
      >
        {coverLabel(project.title)}
      </div>
      {size === 'lg' && (
        <StateBadge state={shelfStateOf(project)} className="absolute bottom-2.5 left-2.5 bg-white/80 text-[10px] text-content-secondary shadow-xs backdrop-blur-sm" />
      )}
      {pct !== null && (
        <div className="absolute inset-x-0 bottom-0 h-[3px] bg-black/[0.06]" title={`已写到目标字数的 ${pct}%`}>
          <div className="h-full bg-brand/70" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  )
}
