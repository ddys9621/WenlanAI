import { useEffect, useState, useCallback } from 'react'
import {
  Brain, Search, Loader2, Trash2, BookOpen, Eye,
  BarChart3, Filter, RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { memoryApi } from '@/services/api'

type TabKey = 'memories' | 'foreshadows' | 'stats'

const TABS: { key: TabKey; label: string; icon: React.ElementType }[] = [
  { key: 'memories', label: '记忆列表', icon: Brain },
  { key: 'foreshadows', label: '伏笔追踪', icon: Eye },
  { key: 'stats', label: '统计总览', icon: BarChart3 },
]

const MEMORY_TYPES = ['全部', 'hook', 'foreshadow', 'plot_point', 'character_state', 'scene', 'emotion']
const STAT_LABELS: Record<string, string> = {
  total_count: '记忆总数',
  foreshadow_count: '伏笔数量',
  foreshadow_resolved: '已回收伏笔',
  by_type: '按类型统计',
  by_chapter: '按章节统计',
}
const MEMORY_TYPE_LABELS: Record<string, string> = {
  hook: '钩子',
  foreshadow: '伏笔',
  plot_point: '情节点',
  character_state: '角色状态',
  scene: '场景',
  emotion: '情绪',
  unknown: '未知类型',
}

export default function MemoriesPage() {
  const { currentProject, chapters } = useStore()
  const projectId = currentProject?.id
  const [activeTab, setActiveTab] = useState<TabKey>('memories')

  if (!projectId) return <div className="py-12 text-center text-sm text-content-secondary">请先选择项目</div>

  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">记忆系统</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            章节分析后自动沉淀的钩子、伏笔、情节点与角色状态，供后续生成时检索引用。
          </p>
        </div>
        <div className="inline-flex shrink-0 border border-surface-border bg-white/60 p-1">
          {TABS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                'inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium transition-colors',
                activeTab === tab.key
                  ? 'bg-brand text-white'
                  : 'text-content-secondary hover:text-content'
              )}
            >
              <tab.icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      {activeTab === 'memories' && <MemoriesTab projectId={projectId} chapters={chapters} />}
      {activeTab === 'foreshadows' && <ForeshadowsTab projectId={projectId} chapters={chapters} />}
      {activeTab === 'stats' && <StatsTab projectId={projectId} />}
    </div>
  )
}

function EmptyPanel({ icon: Icon, title, description }: { icon: React.ElementType; title: string; description?: string }) {
  return (
    <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
      <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
        <Icon className="h-7 w-7" />
      </span>
      <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">{title}</h2>
      {description && <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">{description}</p>}
    </section>
  )
}

function LoadingPanel() {
  return (
    <div className="hh-panel flex items-center justify-center gap-2 py-16 text-sm text-content-secondary">
      <Loader2 className="h-5 w-5 animate-spin text-brand" />
      加载中…
    </div>
  )
}

/* ─── Tab 1: 记忆列表 ─── */

function MemoriesTab({ projectId, chapters }: { projectId: string; chapters: Array<{ id: string; title: string; chapter_number: number }> }) {
  const [memories, setMemories] = useState<Array<Record<string, unknown>>>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState('全部')
  const [searchQuery, setSearchQuery] = useState('')
  const [searching, setSearching] = useState(false)

  const loadMemories = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = { limit: 100 }
      if (typeFilter !== '全部') params.memory_type = typeFilter
      const res = await memoryApi.getProjectMemories(projectId, params as { memory_type?: string; limit?: number })
      setMemories(res.memories || [])
      setTotal(res.total || 0)
    } catch {
      toast.error('加载记忆失败')
    } finally {
      setLoading(false)
    }
  }, [projectId, typeFilter])

  useEffect(() => { loadMemories() }, [loadMemories])

  const handleSearch = async () => {
    if (!searchQuery.trim()) { loadMemories(); return }
    setSearching(true)
    try {
      const res = await memoryApi.searchMemories(projectId, { query: searchQuery, limit: 50 })
      setMemories(res.memories || [])
      setTotal(res.total || 0)
    } catch {
      toast.error('搜索失败')
    } finally {
      setSearching(false)
    }
  }

  const handleDeleteChapterMemories = async (chapterId: string) => {
    if (!confirm('确定删除该章节的所有记忆？')) return
    try {
      await memoryApi.deleteChapterMemories(projectId, chapterId)
      toast.success('已删除')
      loadMemories()
    } catch {
      toast.error('删除失败')
    }
  }

  return (
    <div className="space-y-4">
      {/* 搜索与筛选 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex min-w-[240px] flex-1 gap-2">
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            placeholder="语义搜索记忆…"
            className="hh-field flex-1"
          />
          <button onClick={handleSearch} disabled={searching} className="hh-btn-secondary shrink-0">
            {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            搜索
          </button>
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-content-tertiary" />
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className="hh-field w-auto pr-8">
            {MEMORY_TYPES.map(t => <option key={t} value={t}>{t === '全部' ? '全部类型' : (MEMORY_TYPE_LABELS[t] ?? t)}</option>)}
          </select>
        </div>
        <button onClick={loadMemories} className="hh-icon-btn h-11 w-11" title="刷新" aria-label="刷新">
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
        </button>
        <span className="ml-auto text-xs text-content-tertiary tabular-nums">共 {total} 条记忆</span>
      </div>

      {loading ? (
        <LoadingPanel />
      ) : memories.length === 0 ? (
        <EmptyPanel icon={Brain} title="暂无记忆数据" description="先在「章节管理」中生成章节并执行分析，记忆会自动沉淀到这里。" />
      ) : (
        <section className="hh-panel divide-y divide-surface-border/80 overflow-hidden">
          {memories.map((mem, i) => (
            <div key={(mem.id as string) || i} className="px-5 py-4 transition-colors hover:bg-brand/[0.04]">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {Boolean(mem.memory_type) && (
                      <span className="hh-tag px-1.5 py-0.5 text-[11px]">{MEMORY_TYPE_LABELS[String(mem.memory_type)] ?? String(mem.memory_type)}</span>
                    )}
                    {Boolean(mem.title) && <h3 className="truncate text-sm font-semibold text-content">{String(mem.title)}</h3>}
                    {mem.importance_score != null && <span className="text-xs text-content-tertiary tabular-nums">重要度 {String(mem.importance_score)}</span>}
                  </div>
                  {Boolean(mem.content) && <p className="mt-1.5 line-clamp-3 whitespace-pre-wrap text-[13px] leading-6 text-content-secondary">{String(mem.content)}</p>}
                  <div className="mt-2 flex items-center gap-3 text-xs text-content-tertiary">
                    {mem.story_timeline != null && <span>时间线：第 {String(mem.story_timeline)} 章</span>}
                    {Boolean(mem.chapter_id) && (
                      <span>章节：{chapters.find(c => c.id === mem.chapter_id)?.title || String(mem.chapter_id).slice(0, 8)}</span>
                    )}
                  </div>
                </div>
                {Boolean(mem.chapter_id) && (
                  <button
                    onClick={() => handleDeleteChapterMemories(mem.chapter_id as string)}
                    title="删除该章节所有记忆"
                    aria-label="删除该章节所有记忆"
                    className="hh-icon-btn-plain h-8 w-8 shrink-0 hover:text-red-500"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </section>
      )}
    </div>
  )
}

/* ─── Tab 2: 伏笔追踪 ─── */

function ForeshadowsTab({ projectId, chapters }: { projectId: string; chapters: Array<{ id: string; title: string; chapter_number: number }> }) {
  const [foreshadows, setForeshadows] = useState<Array<Record<string, unknown>>>([])
  const [loading, setLoading] = useState(false)
  const [currentChapter, setCurrentChapter] = useState(() => {
    const max = chapters.reduce((m, c) => Math.max(m, c.chapter_number), 0)
    return max || 1
  })

  const loadForeshadows = useCallback(async () => {
    setLoading(true)
    try {
      const res = await memoryApi.getForeshadows(projectId, currentChapter)
      setForeshadows(res.foreshadows || [])
    } catch {
      toast.error('加载伏笔失败')
    } finally {
      setLoading(false)
    }
  }, [projectId, currentChapter])

  useEffect(() => { loadForeshadows() }, [loadForeshadows])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-content-secondary">截至章节</label>
        <input
          type="number"
          min={1}
          value={currentChapter}
          onChange={e => setCurrentChapter(Number(e.target.value))}
          className="hh-field w-28"
        />
        <button onClick={loadForeshadows} className="hh-btn-secondary">
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          查询
        </button>
        <span className="ml-auto text-xs text-content-tertiary tabular-nums">{foreshadows.length} 条未解决伏笔</span>
      </div>

      {loading ? (
        <LoadingPanel />
      ) : foreshadows.length === 0 ? (
        <EmptyPanel icon={Eye} title={`截至第 ${currentChapter} 章，暂无未解决伏笔`} />
      ) : (
        <section className="hh-panel divide-y divide-surface-border/80 overflow-hidden">
          {foreshadows.map((f, i) => (
            <div key={i} className="flex items-start gap-3 px-5 py-4 transition-colors hover:bg-brand/[0.04]">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center bg-brand/10 text-brand">
                <Eye className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                {Boolean(f.title) && <h3 className="text-sm font-semibold text-content">{String(f.title)}</h3>}
                {Boolean(f.content) && <p className="mt-1 whitespace-pre-wrap text-[13px] leading-6 text-content-secondary">{String(f.content)}</p>}
                <div className="mt-2 flex items-center gap-3 text-xs text-content-tertiary">
                  {f.story_timeline != null && <span>埋设于第 {String(f.story_timeline)} 章</span>}
                  {f.importance_score != null && <span className="tabular-nums">重要度 {String(f.importance_score)}</span>}
                </div>
              </div>
            </div>
          ))}
        </section>
      )}
    </div>
  )
}

/* ─── Tab 3: 统计总览 ─── */

function StatsTab({ projectId }: { projectId: string }) {
  const [stats, setStats] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    memoryApi.getStats(projectId)
      .then(res => setStats(res.stats || {}))
      .catch(() => toast.error('加载统计失败'))
      .finally(() => setLoading(false))
  }, [projectId])

  if (loading) return <LoadingPanel />
  if (!stats) return <EmptyPanel icon={BarChart3} title="暂无统计数据" />

  const entries = Object.entries(stats)
  const scalarEntries = getScalarEntries(stats)
  const groupedEntries = getGroupedEntries(stats)

  if (typeof stats.error === 'string') {
    return <EmptyPanel icon={BarChart3} title="暂无统计数据" description={stats.error} />
  }

  return (
    <div className="space-y-4">
      {scalarEntries.length > 0 && (
        <section className={cn('hh-panel grid grid-cols-2 divide-surface-border/80 md:divide-x', scalarEntries.length >= 4 ? 'md:grid-cols-4' : 'md:grid-cols-3')}>
          {scalarEntries.map(([key, value]) => (
            <div key={key} className="px-5 py-4 md:px-6">
              <p className="text-xs text-content-tertiary">{STAT_LABELS[key] ?? key}</p>
              <p className="mt-1 text-2xl font-semibold tracking-tight text-content tabular-nums">{value}</p>
            </div>
          ))}
        </section>
      )}
      {groupedEntries.length > 0 && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {groupedEntries.map(([key, value]) => {
            const items = formatCountMap(key, value)
            return (
              <section key={key} className="hh-panel p-6">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <h3 className="text-lg font-semibold tracking-tight text-content">{STAT_LABELS[key] ?? key}</h3>
                  <span className="text-xs text-content-tertiary tabular-nums">{items.length} 项</span>
                </div>
                {items.length === 0 ? (
                  <p className="text-sm text-content-tertiary">暂无数据</p>
                ) : (
                  <div className="divide-y divide-surface-border/80">
                    {items.map(([label, count]) => (
                      <div key={label} className="flex items-center justify-between gap-4 py-2 text-sm">
                        <span className="truncate text-content-secondary">{label}</span>
                        <span className="shrink-0 font-semibold text-content tabular-nums">{count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )
          })}
        </div>
      )}
      {entries.length === 0 && (
        <EmptyPanel icon={BookOpen} title="暂无统计数据" description="先分析章节以生成记忆，统计会自动汇总到这里。" />
      )}
    </div>
  )
}

function isCountMap(value: unknown): value is Record<string, number> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function getScalarEntries(stats: Record<string, unknown>) {
  return Object.entries(stats).filter((entry): entry is [string, number] => typeof entry[1] === 'number')
}

function getGroupedEntries(stats: Record<string, unknown>) {
  return Object.entries(stats).filter((entry): entry is [string, Record<string, number>] => isCountMap(entry[1]))
}

function formatCountMap(section: string, value: Record<string, number>) {
  const entries = Object.entries(value)

  if (section === 'by_chapter') {
    return entries.sort((a, b) => Number(a[0]) - Number(b[0])).map(([chapter, count]) => [`第 ${chapter} 章`, count] as const)
  }

  return entries
    .sort((a, b) => b[1] - a[1])
    .map(([label, count]) => [MEMORY_TYPE_LABELS[label] ?? label, count] as const)
}
