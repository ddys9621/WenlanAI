/** 知识库条目阅读视图（纯展示）：标题、状态徽章、原名版 / 去名版正文。 */
import type { KbEntry } from '@/types/knowledge';
import { ENTRY_TYPE_LABEL, entryRangeLabel } from '@/utils/knowledge';

export type EntryViewMode = 'named' | 'denamed';

type BadgeEntry = Pick<KbEntry, 'entry_type' | 'chapter_start' | 'chapter_end' | 'origin' | 'status' | 'upstream_changed'>;

export function EntryBadges({ entry }: { entry: BadgeEntry }) {
  const range = entryRangeLabel(entry);
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="rounded-pill bg-brand/10 px-2 py-0.5 text-brand">{ENTRY_TYPE_LABEL[entry.entry_type] ?? entry.entry_type}</span>
      {range && <span className="rounded-pill bg-surface-hover px-2 py-0.5 text-content-secondary">{range}</span>}
      {entry.origin === 'author' && <span className="rounded-pill bg-amber-500/15 px-2 py-0.5 text-amber-300">作者已改</span>}
      {entry.status === 'confirmed' ? (
        <span className="rounded-pill bg-emerald-500/15 px-2 py-0.5 text-emerald-300">已核对</span>
      ) : (
        <span className="rounded-pill bg-surface-hover px-2 py-0.5 text-content-tertiary">未核对</span>
      )}
      {entry.upstream_changed && <span className="rounded-pill bg-orange-500/15 px-2 py-0.5 text-orange-300">拆书结果已更新</span>}
    </div>
  );
}

export function EntryView({ entry, mode }: { entry: KbEntry; mode: EntryViewMode }) {
  const text = mode === 'denamed' ? entry.denamed_body : entry.body;
  return (
    <article className="space-y-3">
      <header className="space-y-2">
        <h2 className="text-lg font-semibold text-content">{entry.title}</h2>
        <EntryBadges entry={entry} />
        {entry.summary && <p className="text-sm text-content-secondary">{entry.summary}</p>}
      </header>
      <pre className="whitespace-pre-wrap break-words rounded-xl border border-surface-border bg-surface px-4 py-3 font-sans text-sm leading-7 text-content">
        {text || '（空）'}
      </pre>
    </article>
  );
}
