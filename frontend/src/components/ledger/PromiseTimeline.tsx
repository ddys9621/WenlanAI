/**
 * 全书悬念时间线：每条伏笔 / 承诺 / 悬念从埋设章画到回收章，没回收的画到当前进度（超过计划回收章标红），
 * 计划回收章画一道竖线、当前章画一条参考线。上面一行是核对建议：超期、掉线、临近计划回收各几条。
 */
import { useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Modal } from '@/components/ui/Modal';
import { ledgerApi } from '@/services/api';
import type { LedgerPromise } from '@/types/ledger';
import { PROMISE_TYPE_LABELS, promiseSpan } from '@/utils/ledger';

const BAR: Record<string, string> = {
  resolved: 'bg-brand/70', open: 'bg-gold-300/80', overdue: 'bg-cinnabar/70', abandoned: 'bg-neutral-300',
};

export function PromiseTimeline({ projectId, currentChapter, onClose }: { projectId: string; currentChapter?: number; onClose: () => void }) {
  const [items, setItems] = useState<LedgerPromise[] | null>(null);
  const [asOf, setAsOf] = useState(1);
  const [filter, setFilter] = useState<'active' | 'all'>('active');

  useEffect(() => {
    let cancelled = false;
    ledgerApi.promises(projectId, 'all')
      .then((res) => {
        if (cancelled) return;
        setItems([...res.items].sort((a, b) => a.source_chapter_number - b.source_chapter_number));
        setAsOf(res.as_of);
      })
      .catch(() => { if (!cancelled) setItems([]); });
    return () => { cancelled = true; };
  }, [projectId]);

  // as_of = 下一章（写到第 latest 章）：和伏笔清单的「超期」同一个口径（过了计划回收章还没回收）
  const latest = Math.max(1, asOf - 1);
  const rows = useMemo(() => (items ?? [])
    .filter((p) => filter === 'all' || !['resolved', 'abandoned'].includes(p.status))
    .map((p) => ({ p, span: promiseSpan(p, asOf) })), [asOf, filter, items]);
  const max = Math.max(asOf, currentChapter ?? 0, ...rows.map((r) => Math.max(r.span.end, r.span.deadline ?? 0)), 1);
  const pos = (n: number) => `${((Math.max(1, n) - 1) / Math.max(1, max - 1 || 1)) * 100}%`;
  const advice = useMemo(() => {
    const active = (items ?? []).filter((p) => p.flag);
    return {
      overdue: active.filter((p) => p.flag.includes('超期')).length,
      near: active.filter((p) => p.flag.includes('临近')).length,
      dropout: active.filter((p) => p.flag.includes('掉线')).length,
    };
  }, [items]);

  return (
    <Modal title="全书悬念时间线" size="2xl" onClose={onClose}>
      {items === null ? (
        <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>
      ) : !items.length ? (
        <p className="py-6 text-center text-[13px] text-content-tertiary">还没有伏笔记录：章节分析后会自动登记，也可以在故事账本里手动登记。</p>
      ) : (
        <div className="space-y-3 text-[12px]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-content-secondary">写到第 {latest} 章 · 核对建议：</span>
            <span className={cn(advice.overdue ? 'text-cinnabar' : 'text-content-tertiary')}>超期 {advice.overdue}</span>
            <span className={cn(advice.near ? 'text-gold-500' : 'text-content-tertiary')}>临近回收 {advice.near}</span>
            <span className={cn(advice.dropout ? 'text-gold-500' : 'text-content-tertiary')}>掉线 {advice.dropout}</span>
            <span className="ml-auto flex gap-1">
              {(['active', 'all'] as const).map((f) => (
                <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f} className={cn('as-chip', filter === f && 'as-chip--on')}>
                  {f === 'active' ? '未回收' : '全部'}
                </button>
              ))}
            </span>
          </div>
          <div className="flex justify-between pl-[34%] text-[11px] tabular-nums text-content-tertiary">
            <span>第 1 章</span><span>第 {max} 章</span>
          </div>
          <ul className="max-h-[60vh] space-y-1 overflow-y-auto pr-1">
            {rows.map(({ p, span }) => (
              <li key={p.id} className="flex items-center gap-2" title={`${p.content}${p.flag ? `\n${p.flag}` : ''}`}>
                <span className="w-[34%] min-w-0 truncate">
                  <span className="text-content-tertiary">{PROMISE_TYPE_LABELS[p.promise_type]} · </span>
                  <span className="text-content">{p.title}</span>
                </span>
                <span className="relative h-4 flex-1 rounded bg-surface">
                  {currentChapter ? <span className="absolute inset-y-0 w-px bg-brand/50" style={{ left: pos(currentChapter) }} /> : null}
                  <span
                    className={cn('absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full', BAR[span.state], span.state !== 'resolved' && 'opacity-80')}
                    style={{ left: pos(span.start), width: `max(6px, calc(${pos(span.end)} - ${pos(span.start)}))` }}
                  />
                  <span className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-brand" style={{ left: pos(span.start) }} />
                  {span.deadline ? <span className="absolute inset-y-0 w-0.5 bg-cinnabar/60" style={{ left: pos(span.deadline) }} title={`计划第 ${span.deadline} 章前回收`} /> : null}
                </span>
                <span className="w-24 flex-none text-right tabular-nums text-content-tertiary">
                  {span.state === 'resolved' ? `${span.start}→${span.end} 章` : `第 ${span.start} 章起`}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-content-tertiary">圆点 = 埋设章；墨绿 = 已回收，琥珀 = 还没回收，朱砂 = 超过计划回收章；红竖线 = 计划回收章{currentChapter ? '；细竖线 = 正在写的这一章' : ''}。</p>
        </div>
      )}
    </Modal>
  );
}
