/**
 * 智能助笔 · 改动（参照 AI 编程软件的改动审阅）：
 * - 对话里每条回复只留一行「改动 N 项 · 待确认 …」，点开每张卡一行，再点看明细（完整卡片）；
 * - 输入框上方的待确认栏集中处理整段对话里还没处理的卡：单条建档 / 应用 / 确认 / 放弃，或先确认一次再全部处理。
 * 对话的最后一条永远是团队的回复，不会被卡片顶上去。
 */
import { useState, type ReactNode } from 'react';
import { Check, ChevronRight, ChevronUp, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { batchConfirmText, changeSummary, pendingSummary, type ChangeItem, type ChangeState } from '@/utils/cocreation';

const DOT: Record<ChangeState, string> = {
  pending: 'bg-gold-400', done: 'bg-emerald-500', dropped: 'bg-neutral-300', open: 'bg-brand', missing: 'bg-cinnabar',
  gone: 'bg-neutral-300',
};

/** 单条处理：返回 false = 没成功（调用方已提示）；quiet = 批量处理时不逐条提示 */
export type DecideChange = (item: ChangeItem, action: 'apply' | 'reject', opts?: { quiet?: boolean }) => Promise<boolean>;

/** 点开一行看到的完整卡片；showActions = false：操作按钮在那一行上，卡片只给看（两套按钮会被同时点到） */
export type RenderDetail = (item: ChangeItem, opts: { showActions: boolean }) => ReactNode;

const APPLY_LABEL: Record<ChangeItem['ref']['kind'], string> = { field: '应用', entity: '建档', plan: '确认', chapter: '去审阅' };
const REJECT_LABEL: Partial<Record<ChangeItem['ref']['kind'], string>> = { field: '不用', entity: '不建' };

function ChangeRow({ item, open, onToggle, children, actions }: {
  item: ChangeItem;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <li className="border-t border-surface-border-light first:border-t-0">
      <div className="flex items-center gap-2 px-3 py-2">
        <button onClick={onToggle} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <span className={cn('as-dot', DOT[item.state])} />
          <span className="as-kind shrink-0">{item.tag}</span>
          <span className="min-w-0 flex-1 truncate text-[13px] text-content" title={item.title}>{item.title}</span>
          {!actions && <span className="shrink-0 text-[12px] text-content-tertiary">{item.status}</span>}
          <ChevronRight className={cn('h-3.5 w-3.5 flex-none text-content-tertiary transition-transform', open && 'rotate-90')} />
        </button>
        {actions}
      </div>
      {open && <div className="border-t border-surface-border-light bg-surface-paper px-2.5 py-2.5">{children}</div>}
    </li>
  );
}

/** 回复里的那一行改动：默认收起 */
export function ChangeList({ items, renderDetail }: { items: ChangeItem[]; renderDetail: RenderDetail }) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  if (!items.length) return null;
  return (
    <details className="as-disclosure">
      <summary className="w-fit text-[12px] text-content-tertiary hover:text-content-secondary">
        <ChevronRight className="as-chevron h-3.5 w-3.5" />{changeSummary(items)}
      </summary>
      <ul className="mt-1.5 overflow-hidden rounded-[10px] border border-surface-border-light bg-white">
        {items.map((item) => (
          <ChangeRow key={item.key} item={item} open={openKey === item.key} onToggle={() => setOpenKey((k) => (k === item.key ? null : item.key))}>
            {renderDetail(item, { showActions: true })}
          </ChangeRow>
        ))}
      </ul>
    </details>
  );
}

/** 输入框上方的待确认栏：平时一行，点开逐条处理；「全部采用 / 全部放弃」先确认一次，逐条提交，某条失败就停下 */
export function PendingTray({ items, open, onOpenChange, detailKey, onDetailChange, renderDetail, onDecide, onBatchEnd }: {
  items: ChangeItem[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 展开看明细的那一行 */
  detailKey: string | null;
  onDetailChange: (key: string | null) => void;
  renderDetail: RenderDetail;
  onDecide: DecideChange;
  /** 全部处理做完（或中途停下）：通知页面刷新 */
  onBatchEnd?: () => void;
}) {
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<'apply' | 'reject' | null>(null);
  const [batch, setBatch] = useState<{ done: number; total: number } | null>(null);
  if (!items.length) return null;

  const rejectable = items.filter((i) => REJECT_LABEL[i.ref.kind]);
  const working = Boolean(batch) || Boolean(busyKey);

  const decideOne = async (item: ChangeItem, action: 'apply' | 'reject') => {
    setBusyKey(item.key);
    try {
      await onDecide(item, action);
    } finally {
      setBusyKey(null);
    }
  };

  const runBatch = async (action: 'apply' | 'reject') => {
    const targets = action === 'apply' ? items : rejectable;
    setConfirming(null);
    setBatch({ done: 0, total: targets.length });
    let done = 0;
    try {
      for (const item of targets) {
        setBusyKey(item.key);
        if (!(await onDecide(item, action, { quiet: true }))) {
          onOpenChange(true);
          onDetailChange(item.key); // 停在没成功的那条，展开给作者看原因
          break;
        }
        done += 1;
        setBatch({ done, total: targets.length });
      }
    } finally {
      setBusyKey(null);
      setBatch(null);
      onBatchEnd?.();
    }
    if (done === targets.length) toast.success(`已全部${action === 'apply' ? '采用' : '放弃'}（${done} 项）`);
    else if (done) toast.info(`前 ${done} 项已处理，后面的没动`);
  };

  return (
    <section className="mb-2 overflow-hidden rounded-[14px] border border-surface-border bg-white shadow-[0_2px_10px_-6px_rgba(29,36,32,0.18)]">
      <div className="flex items-center gap-2 px-3 py-2">
        <button onClick={() => onOpenChange(!open)} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <span className="as-dot bg-gold-400" />
          <span className="shrink-0 text-[13px] font-medium text-content">{items.length} 项待你确认</span>
          <span className="min-w-0 truncate text-[12px] text-content-tertiary">
            {batch ? `正在处理 ${batch.done + 1}/${batch.total}…` : pendingSummary(items)}
          </span>
          <ChevronUp className={cn('h-3.5 w-3.5 flex-none text-content-tertiary transition-transform', !open && 'rotate-180')} />
        </button>
        {batch ? <Loader2 className="h-4 w-4 flex-none animate-spin text-brand" /> : !confirming && (
          <button onClick={() => setConfirming('apply')} disabled={working} className="as-btn-primary h-7 rounded-full px-3 text-[12px]">
            全部采用
          </button>
        )}
      </div>

      {confirming && (
        <div className="flex flex-wrap items-center gap-2 border-t border-surface-border-light bg-surface-paper px-3 py-2">
          <span className="min-w-0 flex-1 text-[12px] text-content-secondary">{batchConfirmText(items, confirming)}，确定吗？</span>
          <button onClick={() => setConfirming(null)} className="as-btn-ghost h-7 px-2.5 text-[12px]">取消</button>
          <button
            onClick={() => void runBatch(confirming)}
            className={cn('h-7 px-3 text-[12px]', confirming === 'apply' ? 'as-btn-primary' : 'as-btn-danger')}
          >
            {confirming === 'apply' ? '确定采用' : '确定放弃'}
          </button>
        </div>
      )}

      {open && (
        <>
          <ul className="max-h-[42vh] overflow-y-auto border-t border-surface-border-light">
            {items.map((item) => {
              const busy = busyKey === item.key;
              const reject = REJECT_LABEL[item.ref.kind];
              return (
                <ChangeRow
                  key={item.key}
                  item={item}
                  open={detailKey === item.key}
                  onToggle={() => onDetailChange(detailKey === item.key ? null : item.key)}
                  actions={(
                    <span className="flex flex-none items-center gap-1">
                      {reject ? (
                        <button onClick={() => void decideOne(item, 'reject')} disabled={working} className="as-btn-reject h-7 px-2 text-[12px]">
                          {reject}
                        </button>
                      ) : (
                        <span aria-hidden="true" className="as-btn-reject invisible h-7 px-2 text-[12px]">不用</span>
                      )}
                      <button onClick={() => void decideOne(item, 'apply')} disabled={working} className="as-btn-primary h-7 px-2.5 text-[12px]">
                        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}{APPLY_LABEL[item.ref.kind]}
                      </button>
                    </span>
                  )}
                >
                  {renderDetail(item, { showActions: false })}
                </ChangeRow>
              );
            })}
          </ul>
          {rejectable.length > 0 && (
            <div className="flex items-center border-t border-surface-border-light px-3 py-1.5">
              <button onClick={() => setConfirming('reject')} disabled={working} className="as-link text-[12px] text-content-tertiary hover:text-cinnabar">
                全部放弃
              </button>
              <span className="ml-auto text-[11px] text-content-tertiary">点一行看明细</span>
            </div>
          )}
        </>
      )}
    </section>
  );
}
