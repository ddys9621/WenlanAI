/**
 * 作品备忘：你的长期偏好、拍板了的约定、要避开的写法。
 * 每轮开跑都带给团队（成员接手时也带上），开新对话不丢；团队听到长期偏好会自己记一条（标「团队记的」），这里能改、能删。
 */
import { useCallback, useEffect, useState } from 'react';
import { Check, Loader2, NotebookPen, Pencil, Plus, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { assistantApi } from '@/services/api';
import type { AssistantMemo } from '@/types/assistant';
import { errorDetail } from './changeActions';

const LIMIT = 200;
const INPUT = 'block w-full resize-none !rounded-none !border-0 !bg-transparent px-2.5 py-2 text-[13px] leading-6 !text-content outline-none placeholder:!text-content-tertiary focus:!shadow-none';

interface MemoPanelProps {
  projectId: string;
  onClose: () => void;
  /** 团队在运行里记了新的（memo 事件）就加一，面板开着时跟着重读 */
  version?: number;
}

export function MemoPanel({ projectId, onClose, version = 0 }: MemoPanelProps) {
  const [items, setItems] = useState<AssistantMemo[] | null>(null);
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems((await assistantApi.memos(projectId)).items);
    } catch {
      setItems([]);
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load, version]);

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await work();
      await load();
      return true;
    } catch (err) {
      toast.error(errorDetail(err));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = async () => {
    const text = draft.trim();
    if (text && await act(() => assistantApi.addMemo(projectId, text))) setDraft('');
  };

  const save = async () => {
    if (!editing?.text.trim()) return;
    if (await act(() => assistantApi.updateMemo(projectId, editing.id, editing.text.trim()))) setEditing(null);
  };

  const remove = (memo: AssistantMemo) => {
    if (window.confirm(`删掉这条备忘？\n\n${memo.content}`)) void act(() => assistantApi.deleteMemo(projectId, memo.id));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2.5">
        <span className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-brand-50 text-brand">
          <NotebookPen className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold text-content">作品备忘</h3>
          <p className="mt-1 text-[12px] leading-5 text-content-tertiary">
            你的长期偏好、拍板了的约定、要避开的写法。每轮都会带给团队，开新对话也不丢；团队听到长期偏好会自己记一条。
          </p>
        </div>
        <button onClick={onClose} className="ws-icon-btn h-7 w-7 flex-none" title="关闭" aria-label="关闭作品备忘">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="ws-composer">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void add();
            }
          }}
          rows={2}
          maxLength={LIMIT}
          placeholder="一条一句话，比如：女主从不哭；感情线只写暗线；每章 3000 字左右"
          className={INPUT}
          aria-label="新的一条备忘"
        />
        <div className="flex items-center justify-end gap-2 px-2.5 pb-2">
          {draft.length > LIMIT * 0.8 && <span className="text-[11px] tabular-nums text-gold-500">{draft.length}/{LIMIT}</span>}
          <button onClick={() => void add()} disabled={!draft.trim() || busy} className="as-btn-primary px-3">
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}记一条
          </button>
        </div>
      </div>

      {items === null ? (
        <div className="flex justify-center py-6"><Loader2 className="h-4 w-4 animate-spin text-brand" /></div>
      ) : items.length === 0 ? (
        <p className="as-meta px-1">还没有备忘。说过「以后都…」「不要…」这类话，团队会记在这里。</p>
      ) : (
        <ul className="space-y-1.5" aria-label="备忘列表">
          {items.map((m) => (
            <li key={m.id} className="as-card group px-3 py-2">
              {editing?.id === m.id ? (
                <div className="space-y-1.5">
                  <textarea
                    value={editing.text}
                    onChange={(e) => setEditing({ id: m.id, text: e.target.value })}
                    rows={2}
                    maxLength={LIMIT}
                    autoFocus
                    className={`${INPUT} rounded-[6px] !bg-surface`}
                    aria-label="修改这条备忘"
                  />
                  <div className="flex justify-end gap-1.5">
                    <button onClick={() => setEditing(null)} className="as-chip" disabled={busy}>取消</button>
                    <button onClick={() => void save()} className="as-chip as-chip--on" disabled={busy || !editing.text.trim()}>
                      <Check className="h-3.5 w-3.5" />保存
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-2">
                  <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-[13px] leading-6 text-content">{m.content}</p>
                  {m.source === 'team' && <span className="as-meta mt-1 flex-none">团队记的</span>}
                  <span className="flex flex-none items-center gap-0.5 opacity-60 transition-opacity group-hover:opacity-100">
                    <button onClick={() => setEditing({ id: m.id, text: m.content })} className="ws-icon-btn h-7 w-7" title="改" disabled={busy}>
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button onClick={() => remove(m)} className="ws-icon-btn h-7 w-7 hover:text-cinnabar" title="删" disabled={busy}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </span>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
