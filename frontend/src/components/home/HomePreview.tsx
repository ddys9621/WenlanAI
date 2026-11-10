/**
 * 首页的工作台预览：上面一排九步创作流程，点哪一步，下面的三栏工作台（左栏页签与入口 ｜ 中栏页面 ｜ 右栏智能助笔）
 * 就换成那一步的样子。内容是演示用的静态示例（homeContent.PREVIEW_STEPS），不调接口。
 * - 没点过时自动播放：当前那一格底下走一条进度线，走完换下一步（进度线是 CSS 动画，鼠标停在预览上就暂停，计时跟着停）；
 *   点过任何一步、或系统设了「减少动态效果」就不再自动换。
 * - 右栏照真实的智能助笔演一遍：作者的话 → 成员在想 → 先说一句在做什么 → 回执转圈再打勾 → 回复逐字打出。
 * - ← → 键、两侧箭头切换上一步 / 下一步。
 */
import { useEffect, useState, type KeyboardEvent } from 'react'
import { Check, ChevronLeft, ChevronRight, FileDown, FileText, Loader2, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { PREVIEW_STEPS, SIDEBAR_ITEMS, type PreviewBlock } from './homeContent'
import { usePrefersReducedMotion } from './useHomeEffects'

const TABS = ['设定', '大纲', '目录', '资料'] as const
const AUTO_MS = 7000
/** 右栏演示的节奏：成员开口、回执开跑、回执完成（毫秒）；之后回复逐字打出 */
const PHASE_AT = [500, 1100, 2000] as const
const DONE = 9
const isBrowser = typeof window !== 'undefined'

function Block({ block }: { block: PreviewBlock }) {
  if (block.kind === 'fields') {
    return (
      <dl className="space-y-2.5">
        {block.rows.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-surface-border-light bg-white px-3.5 py-2.5">
            <dt className="text-[11px] text-content-tertiary">{label}</dt>
            <dd className="mt-0.5 text-[13px] leading-6 text-content">{value}</dd>
          </div>
        ))}
      </dl>
    )
  }
  if (block.kind === 'cards') {
    return (
      <ul className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {block.items.map((c) => (
          <li key={c.name} className="rounded-lg border border-surface-border-light bg-white px-3.5 py-3">
            <p className="flex items-center gap-2">
              <span className="font-serif text-[14px] font-semibold text-content">{c.name}</span>
              <span className="rounded-full bg-brand-50 px-2 py-0.5 text-[10px] text-brand-600">{c.tag}</span>
            </p>
            <p className="mt-1 text-[12px] leading-5 text-content-secondary">{c.desc}</p>
          </li>
        ))}
      </ul>
    )
  }
  if (block.kind === 'outline') {
    return (
      <ol className="space-y-2">
        {block.items.map((o) => (
          <li key={o.no} className="flex items-start gap-3 rounded-lg border border-surface-border-light bg-white px-3.5 py-2.5">
            <span className="mt-0.5 w-14 flex-none text-[11px] text-content-tertiary">{o.no}</span>
            <span className="min-w-0 flex-1">
              <span className="font-serif text-[13px] font-semibold text-content">{o.title}</span>
              <span className="mt-0.5 block text-[12px] leading-5 text-content-secondary">{o.desc}</span>
            </span>
            <span className={cn('flex-none rounded-full px-2 py-0.5 text-[10px]', o.done ? 'bg-brand-50 text-brand-600' : 'bg-gold-50 text-gold-500')}>
              {o.done ? '已确认' : '草拟待确认'}
            </span>
          </li>
        ))}
      </ol>
    )
  }
  if (block.kind === 'prose') {
    return (
      <div className="rounded-lg border border-[rgba(185,174,155,0.46)] bg-[#fffdf7] px-5 py-4 font-serif">
        {block.paragraphs.map((p) => (
          <p key={p} className="indent-[2em] text-[14px] leading-8 text-[#262b28]">{p}</p>
        ))}
      </div>
    )
  }
  if (block.kind === 'diff') {
    return (
      <ul className="space-y-2.5">
        {block.pairs.map((d) => (
          <li key={d.before} className="rounded-lg border border-surface-border-light bg-white px-3.5 py-3 font-serif text-[13px] leading-7">
            <del className="block bg-cinnabar-wash/70 px-1 text-cinnabar decoration-cinnabar/60">{d.before}</del>
            <ins className="mt-1 block bg-brand-50 px-1 text-brand-700 no-underline">{d.after}</ins>
          </li>
        ))}
      </ul>
    )
  }
  if (block.kind === 'promises') {
    return (
      <ul className="space-y-2">
        {block.items.map((p) => (
          <li key={p.title} className="flex items-center gap-2.5 rounded-lg border border-surface-border-light bg-white px-3.5 py-2.5 text-[12px]">
            <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-content-secondary">{p.type}</span>
            <span className="min-w-0 flex-1 truncate">
              <span className="text-[13px] text-content">{p.title}</span>
              <span className={cn('ml-2', p.urgent ? 'text-cinnabar' : 'text-gold-500')}>{p.reason}</span>
            </span>
            <span className="flex-none text-[11px] text-content-tertiary">本章回收 · 强化 · 暂停</span>
          </li>
        ))}
      </ul>
    )
  }
  return (
    <ul className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
      {block.items.map((e) => (
        <li key={e.name} className="rounded-lg border border-surface-border-light bg-white px-3.5 py-3">
          <p className="flex items-center gap-1.5 text-[13px] font-medium text-content"><FileDown className="h-3.5 w-3.5 text-brand" />{e.name}</p>
          <p className="mt-1 text-[12px] leading-5 text-content-secondary">{e.desc}</p>
        </li>
      ))}
    </ul>
  )
}

export function HomePreview({ initial = 0 }: { initial?: number }) {
  const reduced = usePrefersReducedMotion()
  const [index, setIndex] = useState(initial)
  const [auto, setAuto] = useState(true)
  const [hover, setHover] = useState(false)
  // 右栏演示到哪一步；浏览器里从头演，服务端渲染 / 测试直接给完整内容
  const [phase, setPhase] = useState(isBrowser ? 0 : DONE)
  const [chars, setChars] = useState(isBrowser ? 0 : Number.MAX_SAFE_INTEGER)
  const step = PREVIEW_STEPS[index]
  const playing = auto && !reduced

  useEffect(() => {
    if (reduced) {
      setPhase(DONE)
      setChars(Number.MAX_SAFE_INTEGER)
      return
    }
    setPhase(0)
    setChars(0)
    const timers = PHASE_AT.map((ms, i) => setTimeout(() => setPhase(i + 1), ms))
    return () => timers.forEach(clearTimeout)
  }, [index, reduced])

  useEffect(() => {
    if (phase < 3 || chars >= step.reply.length) return
    const timer = setTimeout(() => setChars((c) => c + 2), 34)
    return () => clearTimeout(timer)
  }, [chars, phase, step.reply.length])

  const go = (i: number, stopAuto = true) => {
    setIndex((i + PREVIEW_STEPS.length) % PREVIEW_STEPS.length)
    if (stopAuto) setAuto(false)
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') { e.preventDefault(); go(index + 1) }
    if (e.key === 'ArrowLeft') { e.preventDefault(); go(index - 1) }
  }

  const replyShown = phase >= 3 ? step.reply.slice(0, chars) : ''
  const typing = phase >= 3 && chars < step.reply.length

  return (
    <div>
      {/* 九步：宽屏一排居中折行；手机上排成 3 × 3 一样宽的格子（折行时一行 2 个、一行 3 个、最后剩 1 个，看着乱） */}
      <div className="flex flex-wrap justify-center gap-2 max-sm:grid max-sm:grid-cols-3 max-sm:gap-1.5" role="tablist" aria-label="创作流程（← → 切换）" onKeyDown={onKeyDown}>
        {PREVIEW_STEPS.map((s, i) => (
          <button
            key={s.key}
            role="tab"
            aria-selected={i === index}
            tabIndex={i === index ? 0 : -1}
            onClick={() => go(i)}
            className={cn(
              'relative inline-flex h-9 items-center gap-2 overflow-hidden rounded-full border px-3.5 text-[13px] transition-all duration-200',
              'max-sm:min-w-0 max-sm:justify-center max-sm:gap-1 max-sm:px-1.5 max-sm:text-[12px]',
              i === index
                ? 'border-brand/40 bg-brand-50 text-brand-700 shadow-[0_6px_16px_-10px_rgba(40,91,77,0.6)]'
                : 'border-surface-border-light bg-white/70 text-content-secondary hover:-translate-y-px hover:border-surface-border hover:text-content',
            )}
          >
            <span className={cn(
              'flex h-5 w-5 flex-none items-center justify-center rounded-full text-[11px] tabular-nums transition-colors max-sm:h-[18px] max-sm:w-[18px] max-sm:text-[10px]',
              i === index ? 'bg-brand text-white' : i < index ? 'bg-brand-100 text-brand-600' : 'bg-surface text-content-tertiary',
            )}>
              {i < index ? <Check className="h-3 w-3" /> : i + 1}
            </span>
            <span className="truncate">{s.label}</span>
            {/* 自动播放的进度线：走完换下一步；鼠标停在预览上暂停 */}
            {i === index && playing && (
              <span
                key={`${s.key}-progress`}
                className="home-pill-progress absolute inset-x-0 bottom-0 h-[2px] origin-left bg-brand"
                style={{ animationDuration: `${AUTO_MS}ms`, animationPlayState: hover ? 'paused' : 'running' }}
                onAnimationEnd={() => go(index + 1, false)}
                aria-hidden
              />
            )}
          </button>
        ))}
      </div>

      <div className="relative mx-auto mt-7 max-w-6xl">
        {/* 两侧箭头 */}
        <button onClick={() => go(index - 1)} className="absolute -left-14 top-1/2 z-10 hidden h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full border border-surface-border bg-white/90 text-content-secondary shadow-sm transition-all hover:-translate-x-0.5 hover:text-brand xl:flex" aria-label="上一步">
          <ChevronLeft className="h-5 w-5" />
        </button>
        <button onClick={() => go(index + 1)} className="absolute -right-14 top-1/2 z-10 hidden h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full border border-surface-border bg-white/90 text-content-secondary shadow-sm transition-all hover:translate-x-0.5 hover:text-brand xl:flex" aria-label="下一步">
          <ChevronRight className="h-5 w-5" />
        </button>

        {/* 外圈一层淡淡的光 */}
        <div className="pointer-events-none absolute -inset-px rounded-[18px] bg-gradient-to-b from-brand/25 via-surface-border/40 to-gold/20" aria-hidden />
        <div
          className="relative overflow-hidden rounded-2xl bg-surface-paper shadow-[0_30px_80px_-30px_rgba(29,36,32,0.35)]"
          onMouseEnter={() => setHover(true)}
          onMouseLeave={() => setHover(false)}
          aria-live="polite"
        >
          {/* 窗口顶栏 */}
          <div className="flex h-11 items-center gap-3 border-b border-surface-border-light bg-white/80 px-4">
            <span className="flex gap-1.5" aria-hidden>
              <i className="h-2.5 w-2.5 rounded-full bg-[#ef8f7b]" /><i className="h-2.5 w-2.5 rounded-full bg-[#f2c46b]" /><i className="h-2.5 w-2.5 rounded-full bg-[#8cc49f]" />
            </span>
            <span className="font-serif text-[13px] font-semibold text-content">夜航灯</span>
            <span className="hidden text-[12px] text-content-tertiary sm:inline">玄幻 · 成长 · 第一卷</span>
            <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-2.5 py-0.5 text-[11px] text-brand-700">
              <i className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand motion-reduce:animate-none" />第 {index + 1} / {PREVIEW_STEPS.length} 步 · {step.label}
            </span>
          </div>

          {/* 手机上只剩中栏：矮一些，底下淡出（内容长的那几步自然截断，内容短的不再空出一大块） */}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-14 bg-gradient-to-t from-surface-paper to-transparent sm:hidden" aria-hidden />
          <div className="grid h-[400px] grid-cols-1 sm:h-[460px] md:grid-cols-[176px_minmax(0,1fr)] lg:grid-cols-[176px_minmax(0,1fr)_300px]">
            {/* 左栏 */}
            <aside className="hidden flex-col border-r border-surface-border-light bg-surface-paper md:flex">
              <div className="grid grid-cols-4 gap-0.5 border-b border-surface-border-light p-1.5">
                {TABS.map((t) => (
                  <span key={t} className={cn('rounded-md py-1 text-center text-[11px] transition-colors duration-300', t === step.tab ? 'bg-brand-50 font-medium text-brand-700' : 'text-content-tertiary')}>
                    {t}
                  </span>
                ))}
              </div>
              <ul key={step.tab} className="animate-fade-in space-y-1 p-2">
                {SIDEBAR_ITEMS[step.tab].map((item) => (
                  <li
                    key={item}
                    className={cn(
                      'truncate rounded-md px-2.5 py-1.5 text-[12px] transition-all duration-300',
                      item === step.nav ? 'border border-brand/30 bg-white font-medium text-content shadow-xs' : 'border border-transparent text-content-secondary',
                    )}
                  >
                    {item}
                  </li>
                ))}
              </ul>
            </aside>

            {/* 中栏 */}
            <main className="min-w-0 overflow-hidden">
              <header key={`${step.key}-head`} className="animate-fade-in flex items-center gap-2 border-b border-surface-border-light px-5 py-3">
                <FileText className="h-4 w-4 text-brand" />
                <span className="font-serif text-[15px] font-semibold text-content">{step.title}</span>
                <span className="truncate text-[12px] text-content-tertiary">{step.desc}</span>
              </header>
              <div key={step.key} className="animate-slide-up space-y-3 px-5 py-4">
                {step.blocks.map((b, i) => <Block key={i} block={b} />)}
              </div>
            </main>

            {/* 右栏：智能助笔，照真实的样子演一遍 */}
            <aside className="hidden min-w-0 flex-col border-l border-surface-border-light bg-white/60 lg:flex">
              <div className="flex h-10 items-center gap-1.5 border-b border-surface-border-light px-3 text-[12px] font-medium text-content">
                <Sparkles className="h-3.5 w-3.5 text-brand" />智能助笔 · 共创室
              </div>
              <div key={step.key} className="flex-1 space-y-3 overflow-hidden px-3 py-3">
                <p className="animate-slide-up ml-auto w-fit max-w-[90%] rounded-xl bg-surface px-3 py-2 text-[12px] leading-5 text-content">{step.ask}</p>
                <p className="flex items-center gap-1.5 text-[12px] font-medium text-content">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-50 text-[10px] text-brand-700">{step.member.slice(0, 1)}</span>
                  {step.member}
                  {phase < 1 && (
                    <span className="ml-1 inline-flex gap-0.5" aria-label="正在想">
                      {[0, 1, 2].map((d) => <i key={d} className="h-1 w-1 animate-typing-dot rounded-full bg-content-tertiary" style={{ animationDelay: `${d * 160}ms` }} />)}
                    </span>
                  )}
                </p>
                {phase >= 1 && <p className="animate-fade-in text-[12px] leading-5 text-content-secondary">{step.note}</p>}
                {phase >= 2 && (
                  <p className="animate-slide-up flex items-center gap-1.5 rounded-lg border border-surface-border-light bg-white px-2.5 py-1.5 text-[11px]">
                    {phase >= 3
                      ? <Check className="h-3.5 w-3.5 flex-none text-emerald-500" />
                      : <Loader2 className="h-3.5 w-3.5 flex-none animate-spin text-brand" />}
                    <span className="min-w-0 truncate text-content">{step.receipt}</span>
                    <span className={cn('ml-auto flex-none', phase >= 3 ? 'text-content-tertiary' : 'text-brand')}>{phase >= 3 ? '已完成' : '进行中'}</span>
                  </p>
                )}
                {phase >= 3 && (
                  <p className="text-[12px] leading-5 text-content">
                    {replyShown}
                    {typing && <i className="home-caret ml-0.5 inline-block h-3 w-px translate-y-0.5 bg-content" />}
                  </p>
                )}
              </div>
              <div className="m-3 rounded-xl border border-surface-border bg-white px-3 py-2.5 text-[11px] text-content-tertiary">
                和主编说说你的想法，打「/」点名写作技能
              </div>
            </aside>
          </div>
        </div>
      </div>
    </div>
  )
}
