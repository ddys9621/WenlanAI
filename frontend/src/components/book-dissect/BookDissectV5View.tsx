/**
 * 拆书 V5 浏览视图（拆书任务页与参考包详情页共用）
 *
 * 5 tab：
 *   1. 全书骨架   —— pack.synopsis（阶段 / 金手指 / 爽点 / 长线伏笔）+ 写法手册 + 结构统计（折叠）
 *   2. 桥段库     —— pack.bridges 聚合 + GET /book-dissect/{id}/arcs 情节单元列表
 *   3. 逐章拆书表 —— GET /cards 表格，点击章号拉整张拆书卡
 *   4. 文风指纹   —— pack.style（prompt_content / 量化指标 / 例句），可复制 / 导入写作风格库
 *   5. 人物功能谱 —— pack.character_archive
 *
 * 拆书卡 / 情节单元直接读任务表，抽取进行中也能逐步看到；维度 tab 依赖参考包就绪。
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  BookMarked,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  Flame,
  GitBranch,
  LayoutList,
  Palette,
  Sparkles,
  Users,
} from 'lucide-react'
import { toast } from 'sonner'

import { bookDissectApi } from '@/services/api'
import type { BookDissectChapterCard, BookDissectChapterCardListItem, BookDissectStoryArc } from '@/types'
import type {
  BridgesV5Data,
  CharacterFunctionsData,
  MethodologyData,
  ReferencePackDetail,
  SkeletonData,
  StructureStatsData,
  StyleFingerprintData,
} from '@/types/reference_pack'
import {
  CHAPTER_ROLE_LABEL,
  EXCERPT_KIND_LABEL,
  STYLE_METRIC_LABEL,
  asRecordList,
  asString,
  asStringList,
  chapterRange,
  formatMetric,
  hookToneClass,
  paceToneClass,
  pct,
  renderValue,
} from './format'
import { ImportStyleDialog } from './ImportStyleDialog'
import { Card, CardTitle, CenterLoader, DecileBars, DistributionBars, Field, NoDataHint, SectionTip, TagList } from './shared'

export type V5Tab = 'skeleton' | 'arcs' | 'cards' | 'style' | 'characters'

const TABS: Array<{ key: V5Tab; label: string; hint: string; icon: React.ComponentType<{ className?: string }> }> = [
  { key: 'skeleton', label: '全书骨架', hint: '类型 / 前提 / 金手指 / 阶段 / 爽点 + 写法手册 + 结构统计', icon: Sparkles },
  { key: 'arcs', label: '桥段库', hint: '情节单元（多章一组的起承爽收）与爽点类型分布', icon: GitBranch },
  { key: 'cards', label: '逐章拆书表', hint: '每章功能标签 / 节奏 / 张力 / 章末钩子，点击看整卡', icon: LayoutList },
  { key: 'style', label: '文风指纹', hint: 'prompt_content + 量化指标 + 原书例句，可导入写作风格库', icon: Palette },
  { key: 'characters', label: '人物功能谱', hint: '主角 / 盟友 / 对手在故事里承担的功能', icon: Users },
]

export interface BookDissectV5ViewProps {
  taskId: string
  /** 参考包详情；null = 尚未生成 / 加载失败 */
  pack: ReferencePackDetail | null
  packLoading?: boolean
  /** 初始 tab（任务页抽取中默认落到逐章拆书表） */
  initialTab?: V5Tab
}

export function BookDissectV5View({ taskId, pack, packLoading = false, initialTab = 'skeleton' }: BookDissectV5ViewProps) {
  const [tab, setTab] = useState<V5Tab>(initialTab)

  const availability: Record<V5Tab, boolean> = {
    skeleton: pack?.synopsis != null || pack?.methodology != null || pack?.structure != null,
    arcs: true,
    cards: true,
    style: pack?.style != null,
    characters: pack?.character_archive != null,
  }

  return (
    <div className="rounded-2xl border border-surface-border-light bg-surface-card p-4">
      <div className="flex flex-wrap gap-1 border-b border-surface-border-light">
        {TABS.map((t) => {
          const active = tab === t.key
          const available = availability[t.key]
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              title={t.hint}
              className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors ${
                active
                  ? 'border-brand text-brand'
                  : available
                    ? 'border-transparent text-content-secondary hover:text-content'
                    : 'border-transparent text-content-tertiary opacity-60'
              }`}
            >
              <t.icon className="h-3.5 w-3.5" />
              {t.label}
              {!available && !packLoading && <span className="text-[10px]">(无)</span>}
            </button>
          )
        })}
      </div>

      <div className="mt-4">
        {tab === 'skeleton' && (
          <PackGate pack={pack} loading={packLoading}>
            {(p) => (
              <SkeletonTab
                skeleton={p.synopsis as SkeletonData | null}
                methodology={p.methodology as MethodologyData | null}
                structure={p.structure as StructureStatsData | null}
              />
            )}
          </PackGate>
        )}
        {tab === 'arcs' && <ArcsTab taskId={taskId} bridges={(pack?.bridges as BridgesV5Data | null) ?? null} />}
        {tab === 'cards' && <CardsTab taskId={taskId} />}
        {tab === 'style' && (
          <PackGate pack={pack} loading={packLoading}>
            {(p) => <StyleTab style={p.style as StyleFingerprintData | null} sourceBookTitle={p.source_book_title} />}
          </PackGate>
        )}
        {tab === 'characters' && (
          <PackGate pack={pack} loading={packLoading}>
            {(p) => <CharacterFunctionsTab data={p.character_archive as CharacterFunctionsData | null} />}
          </PackGate>
        )}
      </div>
    </div>
  )
}

/** 维度 tab 的统一门卫：参考包加载中 / 不存在时给占位 */
function PackGate({
  pack,
  loading,
  children,
}: {
  pack: ReferencePackDetail | null
  loading: boolean
  children: (pack: ReferencePackDetail) => React.ReactNode
}) {
  if (pack) return <>{children(pack)}</>
  if (loading) return <CenterLoader text="正在加载参考包…" />
  return <NoDataHint label="参考包" hint="抽取完成后会自动生成参考包；抽取进行中可先在「逐章拆书表」查看已完成的章节" />
}

// ============================================================
// Tab 1：全书骨架 + 写法手册 + 结构统计
// ============================================================

export function SkeletonTab({
  skeleton,
  methodology,
  structure,
}: {
  skeleton: SkeletonData | null
  methodology: MethodologyData | null
  structure: StructureStatsData | null
}) {
  if (!skeleton && !methodology && !structure) return <NoDataHint label="全书骨架" />
  return (
    <div className="space-y-4">
      {skeleton ? <SkeletonSection data={skeleton} /> : <NoDataHint label="全书骨架" />}
      <Collapsible title="写法手册" icon={Flame} hint="金手指 / 开篇 / 打脸 / 升级 / 爽点密度的可借鉴写法" defaultOpen={!skeleton}>
        <MethodologySection data={methodology} />
      </Collapsible>
      <Collapsible title="结构统计" icon={Activity} hint="按拆书卡统计：节奏 / 张力 / 钩子 / 爽点密度">
        <StructureSection data={structure} />
      </Collapsible>
    </div>
  )
}

function SkeletonSection({ data }: { data: SkeletonData }) {
  const golden = data.golden_finger
  const goldenText =
    typeof golden === 'string'
      ? golden
      : golden
        ? [golden.what, golden.how_it_works && `运作：${golden.how_it_works}`, asStringList(golden.evolution).length > 0 && `演化：${asStringList(golden.evolution).join(' → ')}`]
            .filter(Boolean)
            .join('\n')
        : ''
  const stages = asRecordList(data.stages)
  const payoffs = asRecordList(data.top_payoffs)
  const foreshadowing = asRecordList(data.long_foreshadowing)

  return (
    <>
      <Card>
        <CardTitle icon={Sparkles} extra={data.genre_tag ? <span className="hh-tag">{asString(data.genre_tag)}</span> : undefined}>
          一句话骨架
        </CardTitle>
        <Field label="一句话前提" value={data.one_line_premise} multiline />
        <Field label="主线矛盾" value={data.main_conflict} multiline />
        <Field label="金手指" value={goldenText} multiline />
        <Field label="成长体系" value={data.growth_system} multiline />
        <Field label="力量体系" value={data.power_system} multiline />
        <Field label="阅读承诺（读者为什么追）" value={data.reading_promise} multiline />
        <Field label="开篇策略" value={data.opening_strategy} multiline />
      </Card>

      {stages.length > 0 && (
        <Card>
          <CardTitle icon={BookMarked} extra={`${stages.length} 个阶段`}>
            阶段划分
          </CardTitle>
          <ol className="space-y-2">
            {stages.map((s, i) => (
              <li key={i} className="rounded-lg bg-surface-deeper px-3 py-2">
                <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-content">
                  <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-brand/10 text-[11px] text-brand">{i + 1}</span>
                  {asString(s.title) || `阶段 ${i + 1}`}
                  <span className="text-xs font-normal text-content-tertiary">
                    {chapterRange(s.chapter_start as number | undefined, s.chapter_end as number | undefined)}
                    {s.arc_start != null && ` · 情节单元 #${asString(s.arc_start)}${s.arc_end != null && s.arc_end !== s.arc_start ? `-#${asString(s.arc_end)}` : ''}`}
                  </span>
                  {s.origin === 'fallback' && <span className="text-[10px] text-amber-600">（规则切分）</span>}
                </div>
                <div className="mt-1 grid gap-x-4 gap-y-1 text-xs text-content-secondary sm:grid-cols-2">
                  <KV k="核心冲突" v={s.core_conflict} />
                  <KV k="主角目标" v={s.protagonist_goal} />
                  <KV k="关键升级" v={s.key_upgrades} />
                  <KV k="代表桥段" v={s.signature_arc} />
                  <KV k="阶段末钩子" v={s.ending_hook} />
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {payoffs.length > 0 && (
        <Card>
          <CardTitle icon={Flame}>全书最强爽点</CardTitle>
          <ul className="space-y-2">
            {payoffs.map((p, i) => (
              <li key={i} className="rounded-lg bg-surface-deeper px-3 py-2 text-xs text-content-secondary">
                <div className="mb-0.5 text-sm font-medium text-content">
                  {asString(p.reward) || asString(p.trigger) || `爽点 ${i + 1}`}
                  {(asString(p.stage) || asString(p.arcs)) && (
                    <span className="ml-2 text-xs font-normal text-content-tertiary">
                      {[asString(p.stage), asString(p.arcs) && `情节单元 ${asString(p.arcs)}`].filter(Boolean).join(' · ')}
                    </span>
                  )}
                </div>
                <KV k="铺垫" v={p.buildup} />
                <KV k="触发" v={p.trigger} />
                {asString(p.reward) && asString(p.trigger) ? <KV k="兑现" v={p.reward} /> : null}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {foreshadowing.length > 0 && (
        <Card>
          <CardTitle icon={GitBranch}>长线伏笔</CardTitle>
          <ul className="space-y-1.5 text-xs text-content-secondary">
            {foreshadowing.map((f, i) => (
              <li key={i} className="rounded-lg bg-surface-deeper px-3 py-2">
                <KV k="埋设" v={f.setup} />
                <KV k="回收" v={f.payoff} />
                <KV k="作用" v={f.role} />
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  )
}

const METHODOLOGY_SECTIONS: Array<{ key: keyof MethodologyData; title: string; fields: Array<[string, string]> }> = [
  {
    key: 'golden_finger_pattern',
    title: '金手指模式',
    fields: [['type', '类型'], ['balance_mechanism', '平衡机制'], ['evolution_pattern', '演化模式'], ['writing_tips', '怎么用']],
  },
  {
    key: 'opening_hook_pattern',
    title: '开篇钩子',
    fields: [['hook_type', '钩子类型'], ['first_chapter_strategy', '首章策略'], ['writing_tips', '怎么用']],
  },
  {
    key: 'facepunch_rhythm',
    title: '打脸节奏',
    fields: [['small_facepunch_freq', '小打脸频率'], ['big_facepunch_freq', '大打脸频率'], ['three_elements_pattern', '三要素模式'], ['writing_tips', '怎么用']],
  },
  {
    key: 'power_progression',
    title: '升级路线',
    fields: [['system_type', '体系类型'], ['level_count', '层级数'], ['pace', '节奏'], ['writing_tips', '怎么用']],
  },
  {
    key: 'highlight_density',
    title: '爽点密度',
    fields: [['small_per_n_chapters', '每 N 章一小爽点'], ['medium_per_n_chapters', '每 N 章一中爽点'], ['big_per_n_chapters', '每 N 章一大爽点'], ['writing_tips', '怎么用']],
  },
]

function MethodologySection({ data }: { data: MethodologyData | null }) {
  if (!data) return <p className="text-xs text-content-tertiary">未生成写法手册。</p>
  return (
    <div className="space-y-3">
      <SectionTip>
        总结的是<strong>“作者怎么写”</strong>，不是剧情复述；把 <em>怎么用</em> 当成写自己项目时的借鉴清单。
      </SectionTip>
      <div className="grid gap-3 md:grid-cols-2">
        {METHODOLOGY_SECTIONS.map(({ key, title, fields }) => {
          const section = data[key] as Record<string, unknown> | null | undefined
          if (!section) return null
          return (
            <div key={key} className="rounded-lg bg-surface-deeper px-3 py-2">
              <div className="mb-1 text-sm font-medium text-content">{title}</div>
              {fields.map(([k, label]) => {
                const v = section[k]
                if (v == null || v === '') return null
                const isTip = k === 'writing_tips'
                return (
                  <div key={k} className={`mt-1 text-xs ${isTip ? 'rounded bg-brand/10 px-2 py-1 text-content' : 'text-content-secondary'}`}>
                    <span className="font-medium text-content-tertiary">{label}：</span>
                    {renderValue(v)}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function StructureSection({ data }: { data: StructureStatsData | null }) {
  if (!data) return <p className="text-xs text-content-tertiary">未生成结构统计。</p>
  const hookExamples = asRecordList(data.hook_examples)
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="章数" value={data.chapter_count} />
        <Stat label="平均每章字数" value={data.avg_chapter_words} />
        <Stat label="章末带钩率" value={pct(data.hook_rate)} />
        <Stat label="有爽点章占比" value={pct(data.payoff_chapter_rate)} />
        <Stat label="情节单元数" value={data.arc_count} />
        <Stat label="平均单元长度（章）" value={data.avg_arc_length} />
        <Stat label="爽点密度" value={data.payoff_density_chapters ? `每 ${data.payoff_density_chapters} 章` : '—'} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg bg-surface-deeper px-3 py-2">
          <div className="mb-2 text-xs font-medium text-content-tertiary">张力走势（全书十等分，1-5）</div>
          <DecileBars values={data.tension_by_decile} />
        </div>
        <div className="rounded-lg bg-surface-deeper px-3 py-2">
          <div className="mb-2 text-xs font-medium text-content-tertiary">节奏分布</div>
          <DistributionBars data={data.pace_distribution} percent />
        </div>
        <div className="rounded-lg bg-surface-deeper px-3 py-2">
          <div className="mb-2 text-xs font-medium text-content-tertiary">章末钩子类型</div>
          <DistributionBars data={data.hook_type_distribution} />
        </div>
        <div className="rounded-lg bg-surface-deeper px-3 py-2">
          <div className="mb-2 text-xs font-medium text-content-tertiary">章节功能标签</div>
          <DistributionBars data={data.function_tag_distribution} />
        </div>
      </div>
      {hookExamples.length > 0 && (
        <div className="rounded-lg bg-surface-deeper px-3 py-2">
          <div className="mb-2 text-xs font-medium text-content-tertiary">章末钩子示例</div>
          <ul className="space-y-1 text-xs text-content-secondary">
            {hookExamples.map((h, i) => (
              <li key={i} className="flex gap-2">
                <span className="shrink-0 tabular-nums text-content-tertiary">第 {asString(h.chapter)} 章</span>
                <span className={`shrink-0 rounded px-1.5 ${hookToneClass(asString(h.type))}`}>{asString(h.type)}</span>
                <span className="min-w-0 text-content">{asString(h.text)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ============================================================
// Tab 2：桥段库（bridges 聚合 + 情节单元列表）
// ============================================================

function ArcsTab({ taskId, bridges }: { taskId: string; bridges: BridgesV5Data | null }) {
  const [arcs, setArcs] = useState<BookDissectStoryArc[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    bookDissectApi
      .listArcs(taskId)
      .then((rows) => {
        if (!cancelled) setArcs(rows ?? [])
      })
      .catch(() => {
        if (!cancelled) {
          setArcs([])
          toast.error('加载情节单元失败')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [taskId])

  return (
    <div className="space-y-4">
      {bridges && <BridgesSummary data={bridges} />}
      {loading && !arcs ? (
        <CenterLoader text="加载情节单元…" />
      ) : !arcs || arcs.length === 0 ? (
        <NoDataHint label="情节单元" hint="情节单元在拆书卡全部抽完后划分；抽取进行中请稍后再看" />
      ) : (
        <ArcList arcs={arcs} />
      )}
    </div>
  )
}

export function BridgesSummary({ data }: { data: BridgesV5Data }) {
  const role = data.role_pattern
  return (
    <Card>
      <CardTitle icon={GitBranch} extra={data.payoff_density ? asString(data.payoff_density) : undefined}>
        桥段库总览
      </CardTitle>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="情节单元数" value={data.arc_count} />
        <Stat label="平均长度（章）" value={data.avg_arc_length} />
        {role && <Stat label="铺垫占比（起+承）" value={pct((Number(role.avg_intro_chapters) || 0) + (Number(role.avg_build_chapters) || 0))} />}
        {role && <Stat label="爽点章占比" value={pct(role.payoff_position_ratio)} />}
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded-lg bg-surface-deeper px-3 py-2">
          <div className="mb-2 text-xs font-medium text-content-tertiary">爽点类型分布</div>
          <DistributionBars data={data.payoff_type_distribution} />
        </div>
        <div className="rounded-lg bg-surface-deeper px-3 py-2">
          <div className="mb-2 text-xs font-medium text-content-tertiary">单元长度分布（章）</div>
          <DistributionBars data={data.arc_length_distribution} />
        </div>
      </div>
    </Card>
  )
}

export function ArcList({ arcs }: { arcs: BookDissectStoryArc[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(arcs[0]?.arc_index ?? null)
  return (
    <Card>
      <CardTitle icon={LayoutList} extra={`${arcs.length} 个`}>
        情节单元
      </CardTitle>
      <ul className="space-y-2">
        {arcs.map((arc) => {
          const open = openIndex === arc.arc_index
          return (
            <li key={arc.arc_index} className="rounded-lg bg-surface-deeper">
              <button
                type="button"
                onClick={() => setOpenIndex(open ? null : arc.arc_index)}
                className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left text-sm"
              >
                {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-content-tertiary" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />}
                <span className="shrink-0 tabular-nums text-xs text-content-tertiary">#{arc.arc_index}</span>
                <span className="min-w-0 flex-1 truncate font-medium text-content">{arc.title || '（未命名）'}</span>
                <span className="shrink-0 text-xs text-content-tertiary">{chapterRange(arc.start_chapter, arc.end_chapter)}</span>
                {arc.payoff_type && <span className="hh-tag shrink-0">{arc.payoff_type}</span>}
                {arc.origin === 'fallback' && <span className="shrink-0 text-[10px] text-amber-600">规则切分</span>}
              </button>
              {open && <ArcDetail arc={arc} />}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

function ArcDetail({ arc }: { arc: BookDissectStoryArc }) {
  const roles = Object.entries(arc.chapter_roles ?? {}).sort((a, b) => Number(a[0]) - Number(b[0]))
  return (
    <div className="space-y-1.5 border-t border-surface-border-light px-3 py-2 text-xs text-content-secondary">
      <KV k="功能" v={arc.function} />
      <KV k="结构" v={arc.structure} />
      <KV k="主角行动链" v={arc.protagonist_chain} />
      <KV k="情绪曲线" v={arc.emotion_curve} />
      <KV k="爽点兑现" v={arc.payoff} />
      <KV k="金手指用法" v={arc.golden_finger_usage} />
      <KV k="人物变化" v={arc.character_changes} />
      <KV k="得失" v={arc.gains_costs} />
      <KV k="伏笔" v={arc.foreshadowing} />
      <KV k="切分依据" v={arc.boundary_reason} />
      {roles.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 pt-1">
          <span className="mr-1 font-medium text-content-tertiary">章内分工：</span>
          {roles.map(([ch, role]) => (
            <span
              key={ch}
              className={`rounded px-1.5 py-0.5 ${Number(ch) === arc.tension_peak_chapter ? 'bg-rose-500/10 text-rose-700' : 'bg-surface text-content-secondary'}`}
              title={Number(ch) === arc.tension_peak_chapter ? '张力峰值章' : undefined}
            >
              {ch}·{CHAPTER_ROLE_LABEL[role] ?? role}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================
// Tab 3：逐章拆书表
// ============================================================

function CardsTab({ taskId }: { taskId: string }) {
  const [rows, setRows] = useState<BookDissectChapterCardListItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<number | null>(null)
  const [detail, setDetail] = useState<BookDissectChapterCard | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [tagFilter, setTagFilter] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    bookDissectApi
      .listCards(taskId)
      .then((data) => {
        if (!cancelled) setRows(data ?? [])
      })
      .catch(() => {
        if (!cancelled) {
          setRows([])
          toast.error('加载拆书卡失败')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [taskId])

  useEffect(() => {
    if (selected == null) {
      setDetail(null)
      return
    }
    let cancelled = false
    setDetailLoading(true)
    bookDissectApi
      .getCard(taskId, selected)
      .then((d) => {
        if (!cancelled) setDetail(d)
      })
      .catch(() => {
        if (!cancelled) toast.error('加载拆书卡详情失败')
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [taskId, selected])

  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const r of rows ?? []) for (const t of r.function_tags) counts.set(t, (counts.get(t) ?? 0) + 1)
    return [...counts.entries()].sort((a, b) => b[1] - a[1])
  }, [rows])

  const visible = useMemo(() => (tagFilter ? (rows ?? []).filter((r) => r.function_tags.includes(tagFilter)) : rows ?? []), [rows, tagFilter])

  if (loading && !rows) return <CenterLoader text="加载拆书卡…" />
  if (!rows || rows.length === 0) return <NoDataHint label="拆书卡" hint="启动抽取后，每批章节完成即可在此看到拆书卡" />

  const failed = rows.filter((r) => r.extraction_status !== 'success').length

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-content-secondary">
            共 {rows.length} 章{failed > 0 && <span className="ml-1 text-rose-500">（{failed} 章抽取失败）</span>}
          </span>
          {tagCounts.length > 0 && <span className="mx-1 text-content-tertiary">|</span>}
          <button type="button" onClick={() => setTagFilter(null)} className={`hh-chip !py-0.5 ${tagFilter == null ? 'hh-chip--active' : ''}`}>
            全部
          </button>
          {tagCounts.slice(0, 10).map(([tag, n]) => (
            <button
              key={tag}
              type="button"
              onClick={() => setTagFilter(tagFilter === tag ? null : tag)}
              className={`hh-chip !py-0.5 ${tagFilter === tag ? 'hh-chip--active' : ''}`}
            >
              {tag} <span className="opacity-70">{n}</span>
            </button>
          ))}
        </div>
        <div className="max-h-[640px] overflow-auto rounded-lg border border-surface-border-light">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-surface text-left text-content-tertiary">
              <tr>
                <th className="px-2 py-1.5 font-medium">章</th>
                <th className="px-2 py-1.5 font-medium">标题</th>
                <th className="px-2 py-1.5 font-medium">功能</th>
                <th className="px-2 py-1.5 font-medium">节奏</th>
                <th className="px-2 py-1.5 font-medium">张力</th>
                <th className="px-2 py-1.5 font-medium">章末钩子</th>
                <th className="px-2 py-1.5 text-right font-medium">爽点</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <ChapterCardRow key={r.chapter_number} row={r} active={selected === r.chapter_number} onClick={() => setSelected(r.chapter_number)} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="min-w-0">
        {selected == null ? (
          <div className="flex h-full min-h-[200px] items-center justify-center rounded-lg border border-dashed border-surface-border text-xs text-content-tertiary">
            点击左侧任一章查看整张拆书卡
          </div>
        ) : detailLoading && !detail ? (
          <CenterLoader text="加载拆书卡…" />
        ) : detail ? (
          <ChapterCardDetail card={detail} />
        ) : null}
      </div>
    </div>
  )
}

function ChapterCardRow({ row, active, onClick }: { row: BookDissectChapterCardListItem; active: boolean; onClick: () => void }) {
  const failed = row.extraction_status !== 'success'
  return (
    <tr
      onClick={onClick}
      className={`cursor-pointer border-t border-surface-border-light transition-colors ${active ? 'bg-brand/10' : 'hover:bg-brand/5'} ${failed ? 'opacity-60' : ''}`}
    >
      <td className="px-2 py-1.5 tabular-nums text-content-secondary">{row.chapter_number}</td>
      <td className="max-w-[180px] truncate px-2 py-1.5 text-content" title={row.title}>
        {row.title || '—'}
        {failed && <span className="ml-1 text-rose-500">失败</span>}
      </td>
      <td className="px-2 py-1.5">
        <div className="flex flex-wrap gap-1">
          {row.function_tags.slice(0, 3).map((t) => (
            <span key={t} className="rounded bg-brand/[0.08] px-1.5 text-[11px] text-brand">
              {t}
            </span>
          ))}
          {row.function_tags.length > 3 && <span className="text-[11px] text-content-tertiary">+{row.function_tags.length - 3}</span>}
        </div>
      </td>
      <td className={`px-2 py-1.5 ${paceToneClass(row.pace)}`}>{row.pace}</td>
      <td className="px-2 py-1.5">
        <TensionDots value={row.tension} />
      </td>
      <td className="px-2 py-1.5">
        <span className={`rounded px-1.5 py-0.5 ${hookToneClass(row.ending_hook_type)}`}>{row.ending_hook_type}</span>
      </td>
      <td className="px-2 py-1.5 text-right tabular-nums text-content-secondary">{row.payoff_count || ''}</td>
    </tr>
  )
}

function TensionDots({ value }: { value: number }) {
  return (
    <span className="inline-flex gap-0.5" title={`张力 ${value}/5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span key={i} className={`h-2 w-1.5 rounded-sm ${i <= value ? (value >= 4 ? 'bg-rose-500' : 'bg-brand') : 'bg-brand/10'}`} />
      ))}
    </span>
  )
}

export function ChapterCardDetail({ card }: { card: BookDissectChapterCard }) {
  return (
    <Card className="max-h-[640px] overflow-auto">
      <CardTitle icon={BookMarked} extra={`${card.word_count.toLocaleString('zh-CN')} 字`}>
        第 {card.chapter_number} 章 {card.title}
      </CardTitle>
      {card.extraction_status !== 'success' && (
        <p className="mb-2 rounded bg-rose-500/10 px-2 py-1 text-xs text-rose-700">抽取失败：{card.extraction_error || '未知原因'}</p>
      )}
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <TagList items={card.function_tags} />
        <span className={paceToneClass(card.pace)}>节奏 {card.pace}</span>
        <TensionDots value={card.tension} />
        {card.emotion_tone && <span className="text-content-secondary">情绪 {card.emotion_tone}</span>}
        {card.truncated_input && <span className="text-amber-600">（输入被截断）</span>}
      </div>
      <Field label="章纲" value={card.outline} multiline />
      {card.ending_hook_type !== '无' && (
        <div className="mb-2">
          <div className="text-xs font-medium text-content-tertiary">章末钩子</div>
          <div className="text-sm text-content">
            <span className={`mr-1.5 rounded px-1.5 py-0.5 text-xs ${hookToneClass(card.ending_hook_type)}`}>{card.ending_hook_type}</span>
            {card.ending_hook_text}
          </div>
        </div>
      )}
      <ListField label="爽点" items={card.payoff_points} />
      <ListField label="亮点 / 可借鉴处" items={card.highlights} />
      <Field label="主角变化" value={card.protagonist_delta !== '无' ? card.protagonist_delta : ''} multiline />
      <ListField label="新设定" items={card.new_settings} />
      {card.characters.length > 0 && (
        <div className="mb-2">
          <div className="mb-1 text-xs font-medium text-content-tertiary">出场人物</div>
          <TagList items={card.characters} tone="muted" />
        </div>
      )}
    </Card>
  )
}

// ============================================================
// Tab 4：文风指纹
// ============================================================

export function StyleTab({ style, sourceBookTitle }: { style: StyleFingerprintData | null; sourceBookTitle: string }) {
  const [importOpen, setImportOpen] = useState(false)
  if (!style) return <NoDataHint label="文风指纹" />
  const metrics = (style.metrics ?? {}) as Record<string, unknown>
  const metricEntries = Object.entries(metrics).filter(([k, v]) => k !== 'sentence_len_dist' && v != null)
  const examples = asRecordList(style.examples)
  const canImport = !!style.prompt_content

  return (
    <div className="space-y-4">
      <SectionTip>
        <strong>prompt_content</strong> 可直接作为项目的写作风格 prompt；量化指标来自原书正文统计，例句均为原书逐字摘录。
      </SectionTip>
      <Card>
        <CardTitle icon={Palette}>{asString(style.name) || '未命名文风'}</CardTitle>
        <Field label="描述" value={style.description} multiline />
        {style.traits && style.traits.length > 0 && (
          <div className="mb-2">
            <div className="mb-1 text-xs font-medium text-content-tertiary">关键特征</div>
            <TagList items={asStringList(style.traits)} />
          </div>
        )}
        <Field label="对白习惯" value={style.dialogue_style} multiline />
        <Field label="叙述习惯" value={style.narration_habits} multiline />
        {style.avoid_list && style.avoid_list.length > 0 && (
          <div className="mb-2">
            <div className="mb-1 text-xs font-medium text-content-tertiary">避免</div>
            <TagList items={asStringList(style.avoid_list)} tone="muted" />
          </div>
        )}
        <div className="mt-3">
          <div className="mb-1 text-xs font-medium text-content-tertiary">prompt_content（可复用）</div>
          <pre className="whitespace-pre-wrap rounded-lg border border-surface-border bg-surface-deeper p-3 text-sm leading-6 text-content">
            {style.prompt_content || '（缺失）'}
          </pre>
          {canImport && (
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(style.prompt_content || '')
                  toast.success('已复制 prompt_content')
                }}
                className="hh-chip"
              >
                <Copy className="h-3 w-3" />
                复制
              </button>
              <button
                type="button"
                onClick={() => setImportOpen(true)}
                className="hh-chip hh-chip--active"
                title="把这份文风作为新的写作风格条目添加到某个项目"
              >
                <Download className="h-3 w-3" />
                导入到项目写作风格库
              </button>
            </div>
          )}
        </div>
      </Card>

      {metricEntries.length > 0 && (
        <Card>
          <CardTitle icon={Activity}>量化指标</CardTitle>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {metricEntries.map(([k, v]) => (
              <Stat key={k} label={STYLE_METRIC_LABEL[k] ?? k} value={formatMetric(k, v)} />
            ))}
          </div>
          {metrics.sentence_len_dist != null && (
            <div className="mt-3 rounded-lg bg-surface-deeper px-3 py-2">
              <div className="mb-2 text-xs font-medium text-content-tertiary">句长分布</div>
              <DistributionBars data={metrics.sentence_len_dist as Record<string, number>} percent />
            </div>
          )}
        </Card>
      )}

      {examples.length > 0 && (
        <Card>
          <CardTitle icon={BookMarked} extra={`${examples.length} 段原文`}>
            例句
          </CardTitle>
          <ul className="space-y-2">
            {examples.map((ex, i) => (
              <li key={i} className="rounded-lg bg-surface-deeper px-3 py-2">
                <div className="mb-1 flex items-center gap-2 text-[11px] text-content-tertiary">
                  <span className="hh-tag !py-0">{EXCERPT_KIND_LABEL[asString(ex.kind)] ?? asString(ex.kind)}</span>
                  {ex.chapter != null && <span>第 {asString(ex.chapter)} 章</span>}
                </div>
                <p className="whitespace-pre-wrap text-sm leading-6 text-content">{asString(ex.text)}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {importOpen && <ImportStyleDialog style={style} sourceBookTitle={sourceBookTitle} onClose={() => setImportOpen(false)} />}
    </div>
  )
}

// ============================================================
// Tab 5：人物功能谱
// ============================================================

export function CharacterFunctionsTab({ data }: { data: CharacterFunctionsData | null }) {
  if (!data) return <NoDataHint label="人物功能谱" />
  const protagonist = data.protagonist
  const allies = asRecordList(data.allies)
  const antagonists = asRecordList(data.antagonists)
  const slots = asRecordList(data.function_slots)
  const growth = asRecordList(protagonist?.growth_track)

  return (
    <div className="space-y-4">
      <SectionTip>
        记录的是人物在故事里<strong>承担的功能</strong>（怎么用这类角色推动主线），不是原书人设复述；写自己的书时对号入座即可。
      </SectionTip>
      {protagonist && (
        <Card>
          <CardTitle icon={Users}>主角 · {asString(protagonist.name) || '（未命名）'}</CardTitle>
          <Field label="人设" value={protagonist.persona} multiline />
          <Field label="金手指" value={protagonist.golden_finger} multiline />
          <Field label="缺陷与压力" value={protagonist.flaws_and_pressure} multiline />
          {growth.length > 0 && (
            <div className="mt-2">
              <div className="mb-1 text-xs font-medium text-content-tertiary">成长轨迹</div>
              <ol className="space-y-1">
                {growth.map((g, i) => (
                  <li key={i} className="flex gap-2 text-xs">
                    <span className="shrink-0 rounded bg-brand/10 px-1.5 text-brand">{asString(g.stage) || `阶段 ${i + 1}`}</span>
                    <span className="text-content">{asString(g.state)}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </Card>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardTitle icon={Users} extra={`${allies.length} 人`}>
            盟友 / 助力
          </CardTitle>
          {allies.length === 0 ? (
            <p className="text-xs text-content-tertiary">—</p>
          ) : (
            <ul className="space-y-2">
              {allies.map((a, i) => (
                <li key={i} className="rounded-lg bg-surface-deeper px-3 py-2 text-xs text-content-secondary">
                  <div className="text-sm font-medium text-content">
                    {asString(a.name)}
                    {asString(a.function_role) && <span className="ml-2 hh-tag !py-0">{asString(a.function_role)}</span>}
                  </div>
                  <KV k="出场跨度" v={a.arc_span} />
                  <KV k="用法" v={a.technique} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <CardTitle icon={Flame} extra={`${antagonists.length} 人`}>
            对手 / 阻力
          </CardTitle>
          {antagonists.length === 0 ? (
            <p className="text-xs text-content-tertiary">—</p>
          ) : (
            <ul className="space-y-2">
              {antagonists.map((a, i) => (
                <li key={i} className="rounded-lg bg-surface-deeper px-3 py-2 text-xs text-content-secondary">
                  <div className="text-sm font-medium text-content">
                    {asString(a.name)}
                    {asString(a.tier) && <span className="ml-2 rounded bg-rose-500/10 px-1.5 text-[11px] text-rose-700">{asString(a.tier)}</span>}
                  </div>
                  <KV k="冲突性质" v={a.conflict_nature} />
                  <KV k="升级方式" v={a.escalation} />
                  <KV k="结局" v={a.outcome} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {slots.length > 0 && (
        <Card>
          <CardTitle icon={LayoutList}>功能位</CardTitle>
          <ul className="grid gap-2 sm:grid-cols-2">
            {slots.map((s, i) => (
              <li key={i} className="rounded-lg bg-surface-deeper px-3 py-2 text-xs text-content-secondary">
                <div className="text-sm font-medium text-content">{asString(s.slot)}</div>
                <div className="mt-0.5 leading-5">{asString(s.how_used)}</div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

// ============================================================
// 小部件
// ============================================================

function KV({ k, v }: { k: string; v: unknown }) {
  const text = renderValue(v)
  if (!text) return null
  return (
    <div className="leading-5">
      <span className="font-medium text-content-tertiary">{k}：</span>
      <span className="text-content-secondary">{text}</span>
    </div>
  )
}

function ListField({ label, items }: { label: string; items: string[] }) {
  if (!items || items.length === 0) return null
  return (
    <div className="mb-2">
      <div className="text-xs font-medium text-content-tertiary">{label}</div>
      <ul className="list-inside list-disc text-sm leading-6 text-content">
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: unknown }) {
  const text = value == null || value === '' ? '—' : typeof value === 'number' ? value.toLocaleString('zh-CN') : String(value)
  return (
    <div className="rounded-lg bg-surface-deeper px-3 py-2">
      <div className="text-[11px] text-content-tertiary">{label}</div>
      <div className="mt-0.5 text-base font-semibold tabular-nums text-content">{text}</div>
    </div>
  )
}

function Collapsible({
  title,
  icon: Icon,
  hint,
  defaultOpen = false,
  children,
}: {
  title: string
  icon: React.ComponentType<{ className?: string }>
  hint?: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <Card>
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 text-left">
        {open ? <ChevronDown className="h-4 w-4 text-content-tertiary" /> : <ChevronRight className="h-4 w-4 text-content-tertiary" />}
        <Icon className="h-4 w-4 text-brand" />
        <span className="text-sm font-semibold text-content">{title}</span>
        {hint && <span className="ml-2 hidden text-xs text-content-tertiary sm:inline">{hint}</span>}
      </button>
      {open && <div className="mt-3">{children}</div>}
    </Card>
  )
}
