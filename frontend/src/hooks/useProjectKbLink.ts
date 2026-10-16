import { useEffect, useState } from 'react';

import { knowledgeApi } from '@/services/api';
import type { KbProjectLink } from '@/types/knowledge';

/** 项目的对标书（undefined = 加载中，null = 没设）；enabled=false 时不请求（弹窗没打开）。 */
export function useProjectKbLink(projectId: string | undefined, enabled = true): KbProjectLink | null | undefined {
  const [link, setLink] = useState<KbProjectLink | null | undefined>(undefined);
  useEffect(() => {
    if (!projectId || !enabled) return;
    let cancelled = false;
    knowledgeApi
      .getProjectLink(projectId)
      .then((res) => { if (!cancelled) setLink(res.link); })
      .catch(() => { if (!cancelled) setLink(null); });
    return () => { cancelled = true; };
  }, [projectId, enabled]);
  return link;
}
