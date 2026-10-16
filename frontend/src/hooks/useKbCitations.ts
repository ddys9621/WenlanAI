import { useEffect, useState } from 'react';

import { knowledgeApi } from '@/services/api';
import type { KbCitation, KbCitationTarget } from '@/types/knowledge';

/** 一批生成结果的对标引用（target_id → 引用）。version 变了（重新生成 / 刷新）就重新拉。 */
export function useKbCitations(
  projectId: string | undefined,
  targetType: KbCitationTarget,
  targetIds: string[],
  version = '',
): Record<string, KbCitation[]> {
  const [map, setMap] = useState<Record<string, KbCitation[]>>({});
  const key = `${targetIds.join(',')}|${version}`;
  useEffect(() => {
    const ids = key.split('|')[0].split(',').filter(Boolean);
    if (!projectId || ids.length === 0) return;
    let cancelled = false;
    knowledgeApi
      .citations(projectId, targetType, ids)
      .then((res) => { if (!cancelled) setMap(res ?? {}); })
      .catch(() => { if (!cancelled) setMap({}); });
    return () => { cancelled = true; };
  }, [projectId, targetType, key]);
  return map;
}
