/**
 * 撤销本轮：先列出会撤回什么、哪些撤不了（为什么），作者确认了才撤。
 * 撤完按撤回的类型通知各页面刷新（undoRefreshes）。
 */
import { useEffect, useState } from 'react';
import { Check, Loader2, TriangleAlert, Undo2 } from 'lucide-react';
import { toast } from 'sonner';
import { Modal } from '@/components/ui/Modal';
import { assistantApi } from '@/services/api';
import type { AssistantUndoReport } from '@/types/assistant';
import { errorDetail } from './changeActions';

interface UndoRunDialogProps {
  projectId: string;
  runId: string;
  onClose: () => void;
  onDone: (report: AssistantUndoReport) => void;
}

export function UndoRunDialog({ projectId, runId, onClose, onDone }: UndoRunDialogProps) {
  const [preview, setPreview] = useState<AssistantUndoReport | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    assistantApi.undoPreview(projectId, runId)
      .then((data) => { if (!cancelled) setPreview(data); })
      .catch((err) => { if (!cancelled) setError(errorDetail(err)); });
    return () => { cancelled = true; };
  }, [projectId, runId]);

  const confirm = async () => {
    setBusy(true);
    try {
      onDone(await assistantApi.undoRun(projectId, runId));
    } catch (err) {
      toast.error(errorDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const doable = preview?.items.filter((i) => i.ok) ?? [];
  const blocked = preview?.items.filter((i) => !i.ok) ?? [];
  return (
    <Modal
      title="撤销本轮"
      size="md"
      onClose={busy ? () => {} : onClose}
      closable={!busy}
      footer={(
        <div className="flex justify-end gap-2">
          <button onClick={onClose} disabled={busy} className="hh-btn-ghost hh-btn-sm">取消</button>
          <button onClick={() => void confirm()} disabled={busy || !preview || !doable.length} className="hh-btn-primary hh-btn-sm">
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Undo2 className="h-3.5 w-3.5" />}
            撤回 {doable.length} 项
          </button>
        </div>
      )}
    >
      {error ? (
        <p className="text-[13px] text-cinnabar">{error}</p>
      ) : !preview ? (
        <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>
      ) : !preview.items.length ? (
        <p className="text-[13px] text-content-secondary">这一轮没有往书里写东西，不用撤。</p>
      ) : (
        <div className="space-y-4 text-[13px]">
          <p className="leading-6 text-content-secondary">
            把这一轮写进书里的东西撤回：修改改回原样、新建的删掉、自动采用的正文恢复到采用前、没采用的候选稿丢弃。
          </p>
          {doable.length > 0 && (
            <section>
              <h4 className="mb-1.5 text-[12px] font-medium text-content-tertiary">会撤回（{doable.length}）</h4>
              <ul className="space-y-1">
                {doable.map((i, n) => (
                  <li key={`ok-${n}`} className="flex items-start gap-2">
                    <Check className="mt-1 h-3.5 w-3.5 flex-none text-emerald-500" />
                    <span className="min-w-0"><span className="text-content">{i.label}</span><span className="text-content-tertiary"> · {i.action}</span></span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {blocked.length > 0 && (
            <section>
              <h4 className="mb-1.5 text-[12px] font-medium text-content-tertiary">撤不了（{blocked.length}）</h4>
              <ul className="space-y-1">
                {blocked.map((i, n) => (
                  <li key={`no-${n}`} className="flex items-start gap-2">
                    <TriangleAlert className="mt-1 h-3.5 w-3.5 flex-none text-gold-500" />
                    <span className="min-w-0"><span className="text-content">{i.label}</span><span className="text-content-tertiary"> · {i.reason}</span></span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </Modal>
  );
}
