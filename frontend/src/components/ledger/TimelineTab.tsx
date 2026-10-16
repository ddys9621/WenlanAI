/** 时间线 / 因果：按章列出分析记下的关键事件与因果链；可只看某个人物、某段章节 */
import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { ledgerApi } from '@/services/api'
import { Pill } from '@/components/ui/Pill'
import type { TimelineItem } from '@/types/ledger'
import { groupTimeline } from '@/utils/ledger'

export function TimelineTab({ projectId, characterNames }: { projectId: string; characterNames: string[] }) {
  const [character, setCharacter] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [items, setItems] = useState<TimelineItem[]>([])
  const [loading, setLoading] = useState(false)
  const [names, setNames] = useState<string[]>(characterNames)

  // 角色列表可能还没加载过（直接打开账本页）：用账本里有状态的人补上
  useEffect(() => {
    ledgerApi.characters(projectId)
      .then((res) => setNames((prev) => [...new Set([...prev, ...res.items.map((r) => r.name)])]))
      .catch(() => undefined)
  }, [projectId])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await ledgerApi.timeline(projectId, {
        character: character || undefined,
        from_chapter: from ? Number(from) : undefined,
        to_chapter: to ? Number(to) : undefined,
      })
      setItems(res.items)
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [projectId, character, from, to])

  useEffect(() => { void load() }, [character]) // eslint-disable-line react-hooks/exhaustive-deps

  const groups = groupTimeline(items)

  return (
    <section className="hh-panel p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-content-secondary">
        <select value={character} onChange={(e) => setCharacter(e.target.value)} className="h-8 text-xs">
          <option value="">全部人物</option>
          {names.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        第<input type="number" min={1} value={from} onChange={(e) => setFrom(e.target.value)} className="h-8 w-20 text-xs" />章
        到<input type="number" min={1} value={to} onChange={(e) => setTo(e.target.value)} className="h-8 w-20 text-xs" />章
        <button onClick={() => void load()} className="hh-btn-secondary hh-btn-sm">筛选</button>
      </div>
      {loading ? (
        <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>
      ) : groups.length === 0 ? (
        <p className="py-10 text-center text-xs text-content-tertiary">没有记录</p>
      ) : (
        <ol className="relative space-y-4 border-l border-surface-border pl-4">
          {groups.map((g) => (
            <li key={g.chapter}>
              <span className="absolute -left-1.5 mt-1 h-3 w-3 rounded-full border-2 border-white bg-brand" />
              <p className="mb-1.5 text-xs font-semibold text-content">第 {g.chapter} 章</p>
              <ul className="space-y-1.5">
                {g.items.map((item) => (
                  <li key={item.id} className="hh-subpanel p-2.5 text-xs leading-5">
                    {item.kind === 'event' ? (
                      <>
                        <div className="mb-0.5 flex flex-wrap items-center gap-1">
                          {item.event_type && <Pill tone="brand">{item.event_type}</Pill>}
                          {item.visibility === 'secret' && <Pill>秘密</Pill>}
                          <span className="font-medium text-content">{item.title}</span>
                        </div>
                        {item.description && item.description !== item.title && <p className="text-content-secondary">{item.description}</p>}
                        <p className="text-[11px] text-content-tertiary">
                          {[item.location && `📍${item.location}`, item.time_marker && `🕐${item.time_marker}`,
                            item.actors.length > 0 && `参与：${item.actors.join('、')}`, item.targets.length > 0 && `对象：${item.targets.join('、')}`]
                            .filter(Boolean).join(' · ')}
                        </p>
                      </>
                    ) : (
                      <>
                        <div className="mb-0.5 flex items-center gap-1"><Pill tone="gold">因果</Pill></div>
                        <p className="text-content">{[item.cause, item.event, item.effect].filter(Boolean).join(' → ')}</p>
                        {item.decision && <p className="text-content-secondary">决定：{item.decision}</p>}
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
