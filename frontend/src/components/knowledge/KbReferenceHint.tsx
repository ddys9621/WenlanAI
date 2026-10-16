/** 生成弹窗里的一行「仿写参考」：显示本书的对标书与仿写方式（项目级统一设置，弹窗里不改），链到设置页。 */
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { BookMarked } from 'lucide-react';

import type { KbProjectLink } from '@/types/knowledge';
import { kbHintText } from '@/utils/knowledge';

export function KbReferenceHint({
  projectId, link, children,
}: {
  projectId: string;
  link: KbProjectLink | null | undefined;
  children?: ReactNode;
}) {
  return (
    <div className="space-y-2 rounded border border-surface-border bg-surface-paper px-3 py-2.5 text-xs text-content-secondary">
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-1.5">
          <BookMarked className="h-3.5 w-3.5 text-brand" />
          <span className="font-medium text-content">仿写参考</span>
          <span>{kbHintText(link)}</span>
        </span>
        <Link to={`/project/${projectId}/knowledge`} className="shrink-0 text-brand hover:underline">
          {link ? '调整' : '去设置'}
        </Link>
      </div>
      {children}
    </div>
  );
}
