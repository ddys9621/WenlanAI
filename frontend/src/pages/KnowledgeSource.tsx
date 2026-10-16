/**
 * 知识库来源详情：左侧按类型分组的条目目录，右侧阅读 / 编辑。
 * 每条有「原名版」（给作者读）和「去名版」（人名换成功能位，仿写注入用）；作者改过的条目重新拆书不会被覆盖。
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, Loader2, Pencil, RefreshCw, RotateCcw, Save, X } from 'lucide-react';
import { toast } from 'sonner';

import { EntryView, type EntryViewMode } from '@/components/knowledge/EntryView';
import { cn } from '@/lib/utils';
import { knowledgeApi } from '@/services/api';
import type { KbEntry, KbEntrySummary, KbSource } from '@/types/knowledge';
import { entryRangeLabel, groupEntries } from '@/utils/knowledge';

const BTN =
  'inline-flex items-center gap-1 rounded-pill border border-surface-border bg-surface px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-hover disabled:opacity-50';
const BTN_PRIMARY =
  'inline-flex items-center gap-1 rounded-pill bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-600 disabled:opacity-50';

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export default function KnowledgeSource() {
  const { sourceId = '' } = useParams<{ sourceId: string }>();
  const [params, setParams] = useSearchParams();
  const [source, setSource] = useState<KbSource | null>(null);
  const [entries, setEntries] = useState<KbEntrySummary[]>([]);
  const [entry, setEntry] = useState<KbEntry | null>(null);
  const [filter, setFilter] = useState('');
  const [mode, setMode] = useState<EntryViewMode>('named');
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const currentId = params.get('entry') ?? entries[0]?.id ?? null;

  useEffect(() => {
    let cancelled = false;
    Promise.all([knowledgeApi.getSource(sourceId), knowledgeApi.listEntries(sourceId)])
      .then(([s, list]) => {
        if (cancelled) return;
        setSource(s);
        setEntries(list);
      })
      .catch((err) => toast.error(errorText(err, '加载失败')));
    return () => {
      cancelled = true;
    };
  }, [sourceId]);

  useEffect(() => {
    if (!currentId) return;
    let cancelled = false;
    knowledgeApi
      .getEntry(currentId)
      .then((e) => {
        if (cancelled) return;
        setEntry(e);
        setDraft(null);
      })
      .catch((err) => toast.error(errorText(err, '加载条目失败')));
    return () => {
      cancelled = true;
    };
  }, [currentId]);

  const groups = useMemo(() => {
    const f = filter.trim();
    return groupEntries(f ? entries.filter((e) => e.title.includes(f) || e.summary.includes(f)) : entries);
  }, [entries, filter]);

  const replaceEntry = (next: KbEntry) => {
    setEntry(next);
    setEntries((prev) =>
      prev.map((e) =>
        e.id === next.id
          ? {
              ...e,
              title: next.title,
              summary: next.summary,
              origin: next.origin,
              status: next.status,
              upstream_changed: next.upstream_changed,
              revision: next.revision,
            }
          : e,
      ),
    );
  };

  const act = async (run: () => Promise<KbEntry>, ok: string) => {
    setBusy(true);
    try {
      replaceEntry(await run());
      setDraft(null);
      toast.success(ok);
    } catch (err) {
      toast.error(errorText(err, '操作失败'));
    } finally {
      setBusy(false);
    }
  };

  const reimport = async () => {
    setBusy(true);
    try {
      setSource(await knowledgeApi.reimportSource(sourceId));
      setEntries(await knowledgeApi.listEntries(sourceId));
      toast.success('已按最新拆书结果重新导入，作者改过的条目保持不变');
    } catch (err) {
      toast.error(errorText(err, '重新导入失败'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/knowledge" className="inline-flex items-center gap-1 text-xs text-content-secondary hover:text-brand">
            <ArrowLeft className="h-3 w-3" />
            返回知识库
          </Link>
          <h1 className="lj-page-title mt-1">{source ? `《${source.title}》` : '加载中…'}</h1>
          {source && (
            <p className="mt-1 text-xs text-content-tertiary">
              {source.chapter_count} 章 · 约 {source.total_words.toLocaleString()} 字{source.genre ? ` · ${source.genre}` : ''}
            </p>
          )}
        </div>
        {source?.dissect_task_id && (
          <button type="button" onClick={() => void reimport()} disabled={busy} className={BTN}>
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            按最新拆书结果重新导入
          </button>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="max-h-[75vh] overflow-y-auto rounded-2xl border border-surface-border bg-surface p-3">
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="筛选标题 / 摘要"
            className="mb-2 w-full rounded-lg border border-surface-border bg-surface px-3 py-1.5 text-sm"
          />
          {groups.map((group) => (
            <section key={group.type} className="mb-3">
              <h3 className="mb-1 text-xs font-medium text-content-tertiary">
                {group.label}（{group.items.length}）
              </h3>
              <ul className="space-y-0.5">
                {group.items.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => setParams({ entry: item.id })}
                      className={cn(
                        'w-full truncate rounded-lg px-2 py-1 text-left text-sm',
                        item.id === currentId ? 'bg-brand/10 text-brand' : 'text-content hover:bg-surface-hover',
                      )}
                    >
                      {item.title}
                      {entryRangeLabel(item) && <span className="ml-1 text-xs text-content-tertiary">{entryRangeLabel(item)}</span>}
                      {item.upstream_changed && <span className="ml-1 text-xs text-orange-300">●</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </aside>

        <main className="rounded-2xl border border-surface-border bg-surface p-4">
          {!entry ? (
            <div className="py-16 text-center text-sm text-content-secondary">选择左侧条目查看</div>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="inline-flex rounded-pill border border-surface-border p-0.5 text-xs">
                  {(['named', 'denamed'] as const).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => {
                        setMode(m);
                        setDraft(null);
                      }}
                      className={cn('rounded-pill px-3 py-1', mode === m ? 'bg-brand text-white' : 'text-content-secondary')}
                    >
                      {m === 'named' ? '原名版' : '去名版（仿写用）'}
                    </button>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2">
                  {draft === null ? (
                    <>
                      <button type="button" onClick={() => setDraft(mode === 'denamed' ? entry.denamed_body : entry.body)} className={BTN}>
                        <Pencil className="h-3 w-3" />
                        编辑
                      </button>
                      {entry.status !== 'confirmed' && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void act(() => knowledgeApi.confirmEntry(entry.id), '已标记为核对')}
                          className={BTN}
                        >
                          <CheckCircle2 className="h-3 w-3" />
                          标记已核对
                        </button>
                      )}
                      {(entry.origin === 'author' || entry.upstream_changed) && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            if (window.confirm('恢复成拆书生成的版本？作者的修改会被覆盖。')) {
                              void act(() => knowledgeApi.resetEntry(entry.id), '已恢复拆书版本');
                            }
                          }}
                          className={BTN}
                        >
                          <RotateCcw className="h-3 w-3" />
                          恢复拆书版本
                        </button>
                      )}
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void act(
                            () => knowledgeApi.updateEntry(entry.id, mode === 'denamed' ? { denamed_body: draft } : { body: draft }),
                            '已保存为作者版本',
                          )
                        }
                        className={BTN_PRIMARY}
                      >
                        <Save className="h-3 w-3" />
                        保存
                      </button>
                      <button type="button" onClick={() => setDraft(null)} className={BTN}>
                        <X className="h-3 w-3" />
                        取消
                      </button>
                    </>
                  )}
                </div>
              </div>
              {draft === null ? (
                <EntryView entry={entry} mode={mode} />
              ) : (
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  className="h-[60vh] w-full rounded-xl border border-surface-border bg-surface p-3 font-mono text-sm leading-6"
                />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
