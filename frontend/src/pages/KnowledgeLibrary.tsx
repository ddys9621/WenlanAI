/**
 * 知识库书架（用户级、跨项目）+ 全库关键词检索。
 * 拆书完成的书自动出现在这里（打开书架时后端给还没入库的拆书补导）。
 */
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BookMarked, ChevronRight, Loader2, RefreshCw, Search, Sparkles, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';

import { knowledgeApi } from '@/services/api';
import type { KbSearchHit, KbSource } from '@/types/knowledge';
import { ENTRY_TYPE_LABEL, entryRangeLabel, sourceCountsLine } from '@/utils/knowledge';

const BTN =
  'inline-flex items-center gap-1.5 rounded-pill border border-surface-border bg-surface px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-hover disabled:opacity-50';
const BTN_PRIMARY =
  'inline-flex items-center gap-1.5 rounded-pill bg-brand px-3.5 py-1.5 text-xs font-medium text-white hover:bg-brand-600 disabled:opacity-50';

export default function KnowledgeLibrary() {
  const [sources, setSources] = useState<KbSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<KbSearchHit[] | null>(null);
  const [total, setTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSources(await knowledgeApi.listSources());
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '加载知识库失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runSearch = async () => {
    const q = query.trim();
    if (!q) {
      setHits(null);
      return;
    }
    setSearching(true);
    try {
      const result = await knowledgeApi.search({ q, limit: 50 });
      setHits(result.items);
      setTotal(result.total);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '检索失败');
    } finally {
      setSearching(false);
    }
  };

  const remove = async (source: KbSource) => {
    const tip = source.dissect_task_id
      ? `删除《${source.title}》会同时删除它的拆书任务；以它为对标书的项目会取消对标。确定吗？`
      : `确定删除《${source.title}》吗？`;
    if (!window.confirm(tip)) return;
    setDeletingId(source.id);
    try {
      await knowledgeApi.deleteSource(source.id);
      setSources((prev) => prev.filter((s) => s.id !== source.id));
      toast.success('已删除');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-6 py-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 rounded-pill bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
            <BookMarked className="h-3.5 w-3.5" />
            知识库
          </div>
          <h1 className="lj-page-title mt-2">知识库</h1>
          <p className="mt-1 text-sm text-content-secondary">
            拆过的书都在这里：导读、分卷、剧情单元、章卡、人物、写法与文风，每条都有原名版和去名版，可修改、可核对。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void load()} className={BTN}>
            <RefreshCw className="h-3.5 w-3.5" />
            刷新
          </button>
          <Link to="/book-dissect" className={BTN_PRIMARY}>
            <Sparkles className="h-3.5 w-3.5" />
            去拆书
          </Link>
        </div>
      </header>

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void runSearch();
        }}
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索全部知识库：人名、桥段、第37章……多个词用空格分开"
          className="flex-1 rounded-pill border border-surface-border bg-surface px-4 py-2 text-sm"
        />
        <button type="submit" disabled={searching} className={BTN_PRIMARY}>
          {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
          搜索
        </button>
      </form>

      {hits && (
        <section className="rounded-2xl border border-surface-border bg-surface p-4">
          <div className="mb-2 flex items-center justify-between text-xs text-content-tertiary">
            <span>
              命中 {total} 条{total > hits.length ? `（显示前 ${hits.length} 条）` : ''}
            </span>
            <button type="button" onClick={() => setHits(null)} className={BTN}>
              <X className="h-3 w-3" />
              收起
            </button>
          </div>
          {hits.length === 0 ? (
            <p className="py-6 text-center text-sm text-content-secondary">没有找到，换个词试试</p>
          ) : (
            <ul className="divide-y divide-surface-border">
              {hits.map((hit) => (
                <li key={hit.id} className="py-2">
                  <Link to={`/knowledge/${hit.source_id}?entry=${hit.id}`} className="block hover:text-brand">
                    <div className="flex flex-wrap items-center gap-2 text-sm text-content">
                      <span className="font-medium">{hit.title}</span>
                      <span className="text-xs text-content-tertiary">
                        《{hit.source_title}》· {ENTRY_TYPE_LABEL[hit.entry_type]}
                        {entryRangeLabel(hit) ? ` · ${entryRangeLabel(hit)}` : ''}
                      </span>
                    </div>
                    {hit.summary && <p className="mt-0.5 line-clamp-2 text-xs text-content-secondary">{hit.summary}</p>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {loading ? (
        <div className="flex items-center justify-center rounded-2xl border border-surface-border bg-surface py-16 text-content-secondary">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载中...
        </div>
      ) : sources.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-surface-border bg-surface px-6 py-16 text-center">
          <p className="text-base font-medium text-content">知识库还是空的</p>
          <p className="mt-1 text-sm text-content-secondary">到拆书页上传一本参考书，拆完会自动收进知识库。</p>
        </div>
      ) : (
        <ul className="space-y-3">
          {sources.map((source) => (
            <li
              key={source.id}
              className="rounded-2xl border border-surface-border bg-surface p-4 transition hover:border-brand/40 hover:bg-surface-hover"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <Link to={`/knowledge/${source.id}`} className="truncate text-base font-semibold text-content hover:text-brand">
                    《{source.title}》
                  </Link>
                  <div className="mt-1 flex flex-wrap gap-3 text-xs text-content-tertiary">
                    {source.genre && <span>{source.genre}</span>}
                    <span>{source.chapter_count} 章</span>
                    <span>约 {source.total_words.toLocaleString()} 字</span>
                    <span>{sourceCountsLine(source.entry_counts) || '暂无条目'}</span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Link to={`/knowledge/${source.id}`} className={BTN_PRIMARY}>
                    打开
                    <ChevronRight className="h-3 w-3" />
                  </Link>
                  <button
                    type="button"
                    onClick={() => void remove(source)}
                    disabled={deletingId === source.id}
                    className={`${BTN} hover:border-rose-500/40 hover:text-rose-300`}
                  >
                    {deletingId === source.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                    删除
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
