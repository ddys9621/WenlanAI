/** 历史版本：正文每次被替换（手改 / 采用候选稿 / 恢复）前自动留档；可预览、可恢复（恢复前当前稿也会留档）。 */
import { useCallback, useEffect, useState } from 'react';
import { History, Loader2, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { chapterVersionApi } from '@/services/api';
import type { Chapter } from '@/types';
import type { ChapterVersionDetail, ChapterVersionRestoreResult, ChapterVersionSummary } from '@/types/writing';
import { formatServerTime } from '@/utils/serverTime';
import { versionReasonLabel } from '@/utils/writingFlow';

interface VersionHistoryPanelProps {
  chapter: Chapter;
  onRestored: (result: ChapterVersionRestoreResult) => void;
}

export function VersionHistoryPanel({ chapter, onRestored }: VersionHistoryPanelProps) {
  const [items, setItems] = useState<ChapterVersionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<ChapterVersionDetail | null>(null);
  const [restoring, setRestoring] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await chapterVersionApi.list(chapter.id);
      setItems(res.items);
      setSelected(null);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [chapter.id]);

  useEffect(() => { void load(); }, [load]);

  const open = async (id: string) => {
    try {
      setSelected(await chapterVersionApi.get(chapter.id, id));
    } catch {
      toast.error('读取历史版本失败');
    }
  };

  const restore = async () => {
    if (!selected) return;
    if (!window.confirm(`恢复到第 ${selected.version_number} 版？当前正文会先存进历史版本，本章旧分析会清除，需要时重新分析。`)) return;
    setRestoring(true);
    try {
      const result = await chapterVersionApi.restore(chapter.id, selected.id);
      toast.success(`已恢复到第 ${selected.version_number} 版`);
      onRestored(result);
      await load();
    } catch {
      /* 已 toast */
    } finally {
      setRestoring(false);
    }
  };

  if (loading && items.length === 0) {
    return <div className="flex flex-1 items-center justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>;
  }
  if (items.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 text-center">
        <History className="h-8 w-8 text-content-tertiary" />
        <p className="mt-3 text-sm font-medium text-content">还没有历史版本</p>
        <p className="mt-1 max-w-sm text-xs leading-5 text-content-tertiary">正文每次被替换（手动修改、采用候选稿、恢复旧版）之前，都会把原来那一稿存到这里。</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <ul className="shrink-0 divide-y divide-surface-border-light border-b border-surface-border lg:max-h-[calc(100dvh-300px)] lg:w-60 lg:overflow-y-auto lg:border-b-0 lg:border-r">
        {items.map((v) => (
          <li key={v.id}>
            <button
              onClick={() => void open(v.id)}
              className={cn('w-full px-3 py-2.5 text-left hover:bg-surface-hover', selected?.id === v.id && 'lj-selected')}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-content">第 {v.version_number} 版</span>
                <span className="text-[11px] text-content-tertiary tabular-nums">{v.word_count.toLocaleString()} 字</span>
              </div>
              <p className="mt-0.5 text-[11px] text-content-tertiary">{versionReasonLabel(v.reason)} · {formatServerTime(v.created_at)}</p>
              <p className="mt-1 line-clamp-2 text-xs leading-5 text-content-secondary">{v.preview}</p>
            </button>
          </li>
        ))}
      </ul>
      {selected ? (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border px-5 py-3">
            <div className="text-xs text-content-secondary">
              <span className="font-medium text-content">第 {selected.version_number} 版</span>
              <span className="ml-2">{versionReasonLabel(selected.reason)}</span>
              {selected.note && <span className="ml-2 text-content-tertiary">{selected.note}</span>}
            </div>
            <button onClick={() => void restore()} disabled={restoring} className="hh-btn-secondary hh-btn-sm">
              {restoring ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
              恢复此版本
            </button>
          </div>
          <div className="lj-manuscript min-h-[320px] flex-1 overflow-y-auto whitespace-pre-wrap px-5 py-4 text-[15px] leading-8 lg:max-h-[calc(100dvh-360px)]">
            {selected.content}
          </div>
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center px-6 py-16 text-sm text-content-tertiary">从左侧选一个版本预览</div>
      )}
    </div>
  );
}
