/**
 * 首页首屏以下的各个区块：长篇难点（便当格，第一格画一段故事账本）· AI 创作团队（点成员看他接活）·
 * 你来拍板（深色带 + 可以点着玩的修改卡：应用 / 放弃 / 撤销本轮）· 规划链（进入视口时连线一节节亮起）· 拆书参考 · 模型 · 部署 ·
 * 题材（两行反向滚动）· 姊妹项目推荐位（星绘 Studio，右边一张画布小样）· 常见问题（平滑展开）· 收尾 · 页脚。
 */
import { Fragment, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, ArrowUpRight, Check, Download, Github, Minus, Play, Plus, RotateCcw, Undo2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { BrandLogo } from '@/components/ui/BrandLogo'
import type { User } from '@/types'
import { loginHref } from '@/utils/loginRoute'
import { Marquee, Reveal } from './HomeEffects'
import {
  CONTROL_CARDS, DEPLOY_CARDS, FAQ, GENRES, GUIDE_URL, KNOWLEDGE_POINTS, LONGFORM_CARDS, MEMBER_DEMOS, MODEL_CARDS, PLANNING_CHAIN,
  RELEASES_URL, REPO_URL, SISTER_PROJECT, SISTER_SECTION_ID, TEAM_MEMBERS, TEAM_SCENARIOS, entryHref, type FeatureCard,
} from './homeContent'
import { useInView, usePrefersReducedMotion } from './useHomeEffects'

type MaybeUser = User | null | undefined

function Eyebrow({ children, dark }: { children: ReactNode; dark?: boolean }) {
  return (
    <p className={cn('flex items-center gap-3 font-serif text-[11px] uppercase tracking-[0.32em]', dark ? 'text-[#c9b98f]' : 'text-content-tertiary')}>
      <i className={cn('h-px w-8', dark ? 'bg-[#c9b98f]/60' : 'bg-brand/40')} />{children}
    </p>
  )
}

/** 标题拆成不折开的词组（按空格、逗号后断开）：窄屏只在词组之间换行——不会把「正文」「推进」拆到两行，也不会剩一个字落单 */
function phrased(text: string): ReactNode {
  const parts = text.replace(/，/g, '，\n').split(/\n|\s+/).filter(Boolean)
  return parts.map((part, i) => (
    <Fragment key={i}>
      <span className="whitespace-nowrap">{part}</span>
      {i < parts.length - 1 && !part.endsWith('，') && ' '}
    </Fragment>
  ))
}

function Heading({ eyebrow, title, desc, dark, center }: { eyebrow: string; title: ReactNode; desc?: ReactNode; dark?: boolean; center?: boolean }) {
  return (
    <Reveal className={cn(center && 'mx-auto text-center [&>p:first-child]:justify-center')}>
      <Eyebrow dark={dark}>{eyebrow}</Eyebrow>
      <h2 className={cn('mt-4 font-serif text-[30px] font-semibold leading-[1.25] md:text-[38px]', dark ? 'text-[#f6f3ea]' : 'text-content')}>
        {typeof title === 'string' ? phrased(title) : title}
      </h2>
      {desc && <p className={cn('mt-4 max-w-3xl text-[15px] leading-7', center && 'mx-auto', dark ? 'text-[#f6f3ea]/70' : 'text-content-secondary')}>{desc}</p>}
    </Reveal>
  )
}

function Section({ id, children, className }: { id?: string; children: ReactNode; className?: string }) {
  return (
    <section id={id} className={cn('relative px-5 py-12 md:px-8 md:py-24', className)}>
      <div className="mx-auto max-w-6xl">{children}</div>
    </section>
  )
}

/** 功能卡：宽屏图标、编号一行，标题和说明在下面；手机上图标、标题、编号排在同一行（一张卡少占一截高度） */
function IconCard({ card, index, className, dark }: { card: FeatureCard; index?: number; className?: string; dark?: boolean }) {
  const Icon = card.icon
  return (
    <div className={cn(
      'group relative h-full rounded-2xl border p-6 transition-all duration-300 hover:-translate-y-1',
      'max-sm:grid max-sm:grid-cols-[auto_minmax(0,1fr)_auto] max-sm:items-center max-sm:gap-x-3 max-sm:gap-y-2 max-sm:p-5',
      dark
        ? 'border-white/10 bg-white/[0.04] hover:border-white/20 hover:bg-white/[0.07]'
        : 'border-surface-border-light bg-white/75 hover:border-brand/25 hover:bg-white hover:shadow-[0_22px_44px_-28px_rgba(29,36,32,0.4)]',
      className,
    )}>
      <div className="flex items-center justify-between max-sm:contents">
        <span className={cn(
          'flex h-10 w-10 items-center justify-center rounded-xl transition-colors duration-300 max-sm:col-start-1 max-sm:row-start-1 max-sm:h-9 max-sm:w-9',
          dark ? 'bg-[#c9b98f]/15 text-[#e5cf96] group-hover:bg-[#c9b98f]/25' : 'bg-brand-50 text-brand group-hover:bg-brand group-hover:text-white',
        )}>
          <Icon className="h-5 w-5" strokeWidth={1.75} />
        </span>
        {index !== undefined && <span className={cn('font-serif text-[13px] tabular-nums max-sm:col-start-3 max-sm:row-start-1', dark ? 'text-white/30' : 'text-content-tertiary/70')}>{String(index + 1).padStart(2, '0')}</span>}
      </div>
      <h3 className={cn('mt-5 font-serif text-[17px] font-semibold max-sm:col-start-2 max-sm:row-start-1 max-sm:mt-0', dark ? 'text-[#f6f3ea]' : 'text-content')}>{card.title}</h3>
      <p className={cn('mt-2 text-[13px] leading-6 max-sm:col-span-3 max-sm:mt-0', dark ? 'text-[#f6f3ea]/65' : 'text-content-secondary')}>{card.desc}</p>
    </div>
  )
}

/* ---------- 长篇难点：便当格 ---------- */

/** 第一格的小插图：一段故事账本（伏笔从埋设到回收的线 + 人物状态） */
function LedgerSketch() {
  const [ref, seen] = useInView<HTMLDivElement>()
  const rows = [
    { name: '灯油的来历', from: 1, to: 12, tone: 'bg-brand', label: '第 12 章回收' },
    { name: '第七座灯塔', from: 3, to: 16, tone: 'bg-cinnabar/80', label: '超期 2 章' },
    { name: '没有雾的海', from: 5, to: 16, tone: 'bg-gold/80', label: '还在推进' },
  ]
  return (
    <div ref={ref} className="mt-6 rounded-xl border border-surface-border-light bg-surface-paper/80 p-4">
      <div className="flex justify-between text-[10px] tabular-nums text-content-tertiary">
        {[1, 4, 8, 12, 16].map((n) => <span key={n}>第 {n} 章</span>)}
      </div>
      <ul className="mt-3 space-y-3">
        {rows.map((r, i) => (
          <li key={r.name} className="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-3 text-[12px]">
            <span className="truncate text-content-secondary">{r.name}</span>
            <span className="relative h-2 rounded-full bg-surface">
              <i
                className={cn('absolute inset-y-0 rounded-full transition-[width] duration-1000 ease-out', r.tone)}
                style={{ left: `${((r.from - 1) / 15) * 100}%`, width: seen ? `${((r.to - r.from) / 15) * 100}%` : '0%', transitionDelay: `${200 + i * 180}ms` }}
              />
              <i className="absolute -top-[3px] h-3.5 w-3.5 rounded-full border-2 border-white bg-content shadow-xs" style={{ left: `calc(${((r.from - 1) / 15) * 100}% - 7px)` }} />
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap gap-1.5 border-t border-surface-border-light pt-3 text-[11px]">
        {['林照 · 灯境二重', '左手烫伤未愈', '欠灯会三盏油', '书中第 41 天'].map((t) => (
          <span key={t} className="rounded-full bg-white px-2.5 py-1 text-content-secondary shadow-xs">{t}</span>
        ))}
      </div>
    </div>
  )
}

export function FeaturesSection() {
  const [first, ...rest] = LONGFORM_CARDS
  const FirstIcon = first.icon
  return (
    <Section id="features">
      <Heading
        eyebrow="LONG-FORM"
        title={<>写长篇，难的是<span className="whitespace-nowrap text-brand">第 30 章以后</span></>}
        desc="写出一章漂亮的正文不难，难的是写到几十万字还接得住前情、人物还像自己、伏笔一条不掉。文澜 AI 把长篇里最容易出错的几件事拆开来做，每一步都看得见、改得了。"
      />
      <div className="mt-8 grid grid-cols-1 gap-4 md:mt-12 md:grid-cols-2 lg:grid-cols-3">
        <Reveal className="md:col-span-2 lg:row-span-2">
          <div className="group h-full rounded-2xl border border-surface-border-light bg-gradient-to-br from-white to-brand-50/60 p-7 transition-all duration-300 hover:-translate-y-1 hover:border-brand/25 hover:shadow-[0_26px_50px_-30px_rgba(29,36,32,0.45)]">
            <div className="flex items-center justify-between">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand text-white"><FirstIcon className="h-5 w-5" strokeWidth={1.75} /></span>
              <span className="rounded-full border border-brand/20 bg-white/80 px-3 py-1 text-[11px] text-brand-700">故事账本 · 每章写完自动整理</span>
            </div>
            <h3 className="mt-6 font-serif text-[22px] font-semibold text-content">{first.title}</h3>
            <p className="mt-2 max-w-xl text-[14px] leading-7 text-content-secondary">{first.desc}</p>
            <LedgerSketch />
          </div>
        </Reveal>
        {rest.map((c, i) => (
          <Reveal key={c.title} delay={(i + 1) * 70}><IconCard card={c} index={i + 1} /></Reveal>
        ))}
      </div>
    </Section>
  )
}

/* ---------- AI 创作团队：点成员看他接活 ---------- */

export function TeamSection() {
  const reduced = usePrefersReducedMotion()
  const [picked, setPicked] = useState(0)
  const [auto, setAuto] = useState(true)
  const [hover, setHover] = useState(false)
  const member = TEAM_MEMBERS[picked]
  const demo = MEMBER_DEMOS[member.name]

  useEffect(() => {
    if (!auto || hover || reduced) return
    const timer = setTimeout(() => setPicked((i) => (i + 1) % TEAM_MEMBERS.length), 4200)
    return () => clearTimeout(timer)
  }, [auto, hover, picked, reduced])

  return (
    <Section id="team" className="bg-gradient-to-b from-transparent via-white/50 to-transparent">
      <Heading
        eyebrow="CO-CREATION"
        title="一支 AI 创作团队，陪你推进一本书"
        desc="主编和你商量方向、安排分工，世界观、人物、总纲、章纲、正文、审校各有专人。说你要做什么就行：这件事缺哪些前置，团队自己查、自己先补。"
      />
      <div className="mt-8 grid grid-cols-1 gap-6 md:mt-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
        <Reveal>
          <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-1" role="tablist" aria-label="创作团队成员">
            {TEAM_MEMBERS.map((m, i) => (
              <li key={m.name}>
                <button
                  role="tab"
                  aria-selected={i === picked}
                  onClick={() => { setPicked(i); setAuto(false) }}
                  className={cn(
                    'flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-all duration-200',
                    i === picked ? 'border-brand/25 bg-white shadow-[0_12px_28px_-20px_rgba(29,36,32,0.5)]' : 'border-transparent hover:bg-white/70',
                  )}
                >
                  <span className={cn('flex h-9 w-9 flex-none items-center justify-center rounded-full text-[13px] font-medium transition-transform', m.tone, i === picked && 'scale-110')}>{m.initials}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[14px] font-medium text-content">{m.name}</span>
                    <span className="block truncate text-[12px] text-content-tertiary">{m.duty}</span>
                  </span>
                  <ArrowRight className={cn('h-4 w-4 flex-none transition-all', i === picked ? 'translate-x-0 text-brand opacity-100' : '-translate-x-1 opacity-0')} />
                </button>
              </li>
            ))}
          </ul>
        </Reveal>
        <Reveal delay={120}>
          <div className="relative flex h-full flex-col overflow-hidden rounded-2xl border border-surface-border-light bg-white shadow-[0_26px_60px_-36px_rgba(29,36,32,0.45)]">
            <div className="flex h-11 flex-none items-center gap-2 border-b border-surface-border-light px-4 text-[12px] text-content-secondary">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />智能助笔 · 共创室
              <span className="ml-auto text-content-tertiary">正在和「{member.name}」对话</span>
            </div>
            <div key={member.name} className="flex-1 space-y-4 p-6">
              <p className="animate-slide-up ml-auto w-fit max-w-[85%] rounded-2xl rounded-tr-sm bg-surface px-4 py-2.5 text-[14px] text-content">{demo.ask}</p>
              <div className="animate-slide-up flex items-start gap-3 [animation-delay:120ms] [animation-fill-mode:backwards]">
                <span className={cn('flex h-9 w-9 flex-none items-center justify-center rounded-full text-[13px] font-medium', member.tone)}>{member.initials}</span>
                <div className="min-w-0 flex-1 space-y-2.5">
                  <p className="text-[13px] font-medium text-content">{member.name}</p>
                  <p className="flex items-center gap-2 rounded-lg border border-surface-border-light bg-surface-paper px-3 py-2 text-[12px]">
                    <Check className="h-3.5 w-3.5 text-emerald-500" /><span className="text-content">{demo.receipt}</span><span className="ml-auto text-content-tertiary">已完成</span>
                  </p>
                  <p className="text-[14px] leading-7 text-content">{demo.reply}</p>
                </div>
              </div>
            </div>
            {/* 输入框样子：想直接找这位成员，就在消息开头 @ 他 */}
            <div className="m-4 mt-0 flex flex-none items-center gap-2 rounded-xl border border-surface-border bg-surface-paper px-3 py-2.5 text-[13px] text-content-tertiary">
              <span className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[12px] text-brand-700">@{member.name}</span>
              <span className="min-w-0 flex-1 truncate">直接找这位成员，或打「/」点名写作技能</span>
              <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-brand text-white"><ArrowRight className="h-3.5 w-3.5 -rotate-90" /></span>
            </div>
            {auto && !reduced && (
              <i key={`${member.name}-bar`} className="home-pill-progress absolute inset-x-0 bottom-0 h-[2px] origin-left bg-brand/60" style={{ animationDuration: '4200ms', animationPlayState: hover ? 'paused' : 'running' }} aria-hidden />
            )}
          </div>
        </Reveal>
      </div>
      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {TEAM_SCENARIOS.map((s, i) => (
          <Reveal key={s.title} delay={i * 70}>
            <div className="group h-full rounded-2xl border border-surface-border-light bg-white/75 p-5 transition-all duration-300 hover:-translate-y-1 hover:bg-white hover:shadow-[0_22px_44px_-28px_rgba(29,36,32,0.4)]">
              <p className="font-serif text-[32px] leading-none text-brand/30 transition-colors group-hover:text-brand/60">“</p>
              <p className="-mt-2 font-serif text-[15px] font-medium text-content">{s.quote}</p>
              <h3 className="mt-4 text-[12px] font-medium uppercase tracking-wider text-brand">{s.title}</h3>
              <p className="mt-1.5 text-[13px] leading-6 text-content-secondary">{s.desc}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </Section>
  )
}

/* ---------- 你来拍板：深色带 + 可以点着玩的修改卡 ---------- */

type DemoState = 'pending' | 'applied' | 'discarded' | 'undone'

function DecisionDemo() {
  const [state, setState] = useState<DemoState>('pending')
  const after = state === 'applied'
  return (
    <div className="rounded-2xl border border-white/10 bg-[#f6f3ea] p-5 text-content shadow-[0_30px_60px_-30px_rgba(0,0,0,0.6)]">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="rounded-full bg-gold/15 px-2 py-0.5 text-gold-500">修改</span>
        <span className="text-content-secondary">世界规则 ·「灯火」</span>
        <span className={cn(
          'ml-auto rounded-full px-2 py-0.5 text-[11px] transition-colors',
          state === 'applied' ? 'bg-brand-50 text-brand-700' : state === 'discarded' ? 'bg-surface text-content-tertiary' : state === 'undone' ? 'bg-cinnabar-wash text-cinnabar' : 'bg-gold-50 text-gold-500',
        )}>
          {state === 'applied' ? '已应用' : state === 'discarded' ? '已放弃' : state === 'undone' ? '已撤回本轮' : '待你确认'}
        </span>
      </div>
      <div className="mt-4 space-y-1.5 font-serif text-[14px] leading-7">
        <p className={cn('rounded-md px-2 transition-all duration-300', after ? 'text-content-tertiary line-through decoration-cinnabar/50' : 'bg-cinnabar-wash/60 text-cinnabar line-through decoration-cinnabar/50')}>点灯人每点一夜，折寿一日</p>
        <p className={cn('rounded-md px-2 transition-all duration-300', after ? 'bg-brand-50 text-brand-700' : state === 'pending' ? 'bg-brand-50/70 text-brand-700' : 'text-content-tertiary')}>
          点灯人每点一夜，折寿三日；灯越亮，折得越多
        </p>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-surface-border-light pt-4">
        {state === 'pending' && (
          <>
            <button onClick={() => setState('applied')} className="hh-btn-primary h-9 rounded-full px-4 text-[13px]"><Check className="h-4 w-4" />应用</button>
            <button onClick={() => setState('discarded')} className="inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-[13px] text-content-secondary hover:bg-surface"><X className="h-4 w-4" />放弃</button>
            <span className="ml-auto text-[12px] text-content-tertiary">点一下试试</span>
          </>
        )}
        {state === 'applied' && (
          <>
            <span className="text-[12px] text-content-secondary">已写进书里，这一轮还可以整轮撤回</span>
            <button onClick={() => setState('undone')} className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-full border border-surface-border bg-white px-4 text-[13px] text-content hover:border-cinnabar/40 hover:text-cinnabar"><Undo2 className="h-4 w-4" />撤销本轮</button>
          </>
        )}
        {(state === 'discarded' || state === 'undone') && (
          <>
            <span className="text-[12px] text-content-secondary">{state === 'undone' ? '已改回原样，书里看不出改过' : '没写进书里'}</span>
            <button onClick={() => setState('pending')} className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-[13px] text-brand hover:bg-brand-50"><RotateCcw className="h-4 w-4" />再来一次</button>
          </>
        )}
      </div>
    </div>
  )
}

export function ControlSection() {
  return (
    <section id="control" className="relative overflow-hidden bg-[#1d3b33] px-5 py-14 text-[#f6f3ea] md:px-8 md:py-28">
      <div className="pointer-events-none absolute -left-24 top-0 h-[420px] w-[420px] rounded-full bg-brand-400/20 blur-3xl" aria-hidden />
      <div className="pointer-events-none absolute -right-24 bottom-0 h-[380px] w-[380px] rounded-full bg-gold/10 blur-3xl" aria-hidden />
      <div className="home-ruled home-ruled--dark pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative mx-auto grid max-w-6xl grid-cols-1 gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div>
          <Heading dark eyebrow="YOU DECIDE" title="故事走向由你决定" desc="AI 负责写和整理，你负责判断和拍板。每一处改动都先给你看，写进去了也退得回来。" />
          <Reveal delay={120} className="mt-8"><DecisionDemo /></Reveal>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {CONTROL_CARDS.map((c, i) => (
            <Reveal key={c.title} delay={i * 60}><IconCard card={c} dark /></Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ---------- 规划链 + 拆书参考 ---------- */

export function PlanningSection() {
  const [ref, seen] = useInView<HTMLOListElement>()
  return (
    <Section id="planning">
      <Heading
        eyebrow="PLANNING"
        title="总纲 → 卷纲 → 章纲 → 正文，一层层落地"
        desc="上一层确认了才往下：分卷、剧情单元、章纲都是草案，你点头才定稿；改了上游，下游会标出「上游已改」，不会悄悄对不上。"
      />
      {/* 宽屏四步横排、连线从左往右亮起；手机上竖排成时间线：圆点在左、一道竖线串起来，卡片在右 */}
      <ol ref={ref} className="relative mt-8 grid grid-cols-1 gap-6 md:mt-14 md:grid-cols-4 md:gap-5">
        {/* 连线：进入视口时从左往右亮起来 */}
        <i className="absolute left-[12.5%] right-[12.5%] top-6 hidden h-px bg-surface-border md:block" aria-hidden />
        <i className="absolute left-[12.5%] top-6 hidden h-px origin-left bg-brand transition-[width] duration-[1600ms] ease-out md:block" style={{ width: seen ? '75%' : '0%' }} aria-hidden />
        {PLANNING_CHAIN.map((p, i) => (
          <li key={p.name} className="relative text-center max-md:flex max-md:items-start max-md:gap-4 max-md:text-left">
            {i < PLANNING_CHAIN.length - 1 && <i className="absolute -bottom-6 left-6 top-12 w-px bg-surface-border md:hidden" aria-hidden />}
            <span
              className={cn(
                'relative z-10 mx-auto flex h-12 w-12 items-center justify-center rounded-full border font-serif text-[15px] font-semibold transition-all duration-500 max-md:mx-0 max-md:flex-none',
                seen ? 'border-brand bg-brand text-white shadow-[0_10px_24px_-10px_rgba(40,91,77,0.8)]' : 'border-surface-border bg-surface-paper text-content-tertiary',
              )}
              style={{ transitionDelay: `${i * 380}ms` }}
            >
              {i + 1}
            </span>
            <div
              className={cn('mt-5 rounded-2xl border border-surface-border-light bg-white/75 p-5 transition-all duration-500 max-md:mt-0 max-md:min-w-0 max-md:flex-1 max-md:p-4', seen ? 'translate-y-0 opacity-100' : 'translate-y-3 opacity-0')}
              style={{ transitionDelay: `${i * 380 + 120}ms` }}
            >
              <h3 className="font-serif text-[22px] font-semibold text-content max-md:text-[18px]">{p.name}</h3>
              <p className="mt-2 text-[13px] leading-6 text-content-secondary max-md:mt-1">{p.desc}</p>
            </div>
          </li>
        ))}
      </ol>
      <Reveal className="mt-10 md:mt-16">
        <div className="rounded-3xl border border-surface-border-light bg-gradient-to-br from-white/90 to-gold-50/40 p-6 max-sm:p-5 md:p-8">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <Eyebrow>REFERENCE</Eyebrow>
              <h3 className="mt-3 font-serif text-[24px] font-semibold text-content">{phrased('学别人的节奏，写自己的故事')}</h3>
            </div>
          </div>
          <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
            {KNOWLEDGE_POINTS.map((k, i) => <Reveal key={k.title} delay={i * 70}><IconCard card={k} /></Reveal>)}
          </div>
        </div>
      </Reveal>
    </Section>
  )
}

/* ---------- 模型 + 部署 ---------- */

export function ModelsDeploySection({ user }: { user: MaybeUser }) {
  return (
    <Section id="deploy" className="bg-gradient-to-b from-transparent via-white/50 to-transparent">
      <div className="grid grid-cols-1 gap-12 lg:grid-cols-2">
        <div>
          <Heading eyebrow="MODELS" title="用你自己的模型" desc="写作调用的是你接入的模型：按这本书的需要配，花多少、用多少都在你手里。" />
          <div className="mt-8 space-y-3">
            {MODEL_CARDS.map((c, i) => {
              const Icon = c.icon
              return (
                <Reveal key={c.title} delay={i * 70}>
                  <div className="group flex items-start gap-4 rounded-2xl border border-surface-border-light bg-white/75 p-5 transition-all duration-300 hover:translate-x-1 hover:bg-white hover:shadow-[0_18px_36px_-26px_rgba(29,36,32,0.4)]">
                    <span className="flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-brand-50 text-brand transition-colors group-hover:bg-brand group-hover:text-white"><Icon className="h-5 w-5" strokeWidth={1.75} /></span>
                    <div>
                      <h3 className="font-serif text-[16px] font-semibold text-content">{c.title}</h3>
                      <p className="mt-1 text-[13px] leading-6 text-content-secondary">{c.desc}</p>
                    </div>
                  </div>
                </Reveal>
              )
            })}
          </div>
        </div>
        <div>
          <Heading eyebrow="YOUR DATA" title="书稿和数据，都在你自己手里" desc="部署在你自己的电脑或服务器上，项目随时导出成 TXT 或完整备份。" />
          <div className="mt-8 space-y-3">
            {DEPLOY_CARDS.map((c, i) => {
              const Icon = c.icon
              return (
                <Reveal key={c.title} delay={i * 70}>
                  <div className={cn(
                    'group relative flex items-start gap-4 rounded-2xl border p-5 transition-all duration-300 hover:translate-x-1 hover:shadow-[0_18px_36px_-26px_rgba(29,36,32,0.4)]',
                    i === 0 ? 'border-brand/30 bg-white' : 'border-surface-border-light bg-white/75 hover:bg-white',
                  )}>
                    <span className="flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-brand-50 text-brand transition-colors group-hover:bg-brand group-hover:text-white"><Icon className="h-5 w-5" strokeWidth={1.75} /></span>
                    <div>
                      <h3 className="flex items-center gap-2 font-serif text-[16px] font-semibold text-content">
                        {c.title}{i === 0 && <span className="rounded-full bg-brand px-2 py-0.5 font-sans text-[10px] font-medium text-white">推荐</span>}
                      </h3>
                      <p className="mt-1 text-[13px] leading-6 text-content-secondary">{c.desc}</p>
                    </div>
                  </div>
                </Reveal>
              )
            })}
          </div>
          <Reveal delay={240} className="mt-6 flex flex-wrap gap-3">
            <a href={RELEASES_URL} target="_blank" rel="noreferrer" className="hh-btn-primary h-11 rounded-full px-6 text-[14px] shadow-[0_8px_18px_-8px_rgba(40,91,77,0.8)] transition-transform hover:-translate-y-px">
              <Download className="h-4 w-4" />下载桌面版
            </a>
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="inline-flex h-11 items-center gap-2 rounded-full border border-surface-border bg-white/80 px-5 text-[14px] text-content transition-colors hover:border-brand/30">
              <Github className="h-4 w-4" />源码与部署说明
            </a>
            {!user && <Link to={loginHref('/projects')} className="inline-flex h-11 items-center px-3 text-[14px] text-content-secondary hover:text-content">已经部署好了？登录</Link>}
          </Reveal>
        </div>
      </div>
    </Section>
  )
}

/* ---------- 题材 ---------- */

export function GenresSection() {
  const half = Math.ceil(GENRES.length / 2)
  return (
    <section className="overflow-hidden py-14 md:py-24">
      <div className="mx-auto max-w-6xl px-5 md:px-8">
        <Heading center eyebrow="GENRES" title="什么题材都能写" desc="玄幻的大世界观、科幻的硬设定、悬疑的伏笔网、言情的细腻情绪，设定和写作风格都按这本书来。" />
      </div>
      <div className="home-marquee-mask mt-8 space-y-3 md:mt-10">
        <Marquee items={GENRES.slice(0, half).concat(GENRES.slice(half))} seconds={48} />
        <Marquee items={GENRES.slice(half).concat(GENRES.slice(0, half))} seconds={56} reverse />
      </div>
    </section>
  )
}

/* ---------- 姊妹项目：星绘 Studio ---------- */

function CanvasSketch() {
  const tag = 'absolute left-2 top-2 z-10 rounded-full bg-white/85 px-2 py-0.5 text-[10px] text-content-secondary shadow-xs backdrop-blur'
  const lift = 'transition-transform duration-300 ease-out group-hover:-translate-y-1'
  return (
    <div className="grid grid-cols-[minmax(0,5fr)_minmax(0,7fr)] gap-3 rounded-2xl border border-[#e6dccb] bg-[#f6f1e7] bg-[radial-gradient(rgba(139,108,67,0.22)_1px,transparent_1px)] bg-[length:14px_14px] p-4 sm:p-5">
      <div className={cn('relative row-span-2 overflow-hidden rounded-xl bg-gradient-to-b from-[#1f3a3b] via-[#29494a] to-[#10221f] shadow-[0_18px_36px_-22px_rgba(16,34,31,0.9)]', lift)}>
        <span className={tag}>封面海报</span>
        <p className="absolute right-3 top-3 font-serif text-[17px] font-semibold tracking-[0.3em] text-[#f6f3ea] [writing-mode:vertical-rl]">夜航灯</p>
        <i className="absolute bottom-[40%] left-[36%] h-24 w-24 -translate-x-1/2 translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgba(242,215,154,0.6),transparent_65%)]" />
        <i className="absolute bottom-[40%] left-[36%] h-5 w-[64%] translate-y-1/2 bg-gradient-to-r from-[#f2d79a]/60 to-transparent [clip-path:polygon(0_42%,100%_0,100%_100%,0_58%)]" />
        <i className="absolute bottom-[14%] left-[36%] h-[26%] w-[10%] -translate-x-1/2 bg-[#0b1917] [clip-path:polygon(30%_0,70%_0,100%_100%,0_100%)]" />
        <i className="absolute inset-x-0 bottom-[8%] h-[24%] bg-gradient-to-t from-white/20 to-transparent" />
        <i className="absolute inset-x-0 bottom-0 h-[15%] bg-[#0b1917]" />
      </div>
      <div className={cn('relative aspect-[16/9] overflow-hidden rounded-xl border border-[#e6dccb] bg-[#fbf8f2] [transition-delay:40ms]', lift)}>
        <span className={tag}>林照 · 三视图</span>
        <div className="absolute inset-x-0 bottom-[12%] flex items-end justify-center gap-[10%]">
          {['正', '侧', '背'].map((view) => (
            <span key={view} className="flex flex-col items-center">
              <i className="h-2.5 w-2.5 rounded-full bg-[#40524b] sm:h-3 sm:w-3" />
              <i className={cn('relative mt-0.5 h-6 bg-[#40524b] [clip-path:polygon(22%_0,78%_0,100%_100%,0_100%)] sm:h-8', view === '侧' ? 'w-3 sm:w-4' : 'w-5 sm:w-7')}>
                <i className="absolute inset-x-0 top-[38%] h-[2px] bg-cinnabar/80 sm:h-[3px]" />
              </i>
              <span className="mt-1 hidden text-[9px] leading-none text-content-tertiary sm:block">{view}</span>
            </span>
          ))}
        </div>
      </div>
      <div className={cn('relative aspect-[16/9] overflow-hidden rounded-xl bg-gradient-to-br from-[#4f6f70] via-[#86a09b] to-[#d9cfba] [transition-delay:80ms]', lift)}>
        <span className={tag}>第 1 集 · 漫剧</span>
        <i className="absolute inset-x-0 bottom-0 h-[34%] bg-gradient-to-t from-[#2b4344]/70 to-transparent" />
        <i className="absolute bottom-[30%] left-[8%] h-2.5 w-9 rounded-b-full bg-[#22383a] sm:left-[16%]" />
        <i className="absolute bottom-[30%] left-[8%] ml-4 h-6 w-px bg-[#22383a] sm:left-[16%]" />
        <span className="absolute left-1/2 top-1/2 flex h-8 w-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white/90 text-content shadow-md sm:h-9 sm:w-9">
          <Play className="ml-0.5 h-3.5 w-3.5 fill-current sm:h-4 sm:w-4" />
        </span>
        <div className="absolute inset-x-3 bottom-2 flex items-center gap-2 text-[9px] tabular-nums text-white/90">
          <span className="relative h-[3px] flex-1 overflow-hidden rounded-full bg-white/35"><i className="absolute inset-y-0 left-0 w-1/3 rounded-full bg-white" /></span>
          00:45
        </div>
      </div>
    </div>
  )
}

export function SisterProjectSection() {
  const p = SISTER_PROJECT
  return (
    <section id={SISTER_SECTION_ID} className="px-5 py-4 md:px-8" aria-label={`姊妹项目：${p.name}`}>
      <Reveal className="mx-auto max-w-6xl">
        <div className="grid grid-cols-1 items-center gap-10 rounded-3xl border border-[#e8dfcf] bg-gradient-to-br from-white via-[#fbf7f0] to-[#f3eadb] p-6 shadow-[0_24px_60px_-42px_rgba(29,36,32,0.5)] md:p-10 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:gap-14">
          <div>
            <Eyebrow>SISTER PROJECT</Eyebrow>
            <div className="mt-5 flex items-center gap-3">
              <span className="flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-cinnabar font-serif text-[19px] font-bold text-white shadow-[0_8px_18px_-10px_rgba(168,67,55,0.9)]" aria-hidden>绘</span>
              <span>
                <span className="block font-serif text-[17px] font-semibold text-content">{p.name}</span>
                <span className="block text-[12px] text-content-tertiary">{p.kind}</span>
              </span>
            </div>
            <h2 className="mt-6 font-serif text-[26px] font-semibold leading-[1.3] text-content md:text-[32px]">{phrased(p.title)}</h2>
            <p className="mt-3 max-w-xl text-[14px] leading-7 text-content-secondary">{p.desc}</p>
            <ul className="mt-5 flex flex-wrap gap-2">
              {p.tags.map((t) => <li key={t} className="rounded-full border border-[#e6dccb] bg-white/80 px-3 py-1 text-[12px] text-content-secondary">{t}</li>)}
            </ul>
            <div className="mt-7 flex flex-wrap items-center gap-x-4 gap-y-2">
              <a href={p.url} target="_blank" rel="noreferrer" className="group inline-flex h-11 items-center gap-2 rounded-full bg-content px-6 text-[14px] font-medium text-white shadow-[0_10px_22px_-12px_rgba(29,36,32,0.8)] transition-transform hover:-translate-y-px">
                去{p.name} 看看<ArrowUpRight className="h-4 w-4 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
              </a>
              <span className="text-[12px] text-content-tertiary">{new URL(p.url).host}</span>
            </div>
          </div>
          <a href={p.url} target="_blank" rel="noreferrer" tabIndex={-1} aria-hidden className="group mx-auto block w-full max-w-md lg:max-w-none">
            <CanvasSketch />
          </a>
        </div>
      </Reveal>
    </section>
  )
}

/* ---------- 常见问题 ---------- */

export function FaqSection() {
  const [open, setOpen] = useState<number | null>(0)
  return (
    <Section id="faq">
      <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,4fr)_minmax(0,8fr)]">
        <div>
          <Heading eyebrow="FAQ" title="常见问题" desc="没找到答案？使用说明里一步步写了从安装、配模型到写完一本书。" />
          <Reveal delay={120} className="mt-6">
            <a href={GUIDE_URL} target="_blank" rel="noreferrer" className="group inline-flex items-center gap-1.5 text-[14px] font-medium text-brand">
              看完整使用说明<ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </a>
          </Reveal>
        </div>
        <Reveal delay={80}>
          <ul className="divide-y divide-surface-border-light overflow-hidden rounded-2xl border border-surface-border-light bg-white/80">
            {FAQ.map((f, i) => {
              const expanded = open === i
              return (
                <li key={f.q}>
                  <h3>
                    <button
                      onClick={() => setOpen(expanded ? null : i)}
                      aria-expanded={expanded}
                      className="flex w-full items-center justify-between gap-4 px-6 py-5 text-left text-[15px] font-medium text-content transition-colors hover:bg-surface-paper"
                    >
                      {f.q}
                      <span className={cn('flex h-7 w-7 flex-none items-center justify-center rounded-full border transition-all duration-300', expanded ? 'rotate-180 border-brand bg-brand text-white' : 'border-surface-border text-content-tertiary')}>
                        {expanded ? <Minus className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
                      </span>
                    </button>
                  </h3>
                  <div className={cn('grid transition-[grid-template-rows] duration-300 ease-out', expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
                    <div className="overflow-hidden">
                      <p className="px-6 pb-5 text-[14px] leading-7 text-content-secondary">{f.a}</p>
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        </Reveal>
      </div>
    </Section>
  )
}

/* ---------- 收尾 + 页脚 ---------- */

export function ClosingSection({ user }: { user: MaybeUser }) {
  return (
    <section className="px-5 pb-14 md:px-8 md:pb-20">
      <Reveal>
        <div className="relative mx-auto max-w-6xl overflow-hidden rounded-[28px] bg-gradient-to-br from-[#1d3b33] via-brand to-[#2f6b5a] px-6 py-14 text-center text-[#f6f3ea] shadow-[0_40px_80px_-40px_rgba(29,59,51,0.8)] md:py-24">
          <div className="home-ruled home-ruled--dark pointer-events-none absolute inset-0" aria-hidden />
          <div className="pointer-events-none absolute -top-24 left-1/2 h-[300px] w-[600px] -translate-x-1/2 rounded-full bg-gold/20 blur-3xl" aria-hidden />
          <div className="relative mx-auto max-w-2xl">
            <Eyebrow dark>START WRITING</Eyebrow>
            <h2 className="mt-5 font-serif text-[34px] font-semibold leading-tight md:text-[48px]">
              让每个故事都
              <span className="relative inline-block text-[#f2d79a]">
                写得完
                <svg className="home-brush absolute -bottom-1.5 left-[-4%] h-[0.3em] w-[108%]" viewBox="0 0 120 14" preserveAspectRatio="none" aria-hidden>
                  <path d="M3 9.5C22 4.5 46 3.5 66 5.5C84 7.2 101 6.8 117 3.8" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" opacity="0.7" />
                </svg>
              </span>
            </h2>
            <p className="mx-auto mt-6 max-w-xl text-[15px] leading-8 text-[#f6f3ea]/75">设定、人物、大纲、伏笔这些繁琐的事交给团队整理，你只管想故事接下来怎么走。</p>
            {/* 手机上两个按钮上下排、一样宽（不然一宽一窄地叠着） */}
            <div className="mt-10 flex flex-wrap items-center justify-center gap-3 max-sm:mx-auto max-sm:max-w-[16rem] max-sm:flex-col max-sm:items-stretch">
              <Link to={entryHref(user, '/projects')} className="group inline-flex h-12 items-center justify-center gap-2 rounded-full bg-[#f6f3ea] px-8 text-[15px] font-medium text-brand-700 shadow-[0_12px_28px_-12px_rgba(0,0,0,0.6)] transition-transform hover:-translate-y-0.5">
                {user ? '进入书架' : '开始创作'}<ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Link>
              <a href={RELEASES_URL} target="_blank" rel="noreferrer" className="inline-flex h-12 items-center justify-center gap-2 rounded-full border border-white/25 px-6 text-[15px] text-[#f6f3ea] transition-colors hover:bg-white/10">
                <Download className="h-4 w-4" />下载桌面版
              </a>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  )
}

export function HomeFooter({ user }: { user: MaybeUser }) {
  const cols: { title: string; links: { label: string; to?: string; href?: string }[] }[] = [
    { title: '开始', links: [
      { label: user ? '进入书架' : '开始创作', to: entryHref(user, '/projects') },
      { label: '用灵感开新书', to: entryHref(user, '/projects?panel=inspiration') },
      { label: '拆书参考', to: entryHref(user, '/book-dissect') },
    ] },
    { title: '资源', links: [
      { label: '使用说明', href: GUIDE_URL },
      { label: '下载桌面版', href: RELEASES_URL },
      { label: 'GitHub', href: REPO_URL },
    ] },
  ]
  return (
    <footer className="border-t border-surface-border-light px-5 py-14 md:px-8">
      <div className="mx-auto grid max-w-6xl grid-cols-1 gap-10 md:grid-cols-[minmax(0,1fr)_auto]">
        <div className="max-w-sm">
          <div className="flex items-center gap-2.5">
            <BrandLogo size="sm" />
            <span className="font-serif text-[16px] font-semibold text-content">文澜 AI</span>
          </div>
          <p className="mt-4 text-[13px] leading-6 text-content-tertiary">面向长篇小说的 AI 创作工作台：从灵感到完本，你拍板，AI 来写。</p>
        </div>
        <div className="grid grid-cols-2 gap-x-16 gap-y-2">
          {cols.map((col) => (
            <nav key={col.title} aria-label={col.title}>
              <p className="text-[12px] font-medium uppercase tracking-wider text-content-tertiary">{col.title}</p>
              <ul className="mt-3 space-y-2 text-[13px]">
                {col.links.map((l) => (
                  <li key={l.label}>
                    {l.to
                      ? <Link to={l.to} className="text-content-secondary transition-colors hover:text-brand">{l.label}</Link>
                      : <a href={l.href} target="_blank" rel="noreferrer" className="text-content-secondary transition-colors hover:text-brand">{l.label}</a>}
                  </li>
                ))}
                {col.title === '开始' && !user && <li><Link to={loginHref('/projects')} className="text-content-secondary transition-colors hover:text-brand">登录</Link></li>}
              </ul>
            </nav>
          ))}
        </div>
      </div>
      <div className="mx-auto mt-12 flex max-w-6xl flex-wrap items-center justify-between gap-2 border-t border-surface-border-light pt-6 text-[12px] text-content-tertiary">
        <span>© {new Date().getFullYear()} 文澜 AI</span>
        <span className="font-serif">写好每一个故事</span>
      </div>
    </footer>
  )
}
