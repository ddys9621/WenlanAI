/**
 * 首页首屏：稿纸横线 + 两团柔光的底；徽标、大标题（「完本」下面一笔墨痕，进场时画出来）、介绍；
 * 「一句话开新书」输入框（占位字是轮播的灵感示例，下面的灵感胶囊点了就填进去），回车 / 点按钮带着这句话去灵感模式；
 * 次要入口、四个数字，最后是九步创作流程的工作台预览。
 */
import { useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, BookOpen, Download, ExternalLink, Feather, Sparkles } from 'lucide-react'
import type { User } from '@/types'
import { HomePreview } from './HomePreview'
import { GUIDE_URL, HERO_IDEAS, HERO_STATS, RELEASES_URL, entryHref, ideaHref } from './homeContent'
import { scrollToSection, usePrefersReducedMotion, useTypewriter } from './useHomeEffects'

export function HomeHero({ user }: { user: User | null | undefined }) {
  const navigate = useNavigate()
  const reduced = usePrefersReducedMotion()
  const [idea, setIdea] = useState('')
  const [focused, setFocused] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  // 输入框空着、没在打字时才轮播示例
  const typed = useTypewriter(HERO_IDEAS, !reduced && !focused && !idea)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    navigate(ideaHref(user, idea))
  }

  return (
    <section className="relative overflow-hidden px-5 pb-12 pt-28 sm:pb-20 md:px-8 md:pt-36">
      {/* 底纹：稿纸横线往四周淡出 + 两团柔光 */}
      <div className="home-ruled pointer-events-none absolute inset-0" aria-hidden />
      <div className="pointer-events-none absolute -left-40 top-10 h-[520px] w-[520px] rounded-full bg-brand/10 blur-3xl animate-float-soft motion-reduce:animate-none" aria-hidden />
      <div className="pointer-events-none absolute -right-32 top-48 h-[460px] w-[460px] rounded-full bg-gold/15 blur-3xl animate-float-soft [animation-delay:-3s] motion-reduce:animate-none" aria-hidden />

      <div className="relative mx-auto max-w-4xl text-center">
        <button
          onClick={() => scrollToSection('team')}
          className="home-fade-up group inline-flex items-center gap-2 rounded-full border border-surface-border-light bg-white/80 py-1 pl-1 pr-3.5 text-[12px] text-content-secondary shadow-xs backdrop-blur transition-colors hover:border-brand/30 hover:text-content"
        >
          <span className="rounded-full bg-brand px-2 py-0.5 text-[11px] font-medium text-white">新</span>
          三栏工作台 · 共创室能一键撤销整轮
          <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
        </button>

        <h1 className="home-fade-up mt-7 font-serif text-[34px] font-bold leading-[1.22] tracking-[0.01em] text-content [animation-delay:80ms] sm:text-[46px] md:text-[66px]">
          <span className="inline-block">AI 陪你写长篇，</span><br />
          <span className="inline-block">
            从一个灵感到
            <span className="relative inline-block text-brand">
              完本
              <svg className="home-brush absolute -bottom-2 left-[-6%] h-[0.32em] w-[112%]" viewBox="0 0 120 14" preserveAspectRatio="none" aria-hidden>
                <path d="M3 9.5C22 4.5 46 3.5 66 5.5C84 7.2 101 6.8 117 3.8" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" className="text-gold/80" />
              </svg>
            </span>
            。
          </span>
        </h1>

        <p className="home-fade-up mx-auto mt-6 max-w-2xl text-[15px] leading-7 text-content-secondary [animation-delay:160ms] sm:text-[16px] sm:leading-8">
          {'一支 AI 创作团队陪你把灵感落成世界观、人物、总纲、卷纲和章纲，再一章章写成正文；'
            + '伏笔、人物状态和前情按章整理，写到几百章也接得住。改动先给你看，你拍板了才写进书里。'}
        </p>

        {/* 一句话开新书 */}
        <form onSubmit={submit} className="home-fade-up mx-auto mt-9 max-w-2xl [animation-delay:240ms]">
          <div className="group relative flex items-center gap-2 rounded-full border border-surface-border bg-white p-1.5 pl-5 shadow-[0_18px_40px_-24px_rgba(29,36,32,0.45)] transition-all focus-within:border-brand/50 focus-within:shadow-[0_18px_44px_-20px_rgba(40,91,77,0.45)]">
            <Feather className="h-[18px] w-[18px] flex-none text-brand" />
            <label htmlFor="home-idea" className="sr-only">用一句话写下你的灵感</label>
            <div className="relative min-w-0 flex-1">
              <input
                ref={inputRef}
                id="home-idea"
                value={idea}
                onChange={(e) => setIdea(e.target.value)}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                maxLength={500}
                autoComplete="off"
                className="relative z-10 h-11 w-full !rounded-none !border-0 !bg-transparent !px-0 text-[15px] text-content outline-none !shadow-none"
              />
              {!idea && (
                <span className="pointer-events-none absolute inset-y-0 left-0 flex max-w-full items-center truncate text-[15px] text-content-tertiary" aria-hidden>
                  {focused ? '用一句话写下你的灵感……' : typed}
                  {!focused && !reduced && <i className="home-caret ml-0.5 inline-block h-[1.1em] w-px bg-content-tertiary" />}
                </span>
              )}
            </div>
            <button type="submit" className="hh-btn-primary h-11 flex-none rounded-full px-5 text-[15px] shadow-[0_8px_18px_-8px_rgba(40,91,77,0.8)] transition-transform hover:-translate-y-px">
              <Sparkles className="h-4 w-4" /><span className="hidden sm:inline">用这句开新书</span><span className="sm:hidden">开新书</span>
            </button>
          </div>
          {/* 手机上三条灵感各占一行，一样宽（长短不一地居中叠着看着乱） */}
          <div className="mt-3.5 flex flex-wrap justify-center gap-2 max-sm:flex-col max-sm:items-stretch max-sm:px-2">
            {HERO_IDEAS.slice(0, 3).map((text) => (
              <button
                key={text}
                type="button"
                onClick={() => { setIdea(text); inputRef.current?.focus() }}
                className="max-w-full truncate rounded-full border border-surface-border-light bg-white/70 px-3 py-1 text-[12px] text-content-secondary transition-all hover:-translate-y-px hover:border-brand/30 hover:text-content max-sm:py-1.5 max-sm:text-[13px]"
              >
                {text}
              </button>
            ))}
          </div>
        </form>

        {/* 手机上四个入口排成两列对齐的格子 */}
        <div className="home-fade-up mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-3 text-[14px] [animation-delay:320ms] max-sm:grid max-sm:grid-cols-2 max-sm:gap-x-2">
          <Link to={entryHref(user, '/projects')} className="group inline-flex items-center gap-1.5 font-medium text-brand max-sm:justify-center">
            {user ? '进入书架' : '开始创作'}<ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
          <Link to={entryHref(user, '/book-dissect')} className="inline-flex items-center gap-1.5 text-content-secondary transition-colors hover:text-content max-sm:justify-center">
            <BookOpen className="h-4 w-4" />拆书参考
          </Link>
          <a href={RELEASES_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-content-secondary transition-colors hover:text-content max-sm:justify-center">
            <Download className="h-4 w-4" />下载 Windows 桌面版
          </a>
          <a href={GUIDE_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-content-secondary transition-colors hover:text-content max-sm:justify-center">
            <ExternalLink className="h-4 w-4" />使用说明
          </a>
        </div>

        <dl className="home-fade-up mx-auto mt-10 grid max-w-3xl grid-cols-2 gap-y-5 [animation-delay:400ms] sm:grid-cols-4">
          {HERO_STATS.map(([value, label]) => (
            <div key={label} className="px-2 sm:border-l sm:border-surface-border-light sm:first:border-l-0">
              <dt className="sr-only">{label}</dt>
              <dd className="font-serif text-[28px] font-semibold leading-none text-content">{value}</dd>
              <dd className="mt-1.5 text-[12px] text-content-tertiary">{label}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="home-fade-up relative mt-16 [animation-delay:480ms]">
        <HomePreview />
      </div>
    </section>
  )
}
