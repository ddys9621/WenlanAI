/** 全局智能助笔 ·「核对」界面：本书现在需要注意的事项（只读）；点一条去对应页面处理，或让助笔排个先后。 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';
import { assistantApi } from '@/services/api';
import type { AssistantCheckItem, AssistantChecks as ChecksData } from '@/types/assistant';

const GROUPS: { kind: string; label: string; tone: string }[] = [
  { kind: 'consistency', label: '一致性问题', tone: 'lj-badge--danger' },
  { kind: 'outline_unconfirmed', label: '章纲待确认 / 上游已改', tone: 'lj-badge--stale' },
  { kind: 'analysis_stale', label: '分析已过期', tone: 'lj-badge--stale' },
  { kind: 'analysis_missing', label: '尚未分析', tone: 'lj-badge--muted' },
  { kind: 'candidate_pending', label: '章节候选稿待审', tone: 'lj-badge--candidate' },
  { kind: 'field_candidate', label: '内容修改候选待确认', tone: 'lj-badge--candidate' },
];

interface AssistantChecksProps {
  projectId: string;
  onNavigate: (page: string, search?: string) => void;
  onAsk: (text: string) => void;
  onOpenConversation: () => void;
}

export function AssistantChecks({ projectId, onNavigate, onAsk, onOpenConversation }: AssistantChecksProps) {
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
    if (item.kind === 'field_candidate') return onOpenConversation();
    if (item.page === 'chapter-analysis' && item.target_id) {
      return onNavigate('chapter-analysis', `chapter=${item.target_id}${item.kind === 'candidate_pending' ? '&tab=candidates' : ''}`);
    }
    if (item.page) onNavigate(item.page);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-surface-border-light px-3 py-2">
        <p className="text-xs text-content-secondary">
          {data ? (data.items.length ? `需要注意 ${data.items.length} 项` : '目前没有需要处理的事项') : '读取中…'}
        </p>
        <button onClick={() => void load()} disabled={loading} className="hh-btn-ghost hh-btn-sm h-7 px-2 text-[11px]">
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}刷新
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {error && <p className="rounded border border-cinnabar/30 bg-cinnabar-wash px-3 py-2 text-xs text-cinnabar">{error}</p>}
        {data && !data.items.length && (
          <p className="rounded border border-dashed border-surface-border bg-surface-paper px-3 py-6 text-center text-xs text-content-tertiary">
            章纲都已确认，写过的章节分析都是最新的，也没有待审的候选。
          </p>
        )}
        {grouped.map((g) => (
          <section key={g.kind}>
            <p className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-content-tertiary">
              <span className={cn('lj-badge', g.tone)}>{g.items.length}</span>{g.label}
            </p>
            <ul className="divide-y divide-surface-border-light rounded border border-surface-border-light bg-white">
              {g.items.map((item, i) => (
                <li key={`${item.kind}-${item.target_id ?? i}-${i}`}>
                  <button onClick={() => open(item)} className="group flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-surface-hover">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-medium text-content">{item.title}</span>
                      {item.detail && <span className="block line-clamp-2 text-[11px] leading-5 text-content-tertiary">{item.detail}</span>}
                    </span>
                    <ArrowUpRight className="mt-0.5 h-3.5 w-3.5 flex-none text-content-tertiary group-hover:text-brand" />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      {data && data.items.length > 0 && (
        <div className="border-t border-surface-border bg-white px-3 py-2">
          <button
            onClick={() => onAsk('看看这本书现在有哪些需要我处理的事项，按优先级列出来，并说明先做哪件。')}
            className="hh-btn-secondary hh-btn-sm h-8 w-full justify-center"
          >
            <Sparkles className="h-3.5 w-3.5" />让助笔帮我排个先后
          </button>
        </div>
      )}
    </div>
  );
}
