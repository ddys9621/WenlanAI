/**
 * 人物状态：按章回放「写第 N 章时」每个人的生死 / 位置 / 境界 / 物品 / 伤势 / 目标 / 能力。
 * 点开一个人看每次变化出自哪章、原文怎么写；记错了就加一条作者修正（同章盖过 AI，重新分析不清）。
 */
import { useCallback, useEffect, useState } from 'react'
import { Loader2, Plus, Trash2, UserRound } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { ledgerApi } from '@/services/api'
import { Pill } from '@/components/ui/Pill'
import type { CharacterHistoryRow, CharacterStateRow, CorrectionType, StateCorrectionCreate } from '@/types/ledger'
import { CORRECTION_TYPES, correctionOption, describeSignal, lifeLabel, validateCorrection } from '@/utils/ledger'

const ROLE_LABELS: Record<string, string> = { protagonist: '主角', antagonist: '反派', major: '主要', supporting: '配角', minor: '龙套' }

export function CharactersTab({ projectId, latestChapter }: { projectId: string; latestChapter: number }) {
  const [asOf, setAsOf] = useState(latestChapter + 1)
  const [rows, setRows] = useState<CharacterStateRow[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [history, setHistory] = useState<CharacterHistoryRow[]>([])
  const [form, setForm] = useState<StateCorrectionCreate>({
    character_name: '', chapter_number: Math.max(1, latestChapter), signal_type: 'life_state', signal_value: 'survived',
  })
  const [saving, setSaving] = useState(false)

  const load = useCallback(async (chapter: number) => {
    setLoading(true)
    try {
      setRows((await ledgerApi.characters(projectId, chapter)).items)
    } catch {
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [projectId])

  const loadHistory = useCallback(async (name: string) => {
    try {
      setHistory((await ledgerApi.characterHistory(projectId, name)).items)
    } catch {
      setHistory([])
    }
  }, [projectId])

  useEffect(() => { void load(asOf) }, [load]) // eslint-disable-line react-hooks/exhaustive-deps

  const open = (name: string) => {
    setSelected(name)
    setForm((f) => ({ ...f, character_name: name }))
    void loadHistory(name)
  }

  const setType = (type: CorrectionType) => {
    const option = correctionOption(type)
    setForm((f) => ({ ...f, signal_type: type, signal_value: option.values[0].value, signal_key: option.needsKey ? f.signal_key : undefined }))
  }

  const submit = async () => {
    const error = validateCorrection(form)
    if (error) { toast.error(error); return }
    setSaving(true)
    try {
      await ledgerApi.addCorrection(projectId, { ...form, signal_key: form.signal_key?.trim() || undefined, note: form.note?.trim() || undefined })
      toast.success('已修正，重新分析也不会冲掉')
      setForm((f) => ({ ...f, signal_key: '', note: '' }))
      await load(asOf)
      if (selected) await loadHistory(selected)
    } catch {
      /* 全局已 toast */
    } finally {
      setSaving(false)
    }
  }

  const removeCorrection = async (id: string) => {
    if (!confirm('撤销这条作者修正？')) return
    try {
      await ledgerApi.deleteCorrection(projectId, id)
      await load(asOf)
      if (selected) await loadHistory(selected)
    } catch {
      /* 全局已 toast */
    }
  }

  const option = correctionOption(form.signal_type)

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="hh-panel p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-content-secondary">
          写第
          <input type="number" min={1} value={asOf} onChange={(e) => setAsOf(Math.max(1, Number(e.target.value) || 1))} onKeyDown={(e) => e.key === 'Enter' && void load(asOf)} className="h-8 w-20 text-xs" />
          章时
          <button onClick={() => void load(asOf)} className="hh-btn-secondary hh-btn-sm">回放</button>
          <span className="text-content-tertiary">（只算这一章之前的分析结果与作者修正）</span>
        </div>
        {loading ? (
          <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>
        ) : rows.length === 0 ? (
          <p className="py-10 text-center text-xs text-content-tertiary">还没有人物状态：分析章节后会自动记下</p>
        ) : (
          <div className="grid gap-2 md:grid-cols-2">
            {rows.map((r) => {
              const absent = r.life === 'dead' || r.life === 'missing'
              return (
                <button key={r.name} onClick={() => open(r.name)} className={cn('hh-subpanel p-3 text-left transition-colors hover:border-brand/40', selected === r.name && 'ring-1 ring-brand/40', absent && 'opacity-80')}>
                  <div className="mb-1 flex items-center gap-1.5">
                    <UserRound className="h-3.5 w-3.5 text-content-tertiary" />
                    <span className="text-[13px] font-semibold text-content">{r.name}</span>
                    {r.role && <Pill>{ROLE_LABELS[r.role] ?? r.role}</Pill>}
                    {absent && <Pill tone="red">{lifeLabel(r.life)}{r.life_chapter ? `（第${r.life_chapter}章）` : ''}</Pill>}
                    {r.corrections > 0 && <Pill tone="brand">作者修正 {r.corrections}</Pill>}
                  </div>
                  <div className="space-y-0.5 text-xs leading-5 text-content-secondary">
                    {r.location && <p>位置：{r.location}</p>}
                    {r.realm && <p>境界：{r.realm}</p>}
                    {r.injuries.length > 0 && <p>伤势：{r.injuries.join('、')}</p>}
                    {r.items.length > 0 && <p>持有：{r.items.slice(0, 6).join('、')}</p>}
                    {r.abilities.length > 0 && <p>能力：{r.abilities.slice(0, 6).join('、')}</p>}
                    {r.goal && <p>目标：{r.goal}</p>}
                    {r.last_seen && <p className="text-content-tertiary">最近出场：第{r.last_seen}章</p>}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </section>

      <aside className="hh-panel space-y-4 p-4">
        <div>
          <p className="mb-2 text-sm font-semibold text-content">作者修正</p>
          <div className="grid gap-2">
            <select value={form.signal_type} onChange={(e) => setType(e.target.value as CorrectionType)} className="h-8 text-xs">
              {CORRECTION_TYPES.map((o) => <option key={o.type} value={o.type}>{o.label}</option>)}
            </select>
            {option.needsCharacter && (
              <input value={form.character_name} onChange={(e) => setForm({ ...form, character_name: e.target.value })} placeholder="人物" className="h-8 text-xs" />
            )}
            <div className="flex items-center gap-2 text-xs text-content-secondary">
              第<input type="number" min={1} value={form.chapter_number} onChange={(e) => setForm({ ...form, chapter_number: Number(e.target.value) })} className="h-8 w-20 text-xs" />章结束时
              <select value={form.signal_value} onChange={(e) => setForm({ ...form, signal_value: e.target.value })} className="h-8 flex-1 text-xs">
                {option.values.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
              </select>
            </div>
            {option.needsKey && (
              <input value={form.signal_key ?? ''} onChange={(e) => setForm({ ...form, signal_key: e.target.value })} placeholder={option.keyLabel} className="h-8 text-xs" />
            )}
            <input value={form.note ?? ''} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="备注（可选，如：只是假死）" className="h-8 text-xs" />
            <button onClick={() => void submit()} disabled={saving} className="hh-btn-primary hh-btn-sm justify-center">
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}添加修正
            </button>
            <p className="text-[11px] leading-5 text-content-tertiary">从这一章之后生效（写第 {form.chapter_number + 1} 章起），同一章盖过 AI 的结论；重新分析不会清掉。</p>
          </div>
        </div>

        {selected && (
          <div>
            <p className="mb-2 text-sm font-semibold text-content">{selected} 的变化记录</p>
            {history.length === 0 ? (
              <p className="text-xs text-content-tertiary">没有记录</p>
            ) : (
              <ul className="space-y-1.5">
                {history.map((h) => (
                  <li key={`${h.source}-${h.id}`} className="flex items-start gap-2 text-xs leading-5">
                    <Pill tone={h.source === 'author' ? 'brand' : 'default'}>{h.source === 'author' ? '作者' : 'AI'}</Pill>
                    <div className="min-w-0 flex-1">
                      <span className="text-content-tertiary">第{h.chapter_number}章 · </span>
                      <span className="text-content">{describeSignal(h)}</span>
                      {h.evidence && <p className="text-[11px] text-content-tertiary">{h.source === 'ai' ? `原文：「${h.evidence}」` : h.evidence}</p>}
                    </div>
                    {h.source === 'author' && (
                      <button onClick={() => void removeCorrection(h.id)} className="hh-icon-btn-plain h-6 w-6 hover:text-cinnabar" title="撤销修正" aria-label="撤销修正">
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </aside>
    </div>
  )
}
