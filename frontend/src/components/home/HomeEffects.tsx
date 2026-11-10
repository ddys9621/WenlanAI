/** 首页的动效小部件：滚动显现、回到顶部、无限滚动的一行胶囊。 */
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { ArrowUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useInView } from './useHomeEffects'

/** 滚到眼前时淡入上浮；delay 用来给一排卡片错开节奏 */
export function Reveal({ children, delay = 0, className, as: Tag = 'div' }: {
  children: ReactNode; delay?: number; className?: string; as?: 'div' | 'li' | 'section'
}) {
  const [ref, seen] = useInView<HTMLDivElement>()
  return (
    <Tag
      ref={ref as never}
      className={cn('home-reveal', seen && 'home-reveal--in', className)}
      style={{ transitionDelay: seen ? `${delay}ms` : undefined } as CSSProperties}
    >
      {children}
    </Tag>
  )
}

/** 往下滚过一屏多出现，点了平滑回到顶部 */
export function BackToTop() {
  const [show, setShow] = useState(false)
  useEffect(() => {
    const sync = () => setShow(window.scrollY > 900)
    sync()
    window.addEventListener('scroll', sync, { passive: true })
    return () => window.removeEventListener('scroll', sync)
  }, [])
  return (
    <button
      onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
      className={cn(
        // 手机上小一号、贴边一点，少压住正文
        'fixed bottom-6 right-6 z-40 flex h-11 w-11 items-center justify-center rounded-full border border-surface-border bg-white/90 text-content shadow-md backdrop-blur transition-all duration-300 hover:-translate-y-0.5 hover:text-brand max-sm:bottom-4 max-sm:right-3 max-sm:h-10 max-sm:w-10',
        show ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-3 opacity-0',
      )}
      aria-label="回到顶部"
      title="回到顶部"
    >
      <ArrowUp className="h-4 w-4" />
    </button>
  )
}

/** 一行无限滚动的胶囊（内容复制一份接在后面，动画走一半正好接上）；鼠标停上去暂停 */
export function Marquee({ items, reverse = false, seconds = 40 }: { items: string[]; reverse?: boolean; seconds?: number }) {
  return (
    <div className="home-marquee group relative overflow-hidden" aria-hidden={reverse}>
      <ul
        className="flex w-max gap-3 group-hover:[animation-play-state:paused]"
        style={{ animation: `home-marquee ${seconds}s linear infinite${reverse ? ' reverse' : ''}` }}
      >
        {[...items, ...items].map((item, i) => (
          <li key={`${item}-${i}`} className="whitespace-nowrap rounded-full border border-surface-border-light bg-white/80 px-5 py-2.5 font-serif text-[15px] text-content shadow-xs">
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}
