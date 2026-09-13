/**
 * 拆书 V2 视图组件：在 BookDissect 主页中针对 V2 任务展示
 * 6 个 tab：概览 / 章节 / 字典 / 实体 / 关系 / 事件
 *
 * 数据按需加载：tab 切换时才拉数据，避免一次性获取所有内容。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDown, ArrowUp, ArrowUpDown, Library, Link2, Search, Sparkles } from 'lucide-react'
import { toast } from 'sonner'

import { bookDissectApi, referencePackApi } from '@/services/api'
import type {
  BookDissectV2ChapterDetail,
  BookDissectV2ChapterSummary,
  BookDissectV2DictionaryEntry,
  BookDissectV2Entity,
  BookDissectV2Event,
  BookDissectV2Overview,
  BookDissectV2Relation,
} from '@/types'

type V2Tab =
  | 'overview'
  | 'chapters'
  | 'dictionary'
  | 'entities'
  | 'relations'
  | 'events'

interface BookDissectV2ViewProps {
  taskId: string
  /** 最新任务状态（包含 progress / phase）。父组件每次 poll 后传入。 */
  status: string
  progress: number
  extractionPhase: string | null
  chaptersTotal: number
  chaptersExtracted: number
  chaptersFailed: number
}

const TAB_LABELS: Array<[V2Tab, string]> = [
  ['overview', '概览'],
  ['chapters', '章节事实'],
  ['dictionary', '实体字典'],
  ['entities', '聚合实体'],
  ['relations', '关系'],
  ['events', '事件时间线'],
]

const PHASE_LABELS: Record<string, string> = {
  split_done: '已切分，待抽取',
  queued: '排队中',
  splitting: '章节切分',
  scanning: '实体扫描',
  dictionary: '字典分类',
  extracting: '逐章抽取',
  batched_extraction: '分批抽取（每批多章）', // 后端 batched 模式写入此值
  long_context_extraction: '整本一次抽取', // 后端 one_shot 模式写入此值
  aggregating: '全书聚合',
  synthesizing: '生成概览',
  done: '完成',
}

export function BookDissectV2View({
  taskId,
  status,
  progress,
  extractionPhase,
  chaptersTotal,
  chaptersExtracted,
  chaptersFailed,
}: BookDissectV2ViewProps) {
  const [tab, setTab] = useState<V2Tab>('overview')
  // 跨 tab 联动：点击关系/事件中的实体名 → 切到聚合实体 tab 并选中该实体
  const [entityJumpRequest, setEntityJumpRequest] = useState<{
    kind: 'id' | 'name'
    value: string
    seq: number
  } | null>(null)

  const jumpToEntity = (kind: 'id' | 'name', value: string) => {
    setTab('entities')
    setEntityJumpRequest((prev) => ({
      kind,
      value,
      seq: (prev?.seq ?? 0) + 1,
    }))
  }

  return (
    <div className="rounded-2xl border border-surface-border-light bg-surface-card p-4">
      <ProgressHeader
        status={status}
        progress={progress}
        extractionPhase={extractionPhase}
        chaptersTotal={chaptersTotal}
        chaptersExtracted={chaptersExtracted}
        chaptersFailed={chaptersFailed}
      />

      {status === 'completed' && <ApplyToCreationBar taskId={taskId} />}

      <div className="mt-4 flex flex-wrap gap-1.5 border-b border-surface-border-light">
        {TAB_LABELS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
              tab === key
                ? 'border-brand text-brand'
                : 'border-transparent text-content-secondary hover:text-content'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {tab === 'overview' && (
          <OverviewTab taskId={taskId} chaptersTotal={chaptersTotal} />
        )}
        {tab === 'chapters' && <ChaptersTab taskId={taskId} />}
        {tab === 'dictionary' && <DictionaryTab taskId={taskId} />}
        {tab === 'entities' && (
          <EntitiesTab taskId={taskId} jumpRequest={entityJumpRequest} />
        )}
        {tab === 'relations' && (
          <RelationsTab
            taskId={taskId}
            onJumpToEntity={(id) => jumpToEntity('id', id)}
          />
        )}
        {tab === 'events' && (
          <EventsTab
            taskId={taskId}
            onJumpToEntityByName={(name) => jumpToEntity('name', name)}
          />
        )}
      </div>
    </div>
  )
}

// ============================================================
// 进度头
// ============================================================

function ProgressHeader({
  status,
  progress,
  extractionPhase,
  chaptersTotal,
  chaptersExtracted,
  chaptersFailed,
}: {
  status: string
  progress: number
  extractionPhase: string | null
  chaptersTotal: number
  chaptersExtracted: number
  chaptersFailed: number
}) {
  const phaseLabel = extractionPhase
    ? PHASE_LABELS[extractionPhase] ?? extractionPhase
    : '—'
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-xs text-content-secondary">
        <span>
          <strong className="text-content">阶段：</strong>{phaseLabel}
        </span>
        <span>
          <strong className="text-content">进度：</strong>{progress}%
        </span>
        {chaptersTotal > 0 && (
          <span>
            <strong className="text-content">章节抽取：</strong>
            {chaptersExtracted}/{chaptersTotal}
            {chaptersFailed > 0 && (
              <span className="ml-1 text-rose-400">（{chaptersFailed} 失败）</span>
            )}
          </span>
        )}
        <span className="ml-auto text-[10px] uppercase tracking-wide opacity-60">
          {status}
        </span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-surface/80">
        <div
          className="h-full bg-brand transition-all"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  )
}

// ============================================================
// CTA 横条：应用到创作（仅 status=completed 时显示）
// ============================================================

function ApplyToCreationBar({ taskId }: { taskId: string }) {
  const [packId, setPackId] = useState<string | null>(null)
  const [packTitle, setPackTitle] = useState<string>('')
  const [packStatus, setPackStatus] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    referencePackApi
      .list()
      .then((packs) => {
        if (cancelled) return
        const pack = (packs ?? []).find((p) => p.task_id === taskId) ?? null
        setPackId(pack?.id ?? null)
        setPackTitle(pack?.source_book_title ?? '')
        setPackStatus(pack?.status ?? null)
      })
      .catch(() => {
        if (!cancelled) toast.error('加载参考包关联失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [taskId])

  if (loading) {
    return (
      <div className="mt-3 flex items-center gap-2 rounded-xl border border-brand/15 bg-brand/[0.04] px-4 py-2.5 text-xs text-content-secondary">
        <Sparkles className="h-3.5 w-3.5 text-brand/70" />
        正在关联参考包…
      </div>
    )
  }

  // 参考包缺失或生成失败：不提供"去项目挂载"CTA（后端会 409 拒绝挂载 failed 包）
  if (!packId || packStatus === 'failed') {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-2.5 text-xs text-amber-700">
        <Sparkles className="h-3.5 w-3.5 shrink-0" />
        <span>
          {packStatus === 'failed'
            ? '参考包生成失败（核心维度缺失或章节抽取覆盖率过低），暂不可挂载/仿写。可点击上方「重新抽取」重跑本书；'
            : '参考包尚未生成。可点击上方「重新抽取」重新触发；'}
          现有数据仍可在下方 6 个 tab 中浏览。
        </span>
      </div>
    )
  }

  const notReady = packStatus !== 'ready' && packStatus !== 'partial'

  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-brand/25 bg-gradient-to-r from-brand/[0.06] to-emerald-500/[0.04] px-4 py-3 text-xs">
      <div className="flex min-w-0 flex-1 items-center gap-2 text-content">
        <Sparkles className="h-4 w-4 shrink-0 text-brand" />
        <span>
          <strong>拆书已完成</strong>
          {packTitle && <span className="text-content-secondary">：《{packTitle}》</span>}
          。可作为参考包应用到你的创作项目。
        </span>
        {notReady && (
          <span className="rounded-pill border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-700">
            部分维度未生成
          </span>
        )}
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        <Link
          to={`/reference-packs/${packId}`}
          className="inline-flex items-center gap-1 rounded-pill border border-brand/30 bg-white/80 px-3 py-1 text-xs font-medium text-brand hover:bg-brand/5"
          title="查看参考包 5 维详情，并可一键导入文风到项目"
        >
          <Library className="h-3 w-3" />
          查看参考包
        </Link>
        <Link
          to="/projects"
          className="inline-flex items-center gap-1 rounded-pill bg-brand px-3 py-1 text-xs font-medium text-white hover:bg-brand-600"
          title="选个项目挂载这本参考包，挂载后所有生成场景会自动参考"
        >
          <Link2 className="h-3 w-3" />
          去项目挂载
        </Link>
      </div>
    </div>
  )
}

// ============================================================
// 概览 tab
// ============================================================

function OverviewTab({
  taskId,
  chaptersTotal,
}: {
  taskId: string
  chaptersTotal: number
}) {
  const [data, setData] = useState<BookDissectV2Overview | null>(null)
  const [entities, setEntities] = useState<BookDissectV2Entity[]>([])
  const [events, setEvents] = useState<BookDissectV2Event[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let mounted = true
    setLoading(true)
    Promise.all([
      bookDissectApi.v2GetOverview(taskId),
      bookDissectApi.v2ListEntities(taskId, undefined, true).catch(() => [] as BookDissectV2Entity[]),
      bookDissectApi.v2ListEvents(taskId).catch(() => [] as BookDissectV2Event[]),
    ])
      .then(([d, es, ev]) => {
        if (!mounted) return
        setData(d)
        setEntities(es)
        setEvents(ev)
      })
      .catch(() => {
        if (mounted) toast.error('加载概览失败')
      })
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [taskId])

  if (loading && !data) return <Loading />
  if (!data) return <Empty />

  const synopsis = data.synopsis
  const stats = data.stats

  return (
    <div className="space-y-4">
      <OverviewDashboard
        entities={entities}
        events={events}
        chaptersTotal={chaptersTotal}
      />

      {synopsis && (
        <div className="border border-emerald-500/25 bg-emerald-500/5 p-4">
          <h3 className="mb-3 text-sm font-semibold text-emerald-700">网文骨架（synopsis）</h3>
          <KvList>
            <Kv label="标题" value={pickStr(synopsis.title)} />
            <Kv label="主线" value={pickStr(synopsis.premise)} />
            <Kv label="金手指" value={pickStr(synopsis.golden_finger)} />
            <Kv label="力量体系" value={pickStr(synopsis.power_system)} />
            <Kv label="终极目标" value={pickStr(synopsis.ultimate_goal)} />
            <Kv label="开篇钩子" value={pickStr(synopsis.opening_hook)} />
            <Kv label="题材" value={pickStr(synopsis.genre)} />
            <Kv label="目标字数" value={(synopsis.target_words ?? '—') + ''} />
            <Kv label="叙事视角" value={pickStr(synopsis.narrative_perspective)} />
            <Kv
              label="卖点"
              value={pickList(synopsis.selling_points)?.join(' / ') ?? '—'}
            />
            <Kv
              label="标签"
              value={pickList(synopsis.main_tropes)?.join(' / ') ?? '—'}
            />
          </KvList>
        </div>
      )}
      <div className="border border-surface-border-light bg-white/85 p-4">
        <h3 className="mb-3 text-sm font-semibold text-content">统计</h3>
        <KvList>
          {Object.entries(stats).map(([k, v]) => (
            <Kv key={k} label={k} value={typeof v === 'string' ? v : JSON.stringify(v)} />
          ))}
        </KvList>
      </div>
    </div>
  )
}

// ---- Dashboard 组件 ----

const TYPE_COLORS: Record<string, string> = {
  person: '#ff5a3c', // brand
  location: '#10b981', // emerald-500
  org: '#0ea5e9', // sky-500
  item: '#f2b35d', // gold
  concept: '#8b5cf6', // violet-500
}

function OverviewDashboard({
  entities,
  events,
  chaptersTotal,
}: {
  entities: BookDissectV2Entity[]
  events: BookDissectV2Event[]
  chaptersTotal: number
}) {
  if (entities.length === 0 && events.length === 0) return null

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1.3fr_1fr]">
      <div className="space-y-3">
        <TopEntitiesPanel entities={entities} />
        <TypeDistributionPanel entities={entities} />
      </div>
      <EventDensityPanel events={events} chaptersTotal={chaptersTotal} />
    </div>
  )
}

function TopEntitiesPanel({ entities }: { entities: BookDissectV2Entity[] }) {
  const top = useMemo(() => {
    return [...entities]
      .sort((a, b) => b.appearance_count - a.appearance_count)
      .slice(0, 8)
  }, [entities])
  const max = top[0]?.appearance_count ?? 0
  if (top.length === 0) return null

  return (
    <div className="border border-surface-border-light bg-white/85 p-4">
      <h3 className="mb-2 text-sm font-semibold text-content">核心实体 Top 8</h3>
      <ul className="space-y-1.5">
        {top.map((e) => {
          const meta = ENTITY_TYPE_META[e.entity_type]
          const ratio = max > 0 ? e.appearance_count / max : 0
          return (
            <li key={e.id} className="flex items-center gap-2 text-xs">
              <span className="shrink-0 text-base leading-none" aria-hidden>
                {meta?.icon ?? '•'}
              </span>
              <span className="w-20 shrink-0 truncate font-medium text-content">
                {e.canonical_name}
              </span>
              <RoleBadge
                roleType={e.role_type}
                size="xs"
                {...extractFallbackMeta(e.profile)}
              />
              <div className="relative h-2 flex-1 bg-surface">
                <div
                  className="absolute inset-y-0 left-0 bg-brand/70"
                  style={{ width: `${ratio * 100}%` }}
                />
              </div>
              <span className="w-12 shrink-0 text-right tabular-nums text-content-secondary">
                {e.appearance_count}×
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function TypeDistributionPanel({ entities }: { entities: BookDissectV2Entity[] }) {
  const counts = useMemo(() => {
    const m = new Map<string, number>()
    entities.forEach((e) => m.set(e.entity_type, (m.get(e.entity_type) ?? 0) + 1))
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1])
  }, [entities])
  const total = entities.length
  if (total === 0) return null

  return (
    <div className="border border-surface-border-light bg-white/85 p-4">
      <h3 className="mb-2 text-sm font-semibold text-content">
        实体类型分布
        <span className="ml-2 text-[11px] font-normal text-content-secondary">
          共 {total} 项
        </span>
      </h3>
      <div className="flex h-3 w-full overflow-hidden border border-surface-border">
        {counts.map(([type, n]) => (
          <div
            key={type}
            title={`${ENTITY_TYPE_META[type]?.label ?? type} · ${n}`}
            style={{
              width: `${(n / total) * 100}%`,
              backgroundColor: TYPE_COLORS[type] ?? '#9ca3af',
            }}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-content-secondary">
        {counts.map(([type, n]) => (
          <li key={type} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2"
              style={{ backgroundColor: TYPE_COLORS[type] ?? '#9ca3af' }}
            />
            <span>{ENTITY_TYPE_META[type]?.label ?? type}</span>
            <span className="tabular-nums text-content-tertiary">{n}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function EventDensityPanel({
  events,
  chaptersTotal,
}: {
  events: BookDissectV2Event[]
  chaptersTotal: number
}) {
  const buckets = useMemo(() => {
    if (chaptersTotal <= 0) return { data: [] as number[], max: 0, total: 0 }
    // 章节太多时聚合到 60 个桶以内
    const bucketCount = Math.min(60, chaptersTotal)
    const bucketSize = Math.ceil(chaptersTotal / bucketCount)
    const data = new Array<number>(bucketCount).fill(0)
    for (const ev of events) {
      const idx = Math.min(bucketCount - 1, Math.floor((ev.chapter_number - 1) / bucketSize))
      if (idx >= 0) data[idx] += 1
    }
    return { data, max: Math.max(1, ...data), total: events.length }
  }, [events, chaptersTotal])

  const importanceCounts = useMemo(() => {
    const m = { high: 0, medium: 0, low: 0 } as Record<string, number>
    events.forEach((ev) => {
      if (ev.importance in m) m[ev.importance] += 1
    })
    return m
  }, [events])

  if (buckets.data.length === 0) {
    return (
      <div className="border border-surface-border-light bg-white/85 p-4">
        <h3 className="mb-2 text-sm font-semibold text-content">事件章节密度</h3>
        <p className="text-[11px] text-content-tertiary">尚未产生事件或章节总数未知</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col border border-surface-border-light bg-white/85 p-4">
      <h3 className="mb-2 text-sm font-semibold text-content">
        事件章节密度
        <span className="ml-2 text-[11px] font-normal text-content-secondary">
          共 {buckets.total} 起 · {chaptersTotal} 章
        </span>
      </h3>
      <div className="flex h-24 items-end gap-[1px]">
        {buckets.data.map((n, i) => (
          <div
            key={i}
            title={`区间 ${i + 1}：${n} 起事件`}
            className="flex-1"
            style={{
              height: `${Math.max(4, (n / buckets.max) * 100)}%`,
              backgroundColor: n === 0 ? '#f4e1d5' : `rgba(255, 90, 60, ${0.3 + 0.7 * (n / buckets.max)})`,
            }}
          />
        ))}
      </div>
      <div className="mt-2 flex items-center justify-between text-[10px] text-content-tertiary">
        <span>第 1 章</span>
        <span>第 {Math.ceil(chaptersTotal / 2)} 章</span>
        <span>第 {chaptersTotal} 章</span>
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-3 text-[11px] text-content-secondary">
        <li className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 bg-rose-500/70" />
          <span>高</span>
          <span className="tabular-nums text-content-tertiary">{importanceCounts.high}</span>
        </li>
        <li className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 bg-amber-500/70" />
          <span>中</span>
          <span className="tabular-nums text-content-tertiary">{importanceCounts.medium}</span>
        </li>
        <li className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 bg-slate-400/70" />
          <span>低</span>
          <span className="tabular-nums text-content-tertiary">{importanceCounts.low}</span>
        </li>
      </ul>
    </div>
  )
}

// ============================================================
// 章节 tab
// ============================================================

function ChaptersTab({ taskId }: { taskId: string }) {
  const [list, setList] = useState<BookDissectV2ChapterSummary[] | null>(null)
  const [detail, setDetail] = useState<BookDissectV2ChapterDetail | null>(null)
  const [loadingList, setLoadingList] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)

  useEffect(() => {
    let mounted = true
    setLoadingList(true)
    bookDissectApi
      .v2ListChapters(taskId)
      .then((d) => mounted && setList(d))
      .catch(() => toast.error('加载章节列表失败'))
      .finally(() => mounted && setLoadingList(false))
    return () => {
      mounted = false
    }
  }, [taskId])

  const openDetail = async (chapterNumber: number) => {
    setLoadingDetail(true)
    try {
      const d = await bookDissectApi.v2GetChapterDetail(taskId, chapterNumber)
      setDetail(d)
    } catch {
      toast.error('加载章节详情失败')
    } finally {
      setLoadingDetail(false)
    }
  }

  if (loadingList && !list) return <Loading />
  if (!list || list.length === 0) return <Empty hint="还没有章节抽取结果" />

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-[280px_1fr]">
      <div className="max-h-[480px] overflow-auto rounded-xl border border-surface-border-light bg-white/85">
        {list.map((ch) => (
          <button
            key={ch.id}
            type="button"
            onClick={() => openDetail(ch.chapter_number)}
            className={`w-full border-b border-surface-border-light px-3 py-2 text-left text-xs hover:bg-surface/80 ${
              detail?.chapter_number === ch.chapter_number ? 'bg-surface/80' : ''
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-content">
                第{ch.chapter_number}章 {ch.chapter_title ?? ''}
              </span>
              <StatusBadge status={ch.extraction_status} />
            </div>
            {ch.summary && (
              <p className="mt-1 line-clamp-2 text-content-secondary">{ch.summary}</p>
            )}
          </button>
        ))}
      </div>
      <div className="rounded-xl border border-surface-border-light bg-white/85 p-4">
        {loadingDetail && <Loading />}
        {!loadingDetail && !detail && (
          <p className="text-xs text-content-secondary">点击左侧选择一个章节查看详情</p>
        )}
        {!loadingDetail && detail && <ChapterDetailView detail={detail} />}
      </div>
    </div>
  )
}

function ChapterDetailView({ detail }: { detail: BookDissectV2ChapterDetail }) {
  const fact = (detail.fact ?? {}) as Record<string, unknown>
  return (
    <div className="space-y-3 text-xs">
      <div>
        <h4 className="text-sm font-semibold text-content">
          第{detail.chapter_number}章 {detail.chapter_title ?? ''}
        </h4>
        {detail.extraction_error && (
          <p className="mt-1 text-rose-400">错误：{detail.extraction_error}</p>
        )}
      </div>
      {detail.summary && (
        <p className="text-content-secondary">{detail.summary}</p>
      )}
      <FactSubList label="角色" items={fact.characters as unknown[]} keyField="name" />
      <FactSubList label="关系" items={fact.relationships as unknown[]} keyField="relation_type" />
      <FactSubList label="地点" items={fact.locations as unknown[]} keyField="name" />
      <FactSubList label="事件" items={fact.events as unknown[]} keyField="title" />
      <FactSubList label="物品" items={fact.item_events as unknown[]} keyField="name" />
      <FactSubList label="组织" items={fact.org_events as unknown[]} keyField="name" />
      <FactSubList label="新概念" items={fact.new_concepts as unknown[]} keyField="name" />
    </div>
  )
}

function FactSubList({
  label,
  items,
  keyField,
}: {
  label: string
  items: unknown[] | undefined
  keyField: string
}) {
  if (!Array.isArray(items) || items.length === 0) return null
  return (
    <div>
      <p className="mb-1 font-semibold text-content">
        {label}（{items.length}）
      </p>
      <ul className="space-y-1">
        {items.map((item, idx) => {
          const obj = item as Record<string, unknown>
          const name = String(obj[keyField] ?? `#${idx}`)
          const evidence = obj.evidence ? String(obj.evidence) : null
          return (
            <li key={idx} className="rounded border border-surface-border-light bg-white/85 p-2">
              <span className="font-medium">{name}</span>
              {evidence && (
                <p className="mt-0.5 text-[10px] text-content-secondary">证据：{evidence}</p>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// ============================================================
// 字典 tab
// ============================================================

function DictionaryTab({ taskId }: { taskId: string }) {
  const [list, setList] = useState<BookDissectV2DictionaryEntry[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<string>('all')

  useEffect(() => {
    let mounted = true
    setLoading(true)
    bookDissectApi
      .v2ListDictionary(taskId)
      .then((d) => mounted && setList(d))
      .catch(() => toast.error('加载字典失败'))
      .finally(() => mounted && setLoading(false))
    return () => {
      mounted = false
    }
  }, [taskId])

  if (loading && !list) return <Loading />
  if (!list || list.length === 0) return <Empty hint="字典为空" />

  const types = Array.from(new Set(list.map((e) => e.entity_type))).sort()
  const filtered = filter === 'all'
    ? list
    : list.filter((e) => e.entity_type === filter)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        <FilterButton active={filter === 'all'} label={`全部(${list.length})`} onClick={() => setFilter('all')} />
        {types.map((t) => {
          const count = list.filter((e) => e.entity_type === t).length
          return (
            <FilterButton
              key={t}
              active={filter === t}
              label={`${t}(${count})`}
              onClick={() => setFilter(t)}
            />
          )
        })}
      </div>
      <div className="overflow-auto rounded-xl border border-surface-border-light bg-white/85">
        <table className="w-full text-xs">
          <thead className="bg-surface/80 text-left">
            <tr>
              <th className="px-2 py-1.5">名称</th>
              <th className="px-2 py-1.5">类型</th>
              <th className="px-2 py-1.5">别名</th>
              <th className="px-2 py-1.5">频率</th>
              <th className="px-2 py-1.5">置信度</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.id} className="border-t border-surface-border-light">
                <td className="px-2 py-1.5 font-medium">{e.name}</td>
                <td className="px-2 py-1.5">{e.entity_type}</td>
                <td className="px-2 py-1.5 text-content-secondary">{e.aliases.join(', ') || '—'}</td>
                <td className="px-2 py-1.5 text-content-secondary">{e.frequency}</td>
                <td className="px-2 py-1.5 text-content-secondary">{e.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ============================================================
// 实体 tab
// ============================================================

type EntitySortKey = 'appearance' | 'firstChapter' | 'name'

const ENTITY_TYPE_META: Record<
  string,
  { icon: string; label: string }
> = {
  person: { icon: '🧑', label: '人物' },
  location: { icon: '📍', label: '地点' },
  org: { icon: '🏛️', label: '组织' },
  item: { icon: '🎁', label: '物品' },
  concept: { icon: '💡', label: '概念' },
}

// V4.2.3 角色标签元数据（color = 背景/边框色系，textColor = 文字色）
const ROLE_LABEL: Record<string, string> = {
  protagonist: '主角',
  supporting: '配角',
  antagonist: '反派',
  minor: '次要',
}

const ROLE_STYLE: Record<
  string,
  { bg: string; border: string; text: string }
> = {
  protagonist: {
    bg: 'bg-amber-50',
    border: 'border-amber-300',
    text: 'text-amber-700',
  },
  antagonist: {
    bg: 'bg-rose-50',
    border: 'border-rose-300',
    text: 'text-rose-700',
  },
  supporting: {
    bg: 'bg-surface',
    border: 'border-surface-border',
    text: 'text-content-secondary',
  },
  minor: {
    bg: 'bg-surface',
    border: 'border-surface-border',
    text: 'text-content-tertiary',
  },
}

/**
 * 从实体 profile 中提取 V4.2.3 兜底元信息
 * 后端 entity_aggregator.py L242-250 写入 profile_extras["_role_type_fallback"]
 * 序列化到 profile_json 后前端读取
 */
function extractFallbackMeta(
  profile: Record<string, unknown> | undefined | null,
): { fallback?: boolean; originalRole?: string | null } {
  if (!profile || typeof profile !== 'object') return {}
  const fallback = profile['_role_type_fallback']
  if (fallback !== true) return {}
  const original = profile['_role_type_original']
  return {
    fallback: true,
    originalRole:
      typeof original === 'string' && original.length > 0 ? original : null,
  }
}

/**
 * V4.2.3 角色标签组件
 * - 主角金色醒目 / 反派玫红 / 配角次要弱化
 * - fallback=true 加 ⚙ 标记 + tooltip 显示原 LLM 标记
 */
function RoleBadge({
  roleType,
  size = 'xs',
  fallback,
  originalRole,
}: {
  roleType: string | null | undefined
  size?: 'xs' | 'sm'
  fallback?: boolean
  originalRole?: string | null
}) {
  if (!roleType) return null
  const label = ROLE_LABEL[roleType] ?? roleType
  const style = ROLE_STYLE[roleType] ?? ROLE_STYLE.minor
  const sizeCls =
    size === 'sm'
      ? 'px-2 py-0.5 text-[11px]'
      : 'px-1.5 py-0 text-[10px]'

  const tooltip = fallback
    ? originalRole
      ? `系统推断主角（原 LLM 标记：${ROLE_LABEL[originalRole] ?? originalRole}）`
      : '系统推断主角（LLM 未标记）'
    : undefined

  return (
    <span
      className={`inline-flex items-center gap-0.5 border ${style.bg} ${style.border} ${style.text} ${sizeCls}`}
      title={tooltip}
    >
      {label}
      {fallback ? <span className="opacity-70">⚙</span> : null}
    </span>
  )
}

const ROW_HEIGHT = 56
const LIST_VIEWPORT_HEIGHT = 560
const ROW_BUFFER = 4

interface EntityJumpRequest {
  kind: 'id' | 'name'
  value: string
  seq: number
}

function EntitiesTab({
  taskId,
  jumpRequest,
}: {
  taskId: string
  jumpRequest: EntityJumpRequest | null
}) {
  // 列表（slim）+ 本地 join 用的 relations / events
  const [list, setList] = useState<BookDissectV2Entity[] | null>(null)
  const [relations, setRelations] = useState<BookDissectV2Relation[]>([])
  const [events, setEvents] = useState<BookDissectV2Event[]>([])
  const [loading, setLoading] = useState(false)

  // 交互状态
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [sortKey, setSortKey] = useState<EntitySortKey>('appearance')
  const [search, setSearch] = useState<string>('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // 详情 profile（懒加载）
  const [detail, setDetail] = useState<BookDissectV2Entity | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  useEffect(() => {
    let mounted = true
    setLoading(true)
    Promise.all([
      bookDissectApi.v2ListEntities(taskId, undefined, true),
      bookDissectApi.v2ListRelations(taskId),
      bookDissectApi.v2ListEvents(taskId),
    ])
      .then(([es, rs, ev]) => {
        if (!mounted) return
        setList(es)
        setRelations(rs)
        setEvents(ev)
        if (es.length > 0) setSelectedId((cur) => cur ?? es[0].id)
      })
      .catch(() => toast.error('加载实体失败'))
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [taskId])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let mounted = true
    setLoadingDetail(true)
    bookDissectApi
      .v2GetEntity(taskId, selectedId)
      .then((d) => {
        if (mounted) setDetail(d)
      })
      .catch(() => {
        if (mounted) toast.error('加载实体详情失败')
      })
      .finally(() => {
        if (mounted) setLoadingDetail(false)
      })
    return () => {
      mounted = false
    }
  }, [taskId, selectedId])

  // 响应外部跳转请求（从关系/事件 tab 点击名字触发）
  useEffect(() => {
    if (!jumpRequest || !list) return
    let targetId: string | null = null
    if (jumpRequest.kind === 'id') {
      targetId = jumpRequest.value
    } else {
      const name = jumpRequest.value
      const byName = list.find(
        (e) => e.canonical_name === name || e.aliases.includes(name),
      )
      if (byName) targetId = byName.id
    }
    if (!targetId) {
      toast.info(`未在实体库中找到「${jumpRequest.value}」`)
      return
    }
    // 清掉筛选条件以保证目标项在列表中可见
    setTypeFilter('all')
    setSearch('')
    setSelectedId(targetId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jumpRequest?.seq, list])

  const idToName = useMemo(() => {
    const m = new Map<string, string>()
    ;(list ?? []).forEach((e) => m.set(e.id, e.canonical_name))
    return m
  }, [list])

  const types = useMemo(
    () => (list ? Array.from(new Set(list.map((e) => e.entity_type))).sort() : []),
    [list],
  )

  const filtered = useMemo<BookDissectV2Entity[]>(() => {
    if (!list) return []
    const kw = search.trim().toLowerCase()
    let out = typeFilter === 'all' ? list : list.filter((e) => e.entity_type === typeFilter)
    if (kw) {
      out = out.filter(
        (e) =>
          e.canonical_name.toLowerCase().includes(kw) ||
          e.aliases.some((a) => a.toLowerCase().includes(kw)),
      )
    }
    const sorted = [...out]
    if (sortKey === 'appearance') {
      sorted.sort((a, b) => b.appearance_count - a.appearance_count)
    } else if (sortKey === 'firstChapter') {
      sorted.sort(
        (a, b) => (a.first_chapter ?? Number.POSITIVE_INFINITY) - (b.first_chapter ?? Number.POSITIVE_INFINITY),
      )
    } else {
      sorted.sort((a, b) => a.canonical_name.localeCompare(b.canonical_name, 'zh-Hans-CN'))
    }
    return sorted
  }, [list, typeFilter, search, sortKey])

  const selectedEntity = useMemo(
    () => (list ?? []).find((e) => e.id === selectedId) ?? null,
    [list, selectedId],
  )

  const relatedRelations = useMemo(() => {
    if (!selectedId) return []
    return relations.filter(
      (r) => r.entity_a_id === selectedId || r.entity_b_id === selectedId,
    )
  }, [relations, selectedId])

  const relatedEvents = useMemo(() => {
    if (!selectedEntity) return []
    const names = new Set<string>([
      selectedEntity.canonical_name,
      ...selectedEntity.aliases,
    ])
    return events.filter(
      (ev) =>
        ev.actors.some((a) => names.has(a)) ||
        (ev.location ? names.has(ev.location) : false),
    )
  }, [events, selectedEntity])

  if (loading && !list) return <Loading />
  if (!list || list.length === 0) return <Empty hint="还没有聚合实体" />

  return (
    <div className="space-y-3">
      {/* 工具栏 */}
      <div className="flex flex-col gap-2 border border-surface-border bg-surface-card p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索名字 / 别名…"
              className="w-full border border-surface-border bg-white pl-8 pr-3 py-1.5 text-xs text-content placeholder:text-content-tertiary"
            />
          </div>
          <SortMenu value={sortKey} onChange={setSortKey} />
        </div>
        <div className="flex flex-wrap gap-1">
          <TypeChip
            active={typeFilter === 'all'}
            onClick={() => setTypeFilter('all')}
            label="全部"
            count={list.length}
          />
          {types.map((t) => {
            const meta = ENTITY_TYPE_META[t]
            const count = list.filter((e) => e.entity_type === t).length
            return (
              <TypeChip
                key={t}
                active={typeFilter === t}
                onClick={() => setTypeFilter(t)}
                label={meta?.label ?? t}
                icon={meta?.icon}
                count={count}
              />
            )
          })}
        </div>
      </div>

      {/* Master-Detail */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[340px_1fr]">
        <EntityVirtualList
          items={filtered}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <EntityDetailPanel
          entity={selectedEntity}
          detail={detail}
          loadingDetail={loadingDetail}
          relations={relatedRelations}
          events={relatedEvents}
          idToName={idToName}
        />
      </div>

      <p className="text-[11px] text-content-tertiary">
        显示 {filtered.length} / {list.length} 项 · 本地已缓存关系 {relations.length} 条、事件 {events.length} 条
      </p>
    </div>
  )
}

function EntityVirtualList({
  items,
  selectedId,
  onSelect,
}: {
  items: BookDissectV2Entity[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const [scrollTop, setScrollTop] = useState(0)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  // 外部筛选变化后，如果选中项不在可见区则滚动到它
  useEffect(() => {
    if (!selectedId || !scrollRef.current) return
    const idx = items.findIndex((e) => e.id === selectedId)
    if (idx < 0) return
    const container = scrollRef.current
    const top = idx * ROW_HEIGHT
    const bottom = top + ROW_HEIGHT
    if (top < container.scrollTop || bottom > container.scrollTop + LIST_VIEWPORT_HEIGHT) {
      container.scrollTop = Math.max(0, top - LIST_VIEWPORT_HEIGHT / 2)
    }
  }, [selectedId, items])

  const total = items.length
  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - ROW_BUFFER)
  const endIdx = Math.min(
    total,
    Math.ceil((scrollTop + LIST_VIEWPORT_HEIGHT) / ROW_HEIGHT) + ROW_BUFFER,
  )
  const visible = items.slice(startIdx, endIdx)
  const offsetY = startIdx * ROW_HEIGHT

  return (
    <div
      ref={scrollRef}
      className="border border-surface-border bg-white"
      style={{ height: LIST_VIEWPORT_HEIGHT, overflowY: 'auto' }}
      onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
    >
      {total === 0 ? (
        <p className="p-6 text-center text-xs text-content-tertiary">无匹配项</p>
      ) : (
        <div style={{ height: total * ROW_HEIGHT, position: 'relative' }}>
          <div style={{ transform: `translateY(${offsetY}px)` }}>
            {visible.map((e) => (
              <EntityRow
                key={e.id}
                entity={e}
                active={e.id === selectedId}
                onClick={() => onSelect(e.id)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function EntityRow({
  entity,
  active,
  onClick,
}: {
  entity: BookDissectV2Entity
  active: boolean
  onClick: () => void
}) {
  const meta = ENTITY_TYPE_META[entity.entity_type]
  return (
    <button
      type="button"
      onClick={onClick}
      style={{ height: ROW_HEIGHT }}
      className={`flex w-full items-center gap-2.5 border-b border-surface-border-light px-3 text-left transition-colors ${
        active ? 'bg-brand/10' : 'hover:bg-surface-hover'
      }`}
    >
      <span className="shrink-0 text-base leading-none" aria-hidden>
        {meta?.icon ?? '•'}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span
            className={`truncate text-sm font-medium ${active ? 'text-brand' : 'text-content'}`}
          >
            {entity.canonical_name}
          </span>
          <RoleBadge
            roleType={entity.role_type}
            size="xs"
            {...extractFallbackMeta(entity.profile)}
          />
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-content-tertiary">
          <span className="tabular-nums">{entity.appearance_count}×</span>
          {entity.first_chapter != null && entity.last_chapter != null && (
            <span>第 {entity.first_chapter}-{entity.last_chapter} 章</span>
          )}
        </div>
      </div>
    </button>
  )
}

function EntityDetailPanel({
  entity,
  detail,
  loadingDetail,
  relations,
  events,
  idToName,
}: {
  entity: BookDissectV2Entity | null
  detail: BookDissectV2Entity | null
  loadingDetail: boolean
  relations: BookDissectV2Relation[]
  events: BookDissectV2Event[]
  idToName: Map<string, string>
}) {
  const [showAllAliases, setShowAllAliases] = useState(false)

  // 切换实体时收起别名
  useEffect(() => {
    setShowAllAliases(false)
  }, [entity?.id])

  if (!entity) {
    return (
      <div className="border border-dashed border-surface-border bg-surface-card p-8 text-center text-xs text-content-tertiary">
        请在左侧列表中选择一个实体
      </div>
    )
  }

  const meta = ENTITY_TYPE_META[entity.entity_type]
  const aliases = detail?.aliases ?? entity.aliases
  const visibleAliases = showAllAliases ? aliases : aliases.slice(0, 8)
  const profile = detail?.profile ?? {}
  const profileEntries = Object.entries(profile).filter(
    ([, v]) => v != null && v !== '' && !(Array.isArray(v) && v.length === 0),
  )

  return (
    <div className="border border-surface-border bg-surface-card">
      {/* 头 */}
      <div className="flex items-start gap-3 border-b border-surface-border-light px-4 py-3">
        <span className="shrink-0 text-2xl leading-none" aria-hidden>
          {meta?.icon ?? '•'}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-content">{entity.canonical_name}</h3>
            <span className="border border-surface-border bg-white px-1.5 py-0.5 text-[10px] text-content-secondary">
              {meta?.label ?? entity.entity_type}
            </span>
            <RoleBadge
              roleType={entity.role_type}
              size="sm"
              {...extractFallbackMeta(entity.profile)}
            />
          </div>
          <p className="mt-1 text-xs text-content-secondary">
            出场 <strong className="tabular-nums text-content">{entity.appearance_count}</strong> 次
            {entity.first_chapter != null && entity.last_chapter != null && (
              <>
                {' '}
                · 第 <span className="tabular-nums">{entity.first_chapter}</span> - <span className="tabular-nums">{entity.last_chapter}</span> 章
                （跨 <span className="tabular-nums">{entity.last_chapter - entity.first_chapter + 1}</span> 章）
              </>
            )}
          </p>
        </div>
      </div>

      {/* 详情主体 */}
      <div className="max-h-[500px] space-y-4 overflow-auto px-4 py-3">
        {aliases.length > 0 && (
          <DetailSection title={`别名 · ${aliases.length}`}>
            <div className="flex flex-wrap gap-1">
              {visibleAliases.map((a, i) => (
                <span
                  key={`${a}-${i}`}
                  title={a}
                  className="max-w-[220px] truncate border border-surface-border bg-white px-2 py-0.5 text-[11px] text-content-secondary"
                >
                  {a}
                </span>
              ))}
              {aliases.length > 8 && (
                <button
                  type="button"
                  onClick={() => setShowAllAliases((v) => !v)}
                  className="border border-brand/30 bg-brand/5 px-2 py-0.5 text-[11px] text-brand hover:bg-brand/10"
                >
                  {showAllAliases ? '收起' : `展开 +${aliases.length - 8}`}
                </button>
              )}
            </div>
          </DetailSection>
        )}

        <DetailSection title="基本档案">
          {loadingDetail && !detail ? (
            <p className="text-[11px] text-content-tertiary">加载中…</p>
          ) : profileEntries.length === 0 ? (
            <p className="text-[11px] text-content-tertiary">无额外档案信息</p>
          ) : (
            <dl className="space-y-1 text-xs">
              {profileEntries.map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="min-w-[72px] shrink-0 font-medium text-content">{k}</dt>
                  <dd className="min-w-0 flex-1 break-words text-content-secondary">
                    {stringifyProfileValue(v)}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </DetailSection>

        <DetailSection title={`相关关系 · ${relations.length}`}>
          {relations.length === 0 ? (
            <p className="text-[11px] text-content-tertiary">无</p>
          ) : (
            <ul className="space-y-1">
              {relations.slice(0, 50).map((r) => {
                const isA = r.entity_a_id === entity.id
                const otherId = isA ? r.entity_b_id : r.entity_a_id
                const otherName = idToName.get(otherId) ?? '?'
                return (
                  <li
                    key={r.id}
                    className="flex items-center gap-1.5 border border-surface-border-light bg-white px-2 py-1 text-xs"
                  >
                    <span className="truncate font-medium text-content">{entity.canonical_name}</span>
                    <span className="shrink-0 text-content-tertiary">{isA ? '→' : '←'}</span>
                    <span className="truncate font-medium text-content">{otherName}</span>
                    <span className="ml-auto shrink-0 border border-surface-border bg-surface/80 px-1.5 py-0.5 text-[10px] text-content-secondary">
                      {r.relation_type}
                    </span>
                    {r.first_chapter != null && (
                      <span className="shrink-0 tabular-nums text-[10px] text-content-tertiary">
                        第{r.first_chapter}章
                      </span>
                    )}
                  </li>
                )
              })}
              {relations.length > 50 && (
                <p className="text-[11px] text-content-tertiary">
                  …还有 {relations.length - 50} 条
                </p>
              )}
            </ul>
          )}
        </DetailSection>

        <DetailSection title={`相关事件 · ${events.length}`}>
          {events.length === 0 ? (
            <p className="text-[11px] text-content-tertiary">无</p>
          ) : (
            <ul className="space-y-1">
              {events.slice(0, 50).map((ev) => (
                <li
                  key={ev.id}
                  className="border border-surface-border-light bg-white px-2 py-1.5 text-xs"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="border border-surface-border bg-surface/80 px-1 py-0.5 text-[10px] tabular-nums text-content-secondary">
                      第{ev.chapter_number}章
                    </span>
                    <ImportanceBadge level={ev.importance} />
                    <span className="truncate font-medium text-content">{ev.title}</span>
                  </div>
                  {ev.description && (
                    <p className="mt-1 line-clamp-2 text-[11px] text-content-secondary">
                      {ev.description}
                    </p>
                  )}
                </li>
              ))}
              {events.length > 50 && (
                <p className="text-[11px] text-content-tertiary">
                  …还有 {events.length - 50} 条
                </p>
              )}
            </ul>
          )}
        </DetailSection>
      </div>
    </div>
  )
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-content-secondary">
        {title}
      </h4>
      {children}
    </section>
  )
}

function SortMenu({
  value,
  onChange,
}: {
  value: EntitySortKey
  onChange: (v: EntitySortKey) => void
}) {
  const opts: Array<[EntitySortKey, string, React.ReactNode]> = [
    ['appearance', '出场', <ArrowDown key="a" className="h-3 w-3" />],
    ['firstChapter', '首章', <ArrowUp key="b" className="h-3 w-3" />],
    ['name', '字母', <ArrowUpDown key="c" className="h-3 w-3" />],
  ]
  return (
    <div className="flex items-center gap-0.5 border border-surface-border bg-white px-1 py-0.5 text-[11px] text-content-secondary">
      <span className="px-1 text-content-tertiary">排序</span>
      {opts.map(([k, label, icon]) => (
        <button
          key={k}
          type="button"
          onClick={() => onChange(k)}
          className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 transition-colors ${
            value === k ? 'bg-brand text-white' : 'hover:text-content'
          }`}
        >
          {icon}
          <span>{label}</span>
        </button>
      ))}
    </div>
  )
}

function TypeChip({
  active,
  onClick,
  label,
  icon,
  count,
}: {
  active: boolean
  onClick: () => void
  label: string
  icon?: string
  count: number
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 border px-2 py-0.5 text-[11px] transition-colors ${
        active
          ? 'border-brand bg-brand text-white'
          : 'border-surface-border bg-white text-content-secondary hover:border-brand/40 hover:text-content'
      }`}
    >
      {icon && <span aria-hidden>{icon}</span>}
      <span>{label}</span>
      <span
        className={`tabular-nums ${active ? 'text-white/80' : 'text-content-tertiary'}`}
      >
        {count}
      </span>
    </button>
  )
}

function stringifyProfileValue(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  if (Array.isArray(v)) {
    return v
      .map((x) => (typeof x === 'string' ? x : JSON.stringify(x)))
      .join(' / ')
  }
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

// ============================================================
// 关系 tab
// ============================================================

function RelationsTab({
  taskId,
  onJumpToEntity,
}: {
  taskId: string
  onJumpToEntity: (entityId: string) => void
}) {
  const [list, setList] = useState<BookDissectV2Relation[] | null>(null)
  const [entities, setEntities] = useState<BookDissectV2Entity[] | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let mounted = true
    setLoading(true)
    Promise.all([
      bookDissectApi.v2ListRelations(taskId),
      bookDissectApi.v2ListEntities(taskId, undefined, true),
    ])
      .then(([rs, es]) => {
        if (mounted) {
          setList(rs)
          setEntities(es)
        }
      })
      .catch(() => toast.error('加载关系失败'))
      .finally(() => mounted && setLoading(false))
    return () => {
      mounted = false
    }
  }, [taskId])

  if (loading && !list) return <Loading />
  if (!list || list.length === 0) return <Empty hint="还没有提取到关系" />

  const idToName = new Map((entities ?? []).map((e) => [e.id, e.canonical_name]))

  return (
    <div className="overflow-auto rounded-xl border border-surface-border-light bg-white/85">
      <table className="w-full text-xs">
        <thead className="bg-surface/80 text-left">
          <tr>
            <th className="px-2 py-1.5">A</th>
            <th className="px-2 py-1.5">关系</th>
            <th className="px-2 py-1.5">B</th>
            <th className="px-2 py-1.5">类别</th>
            <th className="px-2 py-1.5">出场</th>
            <th className="px-2 py-1.5">首章</th>
          </tr>
        </thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.id} className="border-t border-surface-border-light">
              <td className="px-2 py-1.5">
                <EntityLink
                  name={idToName.get(r.entity_a_id) ?? '?'}
                  onClick={() => onJumpToEntity(r.entity_a_id)}
                />
              </td>
              <td className="px-2 py-1.5">{r.relation_type}</td>
              <td className="px-2 py-1.5">
                <EntityLink
                  name={idToName.get(r.entity_b_id) ?? '?'}
                  onClick={() => onJumpToEntity(r.entity_b_id)}
                />
              </td>
              <td className="px-2 py-1.5 text-content-secondary">{r.relation_category ?? '—'}</td>
              <td className="px-2 py-1.5 text-content-secondary">{r.occurrence_count}</td>
              <td className="px-2 py-1.5 text-content-secondary">{r.first_chapter ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EntityLink({ name, onClick }: { name: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="truncate font-medium text-content underline-offset-2 hover:text-brand hover:underline"
      title={`在聚合实体 tab 查看「${name}」`}
    >
      {name}
    </button>
  )
}

// ============================================================
// 事件 tab
// ============================================================

function EventsTab({
  taskId,
  onJumpToEntityByName,
}: {
  taskId: string
  onJumpToEntityByName: (name: string) => void
}) {
  const [list, setList] = useState<BookDissectV2Event[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<string>('all')

  useEffect(() => {
    let mounted = true
    setLoading(true)
    bookDissectApi
      .v2ListEvents(taskId)
      .then((d) => mounted && setList(d))
      .catch(() => toast.error('加载事件失败'))
      .finally(() => mounted && setLoading(false))
    return () => {
      mounted = false
    }
  }, [taskId])

  if (loading && !list) return <Loading />
  if (!list || list.length === 0) return <Empty hint="还没有提取到事件" />

  const importanceLevels = ['high', 'medium', 'low'] as const
  const filtered = filter === 'all' ? list : list.filter((e) => e.importance === filter)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        <FilterButton active={filter === 'all'} label={`全部(${list.length})`} onClick={() => setFilter('all')} />
        {importanceLevels.map((imp) => {
          const count = list.filter((e) => e.importance === imp).length
          return (
            <FilterButton key={imp} active={filter === imp} label={`${imp}(${count})`} onClick={() => setFilter(imp)} />
          )
        })}
      </div>
      <ul className="space-y-2">
        {filtered.map((ev) => (
          <li key={ev.id} className="rounded-xl border border-surface-border-light bg-white/85 p-3 text-xs">
            <div className="flex items-center gap-2">
              <span className="rounded bg-surface/80 px-1.5 py-0.5 text-[10px] text-content-secondary">
                第{ev.chapter_number}章
              </span>
              <span className="rounded bg-surface/80 px-1.5 py-0.5 text-[10px] text-content-secondary">
                {ev.event_type}
              </span>
              <ImportanceBadge level={ev.importance} />
            </div>
            <p className="mt-1 font-medium text-content">{ev.title}</p>
            {ev.description && <p className="mt-1 text-content-secondary">{ev.description}</p>}
            {ev.actors.length > 0 && (
              <div className="mt-1 flex flex-wrap items-center gap-1 text-content-secondary">
                <span>参与：</span>
                {ev.actors.map((actor) => (
                  <button
                    key={actor}
                    type="button"
                    onClick={() => onJumpToEntityByName(actor)}
                    className="border border-surface-border bg-white px-1.5 py-0.5 text-[11px] text-content hover:border-brand/40 hover:text-brand"
                  >
                    {actor}
                  </button>
                ))}
              </div>
            )}
            {ev.location && (
              <p className="mt-1 text-content-secondary">
                地点：
                <button
                  type="button"
                  onClick={() => onJumpToEntityByName(ev.location!)}
                  className="ml-1 font-medium text-content underline-offset-2 hover:text-brand hover:underline"
                >
                  {ev.location}
                </button>
              </p>
            )}
            {ev.evidence && (
              <p className="mt-1 text-[10px] text-content-secondary">证据：{ev.evidence}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ============================================================
// 子组件：通用 UI
// ============================================================

function FilterButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-2.5 py-1 text-[11px] transition-colors ${
        active
          ? 'bg-brand text-white'
          : 'bg-surface/80 text-content-secondary hover:bg-surface-hover'
      }`}
    >
      {label}
    </button>
  )
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === 'success'
      ? 'bg-emerald-500/15 text-emerald-300'
      : status === 'failed'
      ? 'bg-rose-500/15 text-rose-300'
      : 'bg-surface/80 text-content-secondary'
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] ${cls}`}>{status}</span>
  )
}

function ImportanceBadge({ level }: { level: string }) {
  const cls =
    level === 'high'
      ? 'bg-rose-500/15 text-rose-300'
      : level === 'medium'
      ? 'bg-amber-500/15 text-amber-300'
      : 'bg-surface/80 text-content-secondary'
  return <span className={`rounded px-1.5 py-0.5 text-[10px] ${cls}`}>{level}</span>
}

function Loading() {
  return <p className="py-6 text-center text-xs text-content-secondary">加载中…</p>
}

function Empty({ hint }: { hint?: string }) {
  return (
    <p className="py-6 text-center text-xs text-content-secondary">{hint ?? '暂无数据'}</p>
  )
}

function KvList({ children }: { children: React.ReactNode }) {
  return <dl className="space-y-1.5 text-xs">{children}</dl>
}

function Kv({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value || value === 'null') return null
  return (
    <div className="flex gap-2">
      <dt className="min-w-[64px] shrink-0 font-medium text-content">{label}</dt>
      <dd className="text-content-secondary">{value}</dd>
    </div>
  )
}

function pickStr(v: unknown): string | null {
  return typeof v === 'string' && v.trim() ? v.trim() : null
}

function pickList(v: unknown): string[] | null {
  if (!Array.isArray(v)) return null
  const out = v.filter((x): x is string => typeof x === 'string' && x.trim().length > 0)
  return out.length > 0 ? out : null
}
