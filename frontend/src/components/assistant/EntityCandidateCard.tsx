/**
 * 新建对象候选：列出拟新建的角色 / 组织 / 设定条目 / 世界规则字段（名称、顺序由后端照页面给），作者「建档」才真正写入，可放弃；
 * 建过档、书里却找不到了（被删了或当时没写进去）就标出来，可以重新建档。与内容修改候选并列。
 */
import { useState } from 'react';
import { ArrowUpRight, Check, Loader2, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import type { AssistantEntityCandidate } from '@/types/assistant';
import { getRoleDisplayName } from '@/utils/characterRole';
import { entityKind } from '@/utils/cocreation';
import { entityAction, errorDetail } from './changeActions';
import { StatusDot, type StatusTone } from './CocreationParts';

const STATUS: Record<AssistantEntityCandidate['status'], { label: string; tone: StatusTone }> = {
  candidate: { label: '待确认', tone: 'orange' },
  applied: { label: '已建档', tone: 'green' },
  rejected: { label: '没有采用', tone: 'gray' },
};
const MISSING: { label: string; tone: StatusTone } = { label: '已不在书里', tone: 'red' };

const VALUE_LABELS: Record<string, Record<string, string>> = {
  category: { term: '术语', law: '铁律', faction: '势力', rule: '规则', other: '其他' },
};

const valueLabel = (key: string, value: string) => (key === 'role_type' ? getRoleDisplayName(value) : VALUE_LABELS[key]?.[value] ?? value);

interface EntityCandidateCardProps {
  projectId: string;
  candidate: AssistantEntityCandidate;
  onChange: (next: AssistantEntityCandidate) => void;
  onOpenPage?: (page: string) => void;
  /** false = 只看内容（在待确认栏里展开时，建档 / 不建在那一行上，不再重复一套） */
  showActions?: boolean;
}

export function EntityCandidateCard({ projectId, candidate, onChange, onOpenPage, showActions = true }: EntityCandidateCardProps) {
  const [busy, setBusy] = useState(false);
  const missing = candidate.status === 'applied' && Boolean(candidate.entity_missing);
  const status = missing ? MISSING : STATUS[candidate.status];
  const fields = candidate.payload;
  const rows = (candidate.fields ?? [])
    .filter((f) => fields[f.key])
    .map((f) => ({ key: f.key, label: f.label, value: valueLabel(f.key, fields[f.key]) }));
  const pending = showActions && candidate.status === 'candidate';
  const rebuild = showActions && missing;
  const canOpen = candidate.status === 'applied' && !missing && candidate.page && onOpenPage;

  const act = async (action: 'apply' | 'reject') => {
    setBusy(true);
    try {
      onChange(await entityAction(projectId, candidate, action));
      toast.success(action === 'reject' ? '已放弃这份新建候选' : `${missing ? '已重新建档' : '已建档'}：${candidate.label}`);
    } catch (err) {
      toast.error(errorDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="as-card">
      <header className="as-card-head">
        <div className="flex items-center gap-2">
          <span className="as-kind">新建{entityKind(candidate)}</span>
          <span className="ml-auto"><StatusDot tone={status.tone} label={status.label} /></span>
        </div>
        <p className="mt-1.5 truncate text-[14px] font-semibold text-content">{fields.name || fields.title || candidate.label}</p>
        {candidate.reason && <p className="mt-1 text-[13px] leading-[1.6] text-content-secondary">{candidate.reason}</p>}
      </header>
      <div className="max-h-64 overflow-y-auto px-4 pb-3.5">
        {rows.length === 0
          ? <p className="as-meta">只有名字，其余留空（建档后可在页面补充）</p>
          : (
            <dl className="as-fields">
              {rows.map((r) => (
                <div key={r.key} className="contents">
                  <dt>{r.label}</dt>
                  <dd>{r.value}</dd>
                </div>
              ))}
            </dl>
          )}
      </div>
      {(pending || canOpen || rebuild) && (
        <footer className="as-card-foot">
          {canOpen && (
            <button onClick={() => onOpenPage(candidate.page!)} className="as-link mr-auto">
              去页面查看<ArrowUpRight className="h-3.5 w-3.5" />
            </button>
          )}
          {rebuild && (
            <>
              <span className="mr-auto min-w-0 text-[12px] leading-[1.5] text-content-tertiary">建过档，但书里现在找不到它（被删了，或当时没写进去）</span>
              <button onClick={() => void act('apply')} disabled={busy} className="as-btn-secondary flex-none">
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}重新建档
              </button>
            </>
          )}
          {pending && (
            <>
              <button onClick={() => void act('reject')} disabled={busy} className="as-btn-reject">不建</button>
              <button onClick={() => void act('apply')} disabled={busy} className="as-btn-primary">
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}建档
              </button>
            </>
          )}
        </footer>
      )}
    </section>
  );
}
