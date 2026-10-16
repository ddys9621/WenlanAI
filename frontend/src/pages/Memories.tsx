/**
 * 故事账本（原「记忆系统」）：章节分析沉淀下来、写正文时按需召回的东西，作者都能看、能改。
 * 伏笔 / 承诺 · 人物状态 · 章节档案 · 时间线 / 因果 · 召回预览；顶部是分析进度、伏笔提醒与检索索引状态。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { BookMarked, Clock3, Database, Eye, Layers, Loader2, RefreshCw, Sparkles, UserRound } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/index'
import { useChapterSync } from '@/store/hooks'
import { useAIJobsStore } from '@/store/aiJobsStore'
import { ledgerApi } from '@/services/api'
import { PromisesTab } from '@/components/ledger/PromisesTab'
import { CharactersTab } from '@/components/ledger/CharactersTab'
import { DigestsTab } from '@/components/ledger/DigestsTab'
import { TimelineTab } from '@/components/ledger/TimelineTab'
import { RecallTab } from '@/components/ledger/RecallTab'
import { BatchAnalyzeModal } from '@/components/ledger/BatchAnalyzeModal'
import type { BatchAnalyzeRequest, BatchAnalyzeResult, LedgerOverview } from '@/types/ledger'

type TabKey = 'promises' | 'characters' | 'digests' | 'timeline' | 'recall'

const TABS: { key: TabKey; label: string; icon: React.ElementType }[] = [
  { key: 'promises', label: '伏笔 / 承诺', icon: Sparkles },
  { key: 'characters', label: '人物状态', icon: UserRound },
  { key: 'digests', label: '章节档案', icon: BookMarked },
  { key: 'timeline', label: '时间线 / 因果', icon: Clock3 },
  { key: 'recall', label: '召回预览', icon: Eye },
]

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: 'red' | 'gold' | 'green' }) {
  return (
    <div className="min-w-[72px]">
      <p className="text-[11px] text-content-tertiary">{label}</p>
      <p className={cn('text-lg font-semibold tabular-nums text-content', tone === 'red' && 'text-red-600', tone === 'gold' && 'text-amber-600', tone === 'green' && 'text-emerald-600')}>{value}</p>
    </div>
  )
}

export default function MemoriesPage() {
  const { currentProject, characters } = useStore()
  const { refreshChapters } = useChapterSync()
  const projectId = currentProject?.id
  const [activeTab, setActiveTab] = useState<TabKey>('promises')
  const [overview, setOverview] = useState<LedgerOverview | null>(null)
  const [showBatch, setShowBatch] = useState(false)
  const [version, setVersion] = useState(0)

  const loadOverview = useCallback(async () => {
    if (!projectId) return
    try {
      setOverview(await ledgerApi.overview(projectId))
    } catch {
      setOverview(null)
    }
  }, [projectId])

  useEffect(() => { void loadOverview() }, [loadOverview])

  const characterNames = useMemo(
    () => characters.filter((c) => !c.is_organization).map((c) => c.name),
    [characters],
  )

  if (!projectId) return <div className="py-12 text-center text-sm text-content-secondary">请先选择项目</div>

  const latest = overview?.latest_chapter ?? 0
  const refreshAll = () => {
    void loadOverview()
    setVersion((v) => v + 1)
  }

  const startBatch = async (request: BatchAnalyzeRequest) => {
    setShowBatch(false)
    try {
      await useAIJobsStore.getState().start<BatchAnalyzeResult>({
        kind: 'chapter_analyze_batch',
        title: `按章序分析第 ${request.from_chapter}-${request.to_chapter} 章`,
        projectId,
        meta: { ...request },
        connect: (options) => ledgerApi.analyzeBatchStream(projectId, request, options),
        onSettled: (job) => {
          const result = job.result as BatchAnalyzeResult | null
          if (job.status === 'done' && result) {
            if (result.failed.length > 0) toast.warning(result.message)
            else toast.success(result.message)
          }
          void refreshChapters()
          refreshAll()
        },
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '批量分析启动失败')
    }
  }

  const rebuildIndex = async () => {
    try {
      await useAIJobsStore.getState().start<{ count: number }>({
        kind: 'memory_index_rebuild',
        title: '重建检索索引',
        projectId,
        connect: (options) => ledgerApi.rebuildIndexStream(projectId, options),
        onSettled: (job) => {
          if (job.status === 'done') toast.success(`检索索引已重建：${(job.result as { count?: number } | null)?.count ?? 0} 条`)
          void loadOverview()
        },
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '重建启动失败')
    }
  }

  const chaptersStat = overview?.chapters
  const promiseStat = overview?.promises
  const index = overview?.index

  return (
    <div className="animate-fade-in space-y-5">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">故事账本</h1>
          <p className="mt-2 max-w-[640px] text-sm leading-6 text-content-secondary">
            章节分析记下的伏笔、人物状态、章节档案与时间线。写正文时按「这一章需要什么」召回；记错的地方在这里改，重新分析不会冲掉你的修改。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button onClick={() => setShowBatch(true)} className="hh-btn-primary"><Layers className="h-4 w-4" />按章序分析</button>
          <button onClick={() => void rebuildIndex()} disabled={!index?.available} className="hh-btn-secondary" title={index?.available ? '从账本重新编码写入向量库（不调用大模型）' : '向量模型没有加载'}>
            <Database className="h-4 w-4" />重建检索索引
          </button>
        </div>
      </section>

      <section className="hh-panel flex flex-wrap items-start gap-x-8 gap-y-3 px-4 py-3">
        {!overview ? (
          <span className="flex items-center gap-2 text-xs text-content-tertiary"><Loader2 className="h-4 w-4 animate-spin" />读取中…</span>
        ) : (
          <>
            <div className="flex flex-wrap gap-4">
              <Stat label="已写章节" value={chaptersStat?.written ?? 0} />
              <Stat label="已分析" value={chaptersStat?.ok ?? 0} tone="green" />
              <Stat label="分析过期" value={chaptersStat?.stale ?? 0} tone={chaptersStat?.stale ? 'gold' : undefined} />
              <Stat label="未分析" value={chaptersStat?.missing ?? 0} tone={chaptersStat?.missing ? 'gold' : undefined} />
              <Stat label="分析失败" value={chaptersStat?.failed ?? 0} tone={chaptersStat?.failed ? 'red' : undefined} />
            </div>
            <div className="flex flex-wrap gap-4">
              <Stat label="未回收伏笔" value={promiseStat?.active ?? 0} />
              <Stat label="已超期" value={promiseStat?.overdue ?? 0} tone={promiseStat?.overdue ? 'red' : undefined} />
              <Stat label="久未提起" value={promiseStat?.dropout ?? 0} tone={promiseStat?.dropout ? 'gold' : undefined} />
              <Stat label="已回收" value={promiseStat?.resolved ?? 0} tone="green" />
            </div>
            <div className="ml-auto text-xs leading-5 text-content-secondary">
              <p className="flex items-center gap-1.5 font-medium text-content"><Database className="h-3.5 w-3.5" />检索索引</p>
              {index?.available ? (
                <>
                  <p>{index.model ?? '向量模型'} · {index.count} 条</p>
                  {index.rebuilding && <p className="flex items-center gap-1 text-brand"><RefreshCw className="h-3 w-3 animate-spin" />正在从账本重建…</p>}
                </>
              ) : (
                <p className="text-amber-700">向量模型未加载：召回只按人物 / 关键词匹配</p>
              )}
            </div>
          </>
        )}
      </section>

      <div className="inline-flex flex-wrap border border-surface-border bg-white/60 p-1">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn('inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium transition-colors',
              activeTab === tab.key ? 'bg-brand text-white' : 'text-content-secondary hover:text-content')}
          >
            <tab.icon className="h-3.5 w-3.5" />
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'promises' && <PromisesTab key={version} projectId={projectId} latestChapter={latest} onChanged={() => void loadOverview()} />}
      {activeTab === 'characters' && <CharactersTab key={`${version}-${latest}`} projectId={projectId} latestChapter={latest} />}
      {activeTab === 'digests' && <DigestsTab projectId={projectId} version={version} />}
      {activeTab === 'timeline' && <TimelineTab key={version} projectId={projectId} characterNames={characterNames} />}
      {activeTab === 'recall' && <RecallTab key={latest} projectId={projectId} latestChapter={latest} />}

      <BatchAnalyzeModal open={showBatch} latestChapter={latest} onClose={() => setShowBatch(false)} onStart={(r) => void startBatch(r)} />
    </div>
  )
}
