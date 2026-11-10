/**
 * 首页顶栏：在首屏上是透明的，往下滚变成带毛玻璃的实底；滚到哪一节，对应的链接就亮起来；
 * 点链接平滑滚过去（不改地址里的 #，免得刷新后停在半截）；窄屏收成菜单按钮。
 */
import { useEffect, useState, type MouseEvent } from 'react'
import { Link } from 'react-router-dom'
import { Github, Menu, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { BrandLogo } from '@/components/ui/BrandLogo'
import type { User } from '@/types'
import { loginHref } from '@/utils/loginRoute'
import { HOME_NAV, REPO_URL, SISTER_PROJECT, SISTER_SECTION_ID, entryHref } from './homeContent'
import { scrollToSection, useScrolled, useScrollSpy } from './useHomeEffects'

const NAV_IDS = HOME_NAV.map(([id]) => id)

export function HomeNav({ user }: { user: User | null | undefined }) {
  const scrolled = useScrolled()
  const active = useScrollSpy(NAV_IDS)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const close = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [open])

  const go = (e: MouseEvent, id: string) => {
    e.preventDefault()
    setOpen(false)
    scrollToSection(id)
  }

  return (
    <header
      className={cn(
        'fixed inset-x-0 top-0 z-50 transition-all duration-300',
        scrolled || open
          ? 'border-b border-surface-border-light bg-surface-paper/80 shadow-[0_8px_30px_-24px_rgba(29,36,32,0.35)] backdrop-blur-xl'
          : 'border-b border-transparent bg-transparent',
      )}
    >
      <div className={cn('mx-auto flex max-w-6xl items-center gap-6 px-5 transition-all duration-300 md:px-8', scrolled ? 'h-14' : 'h-16')}>
        <Link to="/" className="group flex items-center gap-2.5" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
          <BrandLogo size="sm" className="transition-transform duration-300 group-hover:-rotate-6" />
          <span className="font-serif text-[17px] font-semibold text-content">文澜 AI</span>
        </Link>
        <nav className="hidden items-center gap-0.5 lg:flex" aria-label="首页导航">
          {HOME_NAV.filter(([id]) => id !== SISTER_SECTION_ID).map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              onClick={(e) => go(e, id)}
              aria-current={active === id ? 'true' : undefined}
              className={cn(
                'relative rounded-full px-3 py-1.5 text-[14px] transition-colors',
                active === id ? 'bg-white text-content shadow-xs' : 'text-content-secondary hover:text-content',
              )}
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-1.5">
          <a
            href={`#${SISTER_SECTION_ID}`}
            onClick={(e) => go(e, SISTER_SECTION_ID)}
            aria-current={active === SISTER_SECTION_ID ? 'true' : undefined}
            title={`${SISTER_PROJECT.name} · ${SISTER_PROJECT.kind}`}
            className={cn(
              'hidden h-9 items-center gap-1.5 rounded-full border pl-1.5 pr-3 text-[13px] transition-colors hover:border-cinnabar/25 hover:bg-white hover:text-content sm:inline-flex',
              active === SISTER_SECTION_ID ? 'border-cinnabar/25 bg-white text-content shadow-xs' : 'border-surface-border-light bg-white/60 text-content-secondary',
            )}
          >
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-cinnabar font-serif text-[12px] font-bold leading-none text-white" aria-hidden>绘</span>
            {SISTER_PROJECT.name}
          </a>
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="hidden h-9 w-9 items-center justify-center rounded-full text-content-secondary transition-colors hover:bg-white hover:text-content sm:inline-flex" title="GitHub" aria-label="GitHub">
            <Github className="h-[18px] w-[18px]" />
          </a>
          {user ? (
            <>
              <span className="hidden max-w-[8rem] truncate px-2 text-[13px] text-content-secondary md:inline" title={user.username}>{user.display_name || user.username}</span>
              <Link to="/projects" className="hh-btn-primary h-9 rounded-full px-4 text-[14px] shadow-[0_6px_16px_-8px_rgba(40,91,77,0.7)] transition-transform hover:-translate-y-px">进入书架</Link>
            </>
          ) : (
            <>
              <Link to={loginHref('/projects')} className="hidden rounded-full px-3 py-1.5 text-[14px] text-content-secondary transition-colors hover:bg-white hover:text-content sm:inline-block">登录</Link>
              <Link to={entryHref(user, '/projects')} className="hh-btn-primary h-9 rounded-full px-4 text-[14px] shadow-[0_6px_16px_-8px_rgba(40,91,77,0.7)] transition-transform hover:-translate-y-px">开始创作</Link>
            </>
          )}
          <button
            onClick={() => setOpen((v) => !v)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-full text-content-secondary hover:bg-white hover:text-content lg:hidden"
            aria-expanded={open}
            aria-label={open ? '收起菜单' : '展开菜单'}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>
      {/* 窄屏菜单 */}
      <div className={cn('grid transition-[grid-template-rows] duration-300 lg:hidden', open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
        <nav className="overflow-hidden" aria-label="首页导航（菜单）">
          <div className="mx-auto grid max-w-6xl grid-cols-2 gap-1 px-5 pb-4 pt-1 sm:grid-cols-3">
            {HOME_NAV.map(([id, label]) => (
              <a key={id} href={`#${id}`} onClick={(e) => go(e, id)} className={cn('flex items-center gap-2 rounded-xl px-3 py-2.5 text-[14px]', active === id ? 'bg-white text-content' : 'text-content-secondary hover:bg-white')}>
                {id === SISTER_SECTION_ID && <span className="flex h-5 w-5 flex-none items-center justify-center rounded bg-cinnabar font-serif text-[11px] font-bold leading-none text-white" aria-hidden>绘</span>}
                {label}
              </a>
            ))}
            {!user && <Link to={loginHref('/projects')} className="rounded-xl px-3 py-2.5 text-[14px] text-content-secondary hover:bg-white sm:hidden">登录</Link>}
          </div>
        </nav>
      </div>
    </header>
  )
}
