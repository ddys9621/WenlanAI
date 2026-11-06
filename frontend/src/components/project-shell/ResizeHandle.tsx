/**
 * 栏间拖动条：按住左右拖改宽度，松手存下；双击回默认宽度；聚焦后方向键每次 16px。
 * side = 被拖的那一栏在哪边：左栏往右拖变宽，右栏往左拖变宽。
 */
import { useRef, type KeyboardEvent, type PointerEvent } from 'react'
import { cn } from '@/lib/utils'
import { clampWidth, defaultWidth, type PaneLimits } from './paneSizes'

interface ResizeHandleProps {
  side: 'left' | 'right'
  width: number
  limits: PaneLimits
  label: string
  onResize: (width: number) => void
  onCommit: (width: number) => void
  className?: string
}

export function ResizeHandle({ side, width, limits, label, onResize, onCommit, className }: ResizeHandleProps) {
  const drag = useRef<{ x: number; width: number; last: number } | null>(null)

  const widthAt = (clientX: number) => {
    const d = drag.current
    if (!d) return width
    const delta = clientX - d.x
    return clampWidth(side === 'left' ? d.width + delta : d.width - delta, limits, window.innerWidth)
  }

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, width, last: width }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    const next = widthAt(e.clientX)
    if (next === drag.current.last) return
    drag.current.last = next
    onResize(next)
  }

  const finish = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    const next = drag.current.last
    drag.current = null
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    onCommit(next)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const grow = (e.key === 'ArrowRight') === (side === 'left')
    const next = clampWidth(width + (grow ? 16 : -16), limits, window.innerWidth)
    onResize(next)
    onCommit(next)
  }

  const reset = () => {
    const next = defaultWidth(limits, window.innerWidth)
    onResize(next)
    onCommit(next)
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={limits.min}
      aria-valuemax={limits.max}
      tabIndex={0}
      title={`${label}：拖动调整宽度，双击恢复默认`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
      onDoubleClick={reset}
      onKeyDown={onKeyDown}
      className={cn('ws-resize group', className)}
    >
      <span className="ws-resize-grip" aria-hidden />
    </div>
  )
}
