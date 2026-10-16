/**
 * 召回预览：「写第 N 章时会注入什么、为什么」——和正文生成同一条召回链，不调用大模型；
 * 下面是在整本账本里找（关键词 + 语义）。
 */
import { useState } from 'react'
import { Loader2, Search } from 'lucide-react'
import { ledgerApi } from '@/services/api'
import { CollapseSection } from '@/components/ui/CollapseSection'
import { Pill } from '@/components/ui/Pill'
import type { LedgerSearchItem, RecallPreview } from '@/types/ledger'
import { formatChars } from '@/utils/ledger'

const KIND_LABELS: Record<string, string> = { digest: '章节档案', event: '事件', causal: '因果', promise: '伏笔' }
const MATCH_LABELS: Record<string, string> = { keyword: '关键词', semantic: '语义', both: '关键词 + 语义' }

export function RecallTab({ projectId, latestChapter }: { projectId: string; latestChapter: number }) {
  const [chapter, setChapter] = useState(latestChapter + 1)
  const [preview, setPreview] = useState<RecallPreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<LedgerSearchItem[] | null>(null)
  const [semantic, setSemantic] = useState(true)
  const [searching, setSearching] = useState(false)

  const loadPreview = async () => {
    setLoading(true)
    try {
      setPreview(await ledgerApi.recallPreview(projectId, chapter))
    } catch {
      setPreview(null)
    } finally {
      setLoading(false)
    }
  }

  const search = async () => {
    if (!query.trim()) return
    setSearching(true)
    try {
      const res = await ledgerApi.search(projectId, query.trim())
      setResults(res.items)
      setSemantic(res.semantic)
    } catch {
      setResults([])
    } finally {
      setSearching(false)
    }
  }

  const total = preview?.sections.reduce((s, x) => s + x.chars, 0) ?? 0

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="hh-panel p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-content-secondary">
          写第<input type="number" min={1} value={chapter} onChange={(e) => setChapter(Math.max(1, Number(e.target.value) || 1))} className="h-8 w-20 text-xs" />章时
          <button onClick={() => void loadPreview()} disabled={loading} className="hh-btn-primary hh-btn-sm">
            {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}预览召回
          </button>
          {preview && <span className="text-content-tertiary">共 {formatChars(total)}（最终还会按提示词预算裁剪，出场角色与状态不裁）</span>}
        </div>
        {!preview ? (
          <p className="py-10 text-center text-xs leading-6 text-content-tertiary">选一个章号，看看写这一章时会带上哪些前情、旧事、伏笔和人物状态。</p>
        ) : preview.sections.length === 0 ? (
          <p className="py-10 text-center text-xs text-content-tertiary">这一章之前还没有可召回的内容</p>
        ) : (
          <div>
            {preview.sections.map((s) => (
              <CollapseSection key={s.key} title={<>{s.title}<span className="ml-2 text-[11px] font-normal text-content-tertiary">{formatChars(s.chars)}</span></>} defaultOpen={['characters', 'relevant_history'].includes(s.key)}>
                <pre className="whitespace-pre-wrap break-words font-sans text-xs leading-6 text-content-secondary">{s.text}</pre>
              </CollapseSection>
            ))}
            {preview.relevant_items.length > 0 && (
              <div className="mt-3">
                <p className="mb-2 text-xs font-semibold text-content">相关旧事为什么被选中</p>
                <ul className="space-y-1.5">
                  {preview.relevant_items.map((item) => (
                    <li key={item.id} className="hh-subpanel p-2.5 text-xs leading-5">
                      <div className="flex flex-wrap items-center gap-1">
                        <Pill>{KIND_LABELS[item.kind] ?? item.kind}</Pill>
                        <span className="text-content-tertiary">第{item.chapter_number}章 · 得分 {item.score.toFixed(2)}</span>
                      </div>
                      <p className="mt-0.5 text-content">{item.text}</p>
                      <p className="text-[11px] text-content-tertiary">{item.reasons.join('；')}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      <aside className="hh-panel p-4">
        <p className="mb-2 text-sm font-semibold text-content">在账本里找</p>
        <div className="relative mb-3">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void search()} placeholder="人名、物品、事件…（回车）" className="h-8 w-full pl-7 text-xs" />
        </div>
        {searching ? (
          <div className="flex justify-center py-6"><Loader2 className="h-4 w-4 animate-spin text-brand" /></div>
        ) : results === null ? (
          <p className="text-xs leading-6 text-content-tertiary">按关键词找章节档案、伏笔、事件；向量模型可用时也按语义找。</p>
        ) : results.length === 0 ? (
          <p className="text-xs text-content-tertiary">没找到</p>
        ) : (
          <ul className="space-y-1.5">
            {!semantic && <li className="text-[11px] text-content-tertiary">向量模型未加载，只按关键词找</li>}
            {results.map((r) => (
              <li key={r.id} className="hh-subpanel p-2.5 text-xs leading-5">
                <div className="flex flex-wrap items-center gap-1">
                  <Pill>{r.kind_label}</Pill>
                  <span className="text-content-tertiary">第{r.chapter_number}章 · {MATCH_LABELS[r.match] ?? r.match}</span>
                </div>
                <p className="mt-0.5 text-content">{r.text}</p>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  )
}
