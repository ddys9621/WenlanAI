/** 建项目时选对标书（知识库里的书）+ 仿写方式；项目建好后后端会关联它。没有知识库时提示去拆书。 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BookMarked } from 'lucide-react';

import { knowledgeApi } from '@/services/api';
import type { KbMode, KbSource, KbSourceChoice } from '@/types/knowledge';
import { KB_MODE_OPTIONS } from '@/utils/knowledge';

export function KbSourcePicker({
  value, onChange, hint, disabled = false,
}: {
  value: KbSourceChoice;
  onChange: (next: KbSourceChoice) => void;
  hint?: string;
  disabled?: boolean;
}) {
  const [sources, setSources] = useState<KbSource[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    knowledgeApi
      .listSources()
      .then((list) => { if (!cancelled) setSources(list); })
      .catch(() => { if (!cancelled) setSources([]); });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="space-y-2 rounded border border-surface-border bg-surface-paper px-3 py-2.5 text-xs text-content-secondary">
      <div className="flex items-center gap-1.5">
        <BookMarked className="h-3.5 w-3.5 text-brand" />
        <span className="font-medium text-content">仿写参考（对标书）</span>
      </div>
      {sources === null ? (
        <p>读取知识库…</p>
      ) : sources.length === 0 ? (
        <p>
          知识库还是空的：先去<Link to="/book-dissect" className="mx-0.5 text-brand hover:underline">拆一本书</Link>，拆完就能选它做对标。
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={value.sourceId}
            disabled={disabled}
            onChange={(e) => onChange({ ...value, sourceId: e.target.value })}
            className="hh-field w-auto py-1 text-xs"
          >
            <option value="">不对标</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>《{s.title}》{s.genre ? ` · ${s.genre}` : ''}</option>
            ))}
          </select>
          {value.sourceId && (
            <select
              value={value.mode}
              disabled={disabled}
              onChange={(e) => onChange({ ...value, mode: e.target.value as KbMode })}
              className="hh-field w-auto py-1 text-xs"
            >
              {KB_MODE_OPTIONS.filter((o) => o.value !== 'off').map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          )}
        </div>
      )}
      {hint && <p className="text-content-tertiary">{hint}</p>}
    </div>
  );
}
