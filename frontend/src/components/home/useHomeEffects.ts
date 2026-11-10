/** 首页的交互小工具：滚动状态、当前在看哪一节、进入视口、打字机。都在浏览器里才生效（服务端渲染 / 测试里按「静止」处理）。 */
import { useEffect, useRef, useState, type RefObject } from 'react'

const hasWindow = () => typeof window !== 'undefined'

/** 平滑滚到某一节（让出顶栏的高度） */
export function scrollToSection(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 72, behavior: 'smooth' })
}

/** 系统设了「减少动态效果」：打字机、演示动画直接给最终状态 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => hasWindow() && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!mq) return
    const sync = () => setReduced(mq.matches)
    mq.addEventListener?.('change', sync)
    return () => mq.removeEventListener?.('change', sync)
  }, [])
  return reduced
}

/** 页面滚过 threshold 像素（顶栏从透明变实底） */
export function useScrolled(threshold = 8): boolean {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const sync = () => setScrolled(window.scrollY > threshold)
    sync()
    window.addEventListener('scroll', sync, { passive: true })
    return () => window.removeEventListener('scroll', sync)
  }, [threshold])
  return scrolled
}

/** 当前看到的是哪一节：顶边过了 offset 的最后一节（顶栏高亮对应链接） */
export function useScrollSpy(ids: readonly string[], offset = 140): string | null {
  const [active, setActive] = useState<string | null>(null)
  useEffect(() => {
    let frame = 0
    const sync = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        let hit: string | null = null
        for (const id of ids) {
          const el = document.getElementById(id)
          if (el && el.getBoundingClientRect().top <= offset) hit = id
        }
        // 滚到底：最后一节没机会过线，也算它
        if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) hit = ids[ids.length - 1] ?? hit
        setActive(hit)
      })
    }
    sync()
    window.addEventListener('scroll', sync, { passive: true })
    window.addEventListener('resize', sync)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', sync)
      window.removeEventListener('resize', sync)
    }
  }, [ids, offset])
  return active
}

/** 进入视口一次就记住（滚动显现）；没有 IntersectionObserver 时直接算看见了 */
export function useInView<T extends Element>(rootMargin = '0px 0px -12% 0px'): [RefObject<T>, boolean] {
  const ref = useRef<T>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || seen) return
    if (typeof IntersectionObserver === 'undefined') {
      setSeen(true)
      return
    }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setSeen(true)
        io.disconnect()
      }
    }, { rootMargin })
    io.observe(el)
    return () => io.disconnect()
  }, [rootMargin, seen])
  return [ref, seen]
}

/** 打字机：在几句话之间循环，逐字打出、停一会儿、再逐字删掉；enabled=false 时停在第一句 */
export function useTypewriter(items: readonly string[], enabled = true, { typeMs = 85, holdMs = 1800, eraseMs = 30 } = {}): string {
  const [index, setIndex] = useState(0)
  const [length, setLength] = useState(0)
  const [erasing, setErasing] = useState(false)
  const current = items[index % items.length] ?? ''

  useEffect(() => {
    if (!enabled || !items.length) return
    let timer: ReturnType<typeof setTimeout>
    if (!erasing && length < current.length) timer = setTimeout(() => setLength(length + 1), typeMs)
    else if (!erasing) timer = setTimeout(() => setErasing(true), holdMs)
    else if (length > 0) timer = setTimeout(() => setLength(length - 1), eraseMs)
    else timer = setTimeout(() => { setErasing(false); setIndex((i) => (i + 1) % items.length) }, 300)
    return () => clearTimeout(timer)
  }, [current.length, enabled, erasing, eraseMs, holdMs, items.length, length, typeMs])

  return enabled ? current.slice(0, length) : current
}
