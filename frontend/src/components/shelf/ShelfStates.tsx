/** 书架的几种「没有书可列」：加载中的骨架、书架是空的（两种开书方式）、搜索 / 筛选没找到。 */
import type { ReactNode } from 'react'
import { ArrowRight, Plus, SearchX, Sparkles, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ShelfView } from './shelf'

export function ShelfSkeleton({ view }: { view: ShelfView }) {
  if (view === 'list') {
    return (
      <div className="flex flex-col gap-3" aria-hidden>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex gap-4 rounded-2xl border border-surface-border-light bg-white/60 p-3">
            <div className="aspect-[3/4] w-[72px] animate-pulse rounded-[10px] bg-surface-hover sm:w-[84px]" />
            <div className="flex flex-1 flex-col justify-center gap-2.5">
              <div className="h-4 w-1/3 animate-pulse rounded bg-surface-hover" />
              <div className="h-3 w-3/4 animate-pulse rounded bg-surface-hover/70" />
              <div className="h-3 w-1/4 animate-pulse rounded bg-surface-hover/70" />
            </div>
          </div>
        ))}
      </div>
    )
  }
  return (
    <div className="grid grid-cols-2 gap-x-5 gap-y-8 sm:grid-cols-3 sm:gap-x-6 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6" aria-hidden>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i}>
          <div className="aspect-[3/4] animate-pulse rounded-[14px] bg-surface-hover" />
          <div className="mt-3 h-4 w-2/3 animate-pulse rounded bg-surface-hover" />
          <div className="mt-2 h-3 w-full animate-pulse rounded bg-surface-hover/70" />
          <div className="mt-1.5 h-3 w-1/2 animate-pulse rounded bg-surface-hover/70" />
        </div>
      ))}
    </div>
  )
}

function ModeCard({ icon: Icon, title, description, primary, onClick }: {
  icon: LucideIcon
  title: string
  description: string
  primary?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex items-start gap-4 rounded-2xl border border-surface-border-light bg-white/75 p-5 text-left transition-all hover:-translate-y-0.5 hover:border-brand/30 hover:bg-white hover:shadow-card"
    >
      <span className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-colors', primary ? 'bg-brand text-white' : 'bg-brand-50 text-brand')}>
        <Icon className="h-5 w-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2 font-serif text-[16px] font-semibold text-content">
          {title}
          <ArrowRight className="h-4 w-4 text-content-tertiary transition-all group-hover:translate-x-0.5 group-hover:text-brand" />
        </span>
        <span className="mt-1 block text-[13px] leading-6 text-content-secondary">{description}</span>
      </span>
    </button>
  )
}

/** 三本空白书斜靠着，中间那本写着「+」 */
function EmptyShelfArt() {
  const blank = 'rounded-[8px] border border-dashed border-content-tertiary/40 bg-white/60'
  return (
    <div className="flex items-end justify-center gap-2" aria-hidden>
      <div className={cn(blank, 'h-[62px] w-[46px] -rotate-6')} />
      <div className={cn(blank, 'flex h-[78px] w-[58px] items-center justify-center border-brand/40 bg-brand-50/70 text-brand')}>
        <Plus className="h-5 w-5" />
      </div>
      <div className={cn(blank, 'h-[62px] w-[46px] rotate-6')} />
    </div>
  )
}

export function EmptyShelf({ onCreate, onInspiration, onImport }: { onCreate: () => void; onInspiration: () => void; onImport: () => void }) {
  return (
    <section className="flex flex-col items-center px-4 py-10 text-center md:py-14">
      <EmptyShelfArt />
      <h2 className="mt-7 font-serif text-[22px] font-semibold text-content">书架还是空的</h2>
      <p className="mt-2 max-w-[460px] text-sm leading-7 text-content-secondary">
        选一种方式开第一本书，AI 会陪你把世界观、人物和大纲一步步定下来。
      </p>
      <div className="mt-8 grid w-full max-w-[720px] gap-4 md:grid-cols-2">
        <ModeCard icon={Plus} title="新建小说" description="已经有书名和故事想法？填好基本信息，一次生成世界观、角色、总纲和卷纲。" primary onClick={onCreate} />
        <ModeCard icon={Sparkles} title="灵感模式" description="只有一句灵感？AI 一步步陪你定下书名、简介、主题与类型。" onClick={onInspiration} />
      </div>
      <button type="button" onClick={onImport} className="mt-6 text-xs text-content-tertiary underline-offset-4 hover:text-brand hover:underline">
        已有导出的项目文件？导入项目
      </button>
    </section>
  )
}

export function NoMatch({ onClear, children }: { onClear: () => void; children?: ReactNode }) {
  return (
    <section className="flex flex-col items-center px-4 py-16 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-hover text-content-tertiary">
        <SearchX className="h-5 w-5" />
      </span>
      <h2 className="mt-4 font-serif text-[18px] font-semibold text-content">没有找到符合条件的作品</h2>
      <p className="mt-1.5 text-[13px] text-content-secondary">{children ?? '换个关键词，或者清除筛选再看看。'}</p>
      <button type="button" onClick={onClear} className="hh-btn-secondary hh-btn-sm mt-5 rounded-lg">清除搜索和筛选</button>
    </section>
  )
}
