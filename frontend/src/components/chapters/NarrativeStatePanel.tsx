/** 叙事状态面板：承诺 / 伏笔、时间轴、关系变化、因果链、一致性审计（antd 风格，随原剧情分析页搬出） */
import React from 'react'
import { Card, Empty, Tag, Spin, Collapse } from 'antd'
import type { NormalizedAnalysisData } from '@/utils/chapterAnalysis'

const SEV_COLOR: Record<string, string> = { critical: 'red', high: 'orange', medium: 'gold', low: 'default' }
const SEV_LABEL: Record<string, string> = { critical: '严重', high: '高', medium: '中', low: '低' }
const P_STATUS_COLOR: Record<string, string> = { open: 'blue', progressing: 'orange', resolved: 'green', broken: 'red' }
const P_STATUS_LABEL: Record<string, string> = { open: '未解', progressing: '推进中', resolved: '已回收', broken: '已破裂' }
const P_TYPE_LABEL: Record<string, string> = { foreshadow: '伏笔', promise: '承诺', mystery: '悬念', conflict: '冲突' }

export function NarrativeStatePanel({ data, loading }: { data: NormalizedAnalysisData | null; loading: boolean }) {
  if (loading) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
  if (!data) return <Empty description="暂无叙事状态数据" style={{ marginTop: 60 }} />

  const ns = data.narrative_state
  const ca = data.consistency_audit
  const promises = ns?.promises ?? []
  const timeline = ns?.timeline_events ?? []
  const relGraph = ns?.relationship_graph
  const causal = ns?.causal_links ?? []
  const issues = ca?.issues ?? []
  const summary = ca?.summary

  const sections: { key: string; label: string; badge: number; children: React.ReactNode }[] = []

  if (promises.length > 0) {
    sections.push({
      key: 'promises',
      label: '🔮 承诺 / 伏笔',
      badge: promises.length,
      children: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {promises.map((p, i) => {
            const st = String(p.status || 'open')
            const pt = String(p.promise_type || '')
            const pr = String(p.priority || '')
            return (
              <Card key={String(p.id || i)} size="small" style={{ borderLeft: `3px solid ${st === 'resolved' ? '#10b981' : st === 'broken' ? '#ef4444' : '#007aff'}` }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
                  {pt && <Tag color="purple">{P_TYPE_LABEL[pt] || pt}</Tag>}
                  <Tag color={P_STATUS_COLOR[st] || 'default'}>{P_STATUS_LABEL[st] || st}</Tag>
                  {pr === 'critical' && <Tag color="red">紧急</Tag>}
                  {pr === 'high' && <Tag color="orange">高优</Tag>}
                </div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{String(p.title || '未命名')}</div>
                {Boolean(p.content) && <div style={{ fontSize: 12, color: '#5f7090', marginTop: 4 }}>{String(p.content)}</div>}
                <div style={{ fontSize: 11, color: '#93a4be', marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {Boolean(p.owner_character_name) && <span>发起: {String(p.owner_character_name)}</span>}
                  {Boolean(p.target_character_name) && <span>对象: {String(p.target_character_name)}</span>}
                  {p.source_chapter_number != null && <span>第{String(p.source_chapter_number)}章埋设</span>}
                  {p.resolved_chapter_number != null && <span>第{String(p.resolved_chapter_number)}章回收</span>}
                </div>
              </Card>
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {timeline.map((evt, i) => {
            const actors = (evt.actor_names as string[]) || []
            const targets = (evt.target_names as string[]) || []
            return (
              <Card key={String(evt.id || i)} size="small" style={{ borderLeft: '3px solid #007aff' }}>
                <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                  {Boolean(evt.event_type) && <Tag color="blue">{String(evt.event_type)}</Tag>}
                  {evt.public_visibility === 'secret' && <Tag>秘密</Tag>}
                </div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{String(evt.title || '未命名事件')}</div>
                {Boolean(evt.description) && <div style={{ fontSize: 12, color: '#5f7090', marginTop: 4 }}>{String(evt.description)}</div>}
                <div style={{ fontSize: 11, color: '#93a4be', marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {Boolean(evt.location) && <span>📍 {String(evt.location)}</span>}
                  {Boolean(evt.time_marker) && <span>🕐 {String(evt.time_marker)}</span>}
                  {actors.length > 0 && <span>参与: {actors.join(', ')}</span>}
                  {targets.length > 0 && <span>目标: {targets.join(', ')}</span>}
                </div>
              </Card>
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {relGraph.edges.map((e, i) => {
            const d = Number(e.delta || 0)
            return (
              <Card key={i} size="small" style={{ borderLeft: `3px solid ${d > 0 ? '#10b981' : d < 0 ? '#ef4444' : '#d9e4f3'}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                  <span style={{ fontWeight: 600 }}>{String(e.source)}</span>
                  <span style={{ color: '#93a4be' }}>→</span>
                  <span style={{ fontWeight: 600 }}>{String(e.target)}</span>
                  <Tag color={d > 0 ? 'green' : d < 0 ? 'red' : 'default'} style={{ marginLeft: 'auto' }}>{d > 0 ? '+' : ''}{d}</Tag>
                </div>
                <div style={{ fontSize: 11, color: '#93a4be', marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {Boolean(e.reason) && <span>{String(e.reason)}</span>}
                  {Boolean(e.new_status) && <span>状态: {String(e.new_status)}</span>}
                </div>
              </Card>
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {causal.map((lk, i) => (
            <Card key={i} size="small" style={{ borderLeft: '3px solid #f59e0b' }}>
              <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                <Tag color="gold">重要度 {Number(lk.importance || 0)}</Tag>
                {Boolean(lk.reversible) && <Tag color="green">可逆</Tag>}
              </div>
              <div style={{ fontSize: 12, lineHeight: 1.8 }}>
                {Boolean(lk.cause) && <div><b>起因：</b>{String(lk.cause)}</div>}
                {Boolean(lk.event) && <div><b>事件：</b>{String(lk.event)}</div>}
                {Boolean(lk.decision) && <div><b>决策：</b>{String(lk.decision)}</div>}
                {Boolean(lk.effect) && <div><b>影响：</b>{String(lk.effect)}</div>}
              </div>
            </Card>
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {summary.critical > 0 && <Tag color="red">严重 {summary.critical}</Tag>}
            {summary.high > 0 && <Tag color="orange">高 {summary.high}</Tag>}
            {summary.medium > 0 && <Tag color="gold">中 {summary.medium}</Tag>}
            {summary.low > 0 && <Tag>低 {summary.low}</Tag>}
          </div>
          {issues.map((iss, i) => {
            const sev = String(iss.severity || 'medium')
            return (
              <Card key={i} size="small" style={{ borderLeft: `3px solid ${sev === 'critical' ? '#ef4444' : sev === 'high' ? '#f59e0b' : sev === 'medium' ? '#f59e0b' : '#d9e4f3'}` }}>
                <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                  <Tag color={SEV_COLOR[sev] || 'default'}>{SEV_LABEL[sev] || sev}</Tag>
                  {Boolean(iss.issue_type) && <Tag>{String(iss.issue_type)}</Tag>}
                </div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{String(iss.title || '未命名问题')}</div>
                {Boolean(iss.details) && <div style={{ fontSize: 12, color: '#5f7090', marginTop: 4 }}>{String(iss.details)}</div>}
                <div style={{ fontSize: 11, color: '#93a4be', marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {Boolean(iss.character_name) && <span>角色: {String(iss.character_name)}</span>}
                  {iss.reference_chapter_number != null && <span>参考: 第{String(iss.reference_chapter_number)}章</span>}
                </div>
              </Card>
            )
          })}
        </div>
      ),
    })
  }

  if (sections.length === 0) {
    return <Empty description="本章暂无叙事状态数据" style={{ marginTop: 60 }} />
  }

  return (
    <div style={{ padding: 12 }}>
      <Collapse
        defaultActiveKey={sections.map(s => s.key)}
        ghost
        items={sections.map(s => ({
          key: s.key,
          label: (
            <span style={{ fontWeight: 600, fontSize: 13 }}>
              {s.label} <Tag style={{ marginLeft: 4 }}>{s.badge}</Tag>
            </span>
          ),
          children: s.children,
        }))}
      />
    </div>
  )
}
