/** 章纲遵循度审校报告：结论 + 问题 + 逐项核对（带原文引文，未核实的单列，不判失败） */
import { CheckCircle2, CircleAlert, CircleHelp, Quote } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { AdherenceReport } from '@/types/writing';
import { adherenceVerdict } from '@/utils/writingFlow';

const TONE_BADGE = { ok: 'lj-badge--ok', stale: 'lj-badge--stale', muted: 'lj-badge--muted', draft: 'lj-badge--draft' } as const;

function QuoteLine({ quote, verified }: { quote: string; verified: boolean }) {
  if (!quote) return null;
  return (
    <p className={cn('mt-1 flex items-start gap-1 text-[11px] leading-5', verified ? 'text-content-secondary' : 'text-content-tertiary line-through')}>
      <Quote className="mt-0.5 h-3 w-3 shrink-0" />
      <span>{quote}{!verified && '（正文里找不到）'}</span>
    </p>
  );
}

export function AdherenceReportView({ report, compact = false }: { report: AdherenceReport | null | undefined; compact?: boolean }) {
  const verdict = adherenceVerdict(report);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn('lj-badge', TONE_BADGE[verdict.tone])}>
          {verdict.tone === 'ok' ? <CheckCircle2 className="h-3 w-3" /> : verdict.tone === 'stale' ? <CircleAlert className="h-3 w-3" /> : <CircleHelp className="h-3 w-3" />}
          章纲审校：{verdict.label}
        </span>
        {report?.summary && <span className="text-xs text-content-secondary">{report.summary}</span>}
        {verdict.detail && <span className="text-xs text-content-tertiary">{verdict.detail}</span>}
      </div>

      {report && report.status === 'ok' && report.issues.length > 0 && (
        <ul className="space-y-1 rounded border border-signal/25 bg-signal-soft/50 px-3 py-2 text-xs text-cinnabar">
          {report.issues.map((issue) => <li key={issue}>· {issue}</li>)}
        </ul>
      )}

      {!compact && report && report.status === 'ok' && (
        <div className="space-y-2 text-xs">
          {(report.key_events?.length ?? 0) > 0 && (
            <div>
              <p className="mb-1 font-medium text-content">关键事件</p>
              <ul className="space-y-1.5">
                {report.key_events!.map((e) => (
                  <li key={e.event} className="rounded border border-surface-border-light bg-white px-2.5 py-1.5">
                    <span className={cn('font-medium', e.covered && e.verified ? 'text-brand-600' : 'text-cinnabar')}>
                      {e.covered && e.verified ? '已写到' : e.covered ? '引文未核实' : '没写到'}
                    </span>
                    <span className="ml-1.5 text-content">{e.event}</span>
                    <QuoteLine quote={e.quote} verified={e.verified} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {report.ending && (
            <div className="rounded border border-surface-border-light bg-white px-2.5 py-1.5">
              <span className={cn('font-medium', report.ending.reached && report.ending.verified ? 'text-brand-600' : 'text-cinnabar')}>
                章末落点：{report.ending.reached ? (report.ending.verified ? '已写到' : '引文未核实') : '没写到'}
              </span>
              <QuoteLine quote={report.ending.quote} verified={report.ending.verified} />
            </div>
          )}
          {(report.narrative_tasks?.length ?? 0) > 0 && (
            <div>
              <p className="mb-1 font-medium text-content">叙事任务</p>
              <ul className="space-y-1">
                {report.narrative_tasks!.map((t) => (
                  <li key={t.task} className="text-content-secondary">
                    <span className={t.done ? 'text-brand-600' : 'text-cinnabar'}>{t.done ? '完成' : '未完成'}</span>
                    <span className="ml-1.5">{t.task}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {report.unverified.length > 0 && (
            <div className="text-content-tertiary">
              <p className="mb-1 font-medium">模型提到但引文没核实的（不判失败）</p>
              <ul className="space-y-0.5">{report.unverified.map((u) => <li key={u}>· {u}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
