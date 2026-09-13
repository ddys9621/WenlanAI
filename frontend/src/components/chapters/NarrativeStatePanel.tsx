/** 叙事状态面板：承诺 / 伏笔、时间轴、关系变化、因果链、一致性审计 */
import type { ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { CollapseSection } from '@/components/ui/CollapseSection'
import { Pill, type PillTone } from '@/components/ui/Pill'
import type { NormalizedAnalysisData } from '@/utils/chapterAnalysis'

const SEV_TONE: Record<string, PillTone> = { critical: 'red', high: 'orange', medium: 'gold', low: 'default' }
const SEV_LABEL: Record<string, string> = { critical: '严重', high: '高', medium: '中', low: '低' }
const SEV_BORDER: Record<string, string> = { critical: '#ef4444', high: '#f59e0b', medium: '#f59e0b' }
const P_STATUS_TONE: Record<string, PillTone> = { open: 'brand', progressing: 'orange', resolved: 'green', broken: 'red' }
const P_STATUS_LABEL: Record<string, string> = { open: '未解', progressing: '推进中', resolved: '已回收', broken: '已破裂' }
const P_TYPE_LABEL: Record<string, string> = { foreshadow: '伏笔', promise: '承诺', mystery: '悬念', conflict: '冲突' }

function Item({ accent, children }: { accent: string; children: ReactNode }) {
  return <div className="hh-subpanel border-l-[3px] p-3" style={{ borderLeftColor: accent }}>{children}</div>
}

const Meta = ({ children }: { children: ReactNode }) => <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-content-tertiary">{children}</div>

export function NarrativeStatePanel({ data, loading }: { data: NormalizedAnalysisData | null; loading: boolean }) {
  if (loading) return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>
  if (!data) return <p className="py-12 text-center text-xs text-content-tertiary">暂无叙事状态数据</p>

  const ns = data.narrative_state
  const ca = data.consistency_audit
  const promises = ns?.promises ?? []
  const timeline = ns?.timeline_events ?? []
  const relGraph = ns?.relationship_graph
  const causal = ns?.causal_links ?? []
  const issues = ca?.issues ?? []
  const summary = ca?.summary

  const sections: { key: string; label: string; badge: number; children: ReactNode }[] = []

  if (promises.length > 0) {
    sections.push({
      key: 'promises',
      label: '🔮 承诺 / 伏笔',
      badge: promises.length,
      children: (
        <div className="flex flex-col gap-2">
          {promises.map((p, i) => {
            const st = String(p.status || 'open')
            const pt = String(p.promise_type || '')
            const pr = String(p.priority || '')
            return (
              <Item key={String(p.id || i)} accent={st === 'resolved' ? '#10b981' : st === 'broken' ? '#ef4444' : '#007aff'}>
                <div className="mb-1 flex flex-wrap gap-1">
                  {pt && <Pill tone="purple">{P_TYPE_LABEL[pt] || pt}</Pill>}
                  <Pill tone={P_STATUS_TONE[st] || 'default'}>{P_STATUS_LABEL[st] || st}</Pill>
                  {pr === 'critical' && <Pill tone="red">紧急</Pill>}
                  {pr === 'high' && <Pill tone="orange">高优</Pill>}
                </div>
                <div className="text-[13px] font-semibold text-content">{String(p.title || '未命名')}</div>
                {Boolean(p.content) && <div className="mt-1 text-xs text-content-secondary">{String(p.content)}</div>}
                <Meta>
                  {Boolean(p.owner_character_name) && <span>发起: {String(p.owner_character_name)}</span>}
                  {Boolean(p.target_character_name) && <span>对象: {String(p.target_character_name)}</span>}
                  {p.source_chapter_number != null && <span>第{String(p.source_chapter_number)}章埋设</span>}
                  {p.resolved_chapter_number != null && <span>第{String(p.resolved_chapter_number)}章回收</span>}
                </Meta>
              </Item>
            )
          })}
        </div>
      ),
    })
  }

  if (timeline.length > 0) {
    sections.push({
      key: 'timeline',
      label: '⏱️ 时间轴事件',
      badge: timeline.length,
      children: (
        <div className="flex flex-col gap-2">
          {timeline.map((evt, i) => {
            const actors = (evt.actor_names as string[]) || []
            const targets = (evt.target_names as string[]) || []
            return (
              <Item key={String(evt.id || i)} accent="#007aff">
                <div className="mb-1 flex gap-1">
                  {Boolean(evt.event_type) && <Pill tone="brand">{String(evt.event_type)}</Pill>}
                  {evt.public_visibility === 'secret' && <Pill>秘密</Pill>}
                </div>
                <div className="text-[13px] font-semibold text-content">{String(evt.title || '未命名事件')}</div>
                {Boolean(evt.description) && <div className="mt-1 text-xs text-content-secondary">{String(evt.description)}</div>}
                <Meta>
                  {Boolean(evt.location) && <span>📍 {String(evt.location)}</span>}
                  {Boolean(evt.time_marker) && <span>🕐 {String(evt.time_marker)}</span>}
                  {actors.length > 0 && <span>参与: {actors.join(', ')}</span>}
                  {targets.length > 0 && <span>目标: {targets.join(', ')}</span>}
                </Meta>
              </Item>
            )
          })}
        </div>
      ),
    })
  }

  if (relGraph && relGraph.edges.length > 0) {
    sections.push({
      key: 'relationship',
      label: '💞 关系变化',
      badge: relGraph.edges.length,
      children: (
        <div className="flex flex-col gap-2">
          {relGraph.edges.map((e, i) => {
            const d = Number(e.delta || 0)
            return (
              <Item key={i} accent={d > 0 ? '#10b981' : d < 0 ? '#ef4444' : '#d9e4f3'}>
                <div className="flex items-center gap-1.5 text-[13px]">
                  <span className="font-semibold text-content">{String(e.source)}</span>
                  <span className="text-content-tertiary">→</span>
                  <span className="font-semibold text-content">{String(e.target)}</span>
                  <Pill tone={d > 0 ? 'green' : d < 0 ? 'red' : 'default'} className="ml-auto tabular-nums">{d > 0 ? '+' : ''}{d}</Pill>
                </div>
                <Meta>
                  {Boolean(e.reason) && <span>{String(e.reason)}</span>}
                  {Boolean(e.new_status) && <span>状态: {String(e.new_status)}</span>}
                </Meta>
              </Item>
            )
          })}
        </div>
      ),
    })
  }

  if (causal.length > 0) {
    sections.push({
      key: 'causal',
      label: '🔗 因果链',
      badge: causal.length,
      children: (
        <div className="flex flex-col gap-2">
          {causal.map((lk, i) => (
            <Item key={i} accent="#f59e0b">
              <div className="mb-1 flex gap-1">
                <Pill tone="gold">重要度 {Number(lk.importance || 0)}</Pill>
                {Boolean(lk.reversible) && <Pill tone="green">可逆</Pill>}
              </div>
              <div className="text-xs leading-7 text-content">
                {Boolean(lk.cause) && <div><b>起因：</b>{String(lk.cause)}</div>}
                {Boolean(lk.event) && <div><b>事件：</b>{String(lk.event)}</div>}
                {Boolean(lk.decision) && <div><b>决策：</b>{String(lk.decision)}</div>}
                {Boolean(lk.effect) && <div><b>影响：</b>{String(lk.effect)}</div>}
              </div>
            </Item>
          ))}
        </div>
      ),
    })
  }

  if (summary && summary.total > 0) {
    sections.push({
      key: 'audit',
      label: '🛡️ 一致性审计',
      badge: summary.total,
      children: (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-1.5">
            {summary.critical > 0 && <Pill tone="red">严重 {summary.critical}</Pill>}
            {summary.high > 0 && <Pill tone="orange">高 {summary.high}</Pill>}
            {summary.medium > 0 && <Pill tone="gold">中 {summary.medium}</Pill>}
            {summary.low > 0 && <Pill>低 {summary.low}</Pill>}
          </div>
          {issues.map((iss, i) => {
            const sev = String(iss.severity || 'medium')
            return (
              <Item key={i} accent={SEV_BORDER[sev] || '#d9e4f3'}>
                <div className="mb-1 flex gap-1">
                  <Pill tone={SEV_TONE[sev] || 'default'}>{SEV_LABEL[sev] || sev}</Pill>
                  {Boolean(iss.issue_type) && <Pill>{String(iss.issue_type)}</Pill>}
                </div>
                <div className="text-[13px] font-semibold text-content">{String(iss.title || '未命名问题')}</div>
                {Boolean(iss.details) && <div className="mt-1 text-xs text-content-secondary">{String(iss.details)}</div>}
                <Meta>
                  {Boolean(iss.character_name) && <span>角色: {String(iss.character_name)}</span>}
                  {iss.reference_chapter_number != null && <span>参考: 第{String(iss.reference_chapter_number)}章</span>}
                </Meta>
              </Item>
            )
          })}
        </div>
      ),
    })
  }

  if (sections.length === 0) {
    return <p className="py-12 text-center text-xs text-content-tertiary">本章暂无叙事状态数据</p>
  }

  return (
    <div>
      {sections.map((s) => (
        <CollapseSection key={s.key} title={s.label} count={s.badge}>{s.children}</CollapseSection>
      ))}
    </div>
  )
}
