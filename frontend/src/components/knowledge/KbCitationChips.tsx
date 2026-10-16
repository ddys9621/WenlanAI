/** 生成结果上的「对标：原书……」标记：点开跳到知识库里那一条；条目改版或被删时标「已过期」。 */
import { Link } from 'react-router-dom';
import { BookMarked } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { KbCitation } from '@/types/knowledge';
import { citationText } from '@/utils/knowledge';

export function KbCitationChips({ citations, className }: { citations?: KbCitation[]; className?: string }) {
  if (!citations || citations.length === 0) return null;
  return (
    <div className={cn('flex flex-wrap gap-1', className)}>
      {citations.map((c, i) => (
        <Link
          key={`${c.entry_id}-${i}`}
          to={`/knowledge/${c.source_id}?entry=${c.entry_id}`}
          title={c.stale ? `${c.reason}（原书条目改过或已删除，重新生成时会重新对位）` : c.reason}
          className={cn(
            'inline-flex max-w-full items-center gap-1 truncate rounded-pill border px-2 py-0.5 text-[11px] hover:underline',
            c.stale ? 'border-amber-500/40 text-amber-600' : 'border-brand/30 text-brand',
          )}
        >
          <BookMarked className="h-3 w-3 shrink-0" />
          <span className="truncate">{citationText(c)}</span>
        </Link>
      ))}
    </div>
  );
}
