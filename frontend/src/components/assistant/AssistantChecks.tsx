/** 全局智能助笔 ·「核对」界面：本书现在需要注意的事项（只读）；点一条去对应页面处理，或让助笔排个先后。 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, ChevronRight, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';
import { assistantApi } from '@/services/api';
import type { AssistantCheckItem, AssistantChecks as ChecksData } from '@/types/assistant';

const GROUPS: { kind: string; label: string; dot: string }[] = [
  { kind: 'consistency', label: '一致性问题', dot: 'bg-cinnabar' },
  { kind: 'volume_unconfirmed', label: '卷纲待确认 / 上游已改', dot: 'bg-gold-400' },
  { kind: 'outline_unconfirmed', label: '章纲待确认 / 上游已改', dot: 'bg-gold-400' },
  { kind: 'analysis_stale', label: '分析已过期', dot: 'bg-gold-400' },
  { kind: 'analysis_missing', label: '尚未分析', dot: 'bg-neutral-300' },
  { kind: 'candidate_pending', label: '章节候选稿待审', dot: 'bg-brand' },
  { kind: 'field_candidate', label: '内容修改候选待确认', dot: 'bg-brand' },
  { kind: 'entity_candidate', label: '新建候选待建档', dot: 'bg-brand' },
];

interface AssistantChecksProps {
  projectId: string;
  onNavigate: (page: string, search?: string) => void;
  onAsk: (text: string) => void;
  /** 回到对话并展开输入框上方的待确认栏 */
  onOpenReview: () => void;
}

export function AssistantChecks({ projectId, onNavigate, onAsk, onOpenReview }: AssistantChecksProps) {
  const [data, setData] = useState<ChecksData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await assistantApi.checks(projectId));
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '核对清单读取失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  const grouped = useMemo(() => {
    const items = data?.items ?? [];
    return GROUPS.map((g) => ({ ...g, items: items.filter((i) => i.kind === g.kind) })).filter((g) => g.items.length);
  }, [data]);

  const open = (item: AssistantCheckItem) => {
    if (item.kind === 'field_candidate' || item.kind === 'entity_candidate') return onOpenReview();
    if (item.page === 'chapter-analysis' && item.target_id) {
      return onNavigate('chapter-analysis', `chapter=${item.target_id}${item.kind === 'candidate_pending' ? '&tab=candidates' : ''}`);
    }
    if (item.page) onNavigate(item.page);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-5">
        <div className="flex items-center justify-between pt-4">
          <p className="text-[13px] text-content-secondary">
            {data ? (data.items.length ? `需要注意 ${data.items.length} 项` : '目前没有需要处理的事项') : '读取中…'}
          </p>
          <button onClick={() => void load()} disabled={loading} className="as-icon-btn" title="刷新">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
        </div>
        {error && <p className="mt-3 rounded-[10px] bg-cinnabar-wash px-3.5 py-2.5 text-[13px] text-cinnabar">{error}</p>}
        {data && !data.items.length && (
          <div className="flex flex-col items-center pt-16 text-center">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand">
              <Check className="h-5 w-5" strokeWidth={2.5} />
            </span>
            <p className="mt-4 text-[16px] font-semibold text-content">一切就绪</p>
            <p className="mt-1.5 max-w-[280px] text-[13px] leading-[1.7] text-content-secondary">卷纲、章纲都已确认，写过的章节分析都是最新的，也没有待审的候选。</p>
          </div>
        )}
        {grouped.map((g) => (
          <section key={g.kind}>
            <p className="as-section-title">
              <span className={cn('as-dot', g.dot)} />{g.label}
              <span className="ml-auto text-[12px] font-normal tabular-nums text-content-tertiary">{g.items.length}</span>
            </p>
            <ul className="as-list">
              {g.items.map((item, i) => (
                <li key={`${item.kind}-${item.target_id ?? i}-${i}`}>
                  <button onClick={() => open(item)} className="as-row">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] text-content">{item.title}</span>
                      {item.detail && <span className="mt-0.5 block line-clamp-2 text-[12px] leading-[1.5] text-content-tertiary">{item.detail}</span>}
                    </span>
                    <ChevronRight className="h-4 w-4 flex-none text-content-tertiary" />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      {data && data.items.length > 0 && (
        <div className="flex-none border-t border-surface-border-light px-4 py-3">
          <button
            onClick={() => onAsk('看看这本书现在有哪些需要我处理的事项，按优先级列出来，并说明先做哪件。')}
            className="as-btn-primary h-9 w-full"
          >
            <Sparkles className="h-4 w-4" />让助笔帮我排个先后
          </button>
        </div>
      )}
    </div>
  );
}
