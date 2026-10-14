import { useId } from 'react'
import { cn } from '@/lib/utils'

interface BrandLogoProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const SIZE_MAP = {
  sm: 'h-9 w-9 rounded',
  md: 'h-10 w-10 rounded',
  lg: 'h-12 w-12 rounded-lg',
} as const

// 翻开的两页书 + 一道从左页起笔、越过书脊、右上提笔出页的笔迹（viewBox 256）
const PAGES =
  'M48 84C76 72 104 76 122 94V196C104 178 76 174 48 186ZM208 84C180 72 152 76 134 94V196C152 178 180 174 208 186Z'
const STROKE = 'M74 156C100 132 118 158 136 136C154 114 176 90 212 60'
const STROKE_WIDTH = 16

export function BrandLogo({ size = 'md', className }: BrandLogoProps) {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const notStroke = `hh-logo-${id}-s`
  const notPages = `hh-logo-${id}-p`

  return (
    <span
      className={cn(
        'relative inline-flex items-center justify-center overflow-hidden bg-gradient-to-br from-brand-600 via-brand to-brand-400 text-white ring-1 ring-inset ring-white/10',
        SIZE_MAP[size],
        className,
      )}
      aria-hidden="true"
    >
      <span className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.22),transparent_38%)]" />
      <span className="absolute bottom-0 right-0 h-1 w-1/3 bg-signal" />
      <svg viewBox="0 0 256 256" fill="none" className="relative h-[66%] w-[66%]">
        <defs>
          <mask id={notStroke} maskUnits="userSpaceOnUse" x="0" y="0" width="256" height="256">
            <rect width="256" height="256" fill="#fff" />
            <path d={STROKE} stroke="#000" strokeWidth={STROKE_WIDTH} strokeLinecap="round" />
          </mask>
          <mask id={notPages} maskUnits="userSpaceOnUse" x="0" y="0" width="256" height="256">
            <rect width="256" height="256" fill="#fff" />
            <path d={PAGES} fill="#000" />
          </mask>
        </defs>
        <path d={PAGES} fill="currentColor" mask={`url(#${notStroke})`} />
        <path d={STROKE} stroke="currentColor" strokeWidth={STROKE_WIDTH} strokeLinecap="round" mask={`url(#${notPages})`} />
      </svg>
    </span>
  )
}
