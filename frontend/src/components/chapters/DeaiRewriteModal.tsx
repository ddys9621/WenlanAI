/** 去 AI 味重写：勾选项目提示词（可多选、可内联增删改）→ 只带提示词 + 原文重写 → 直接覆盖正文并清掉本章旧分析 */
import { useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { deaiPromptApi, type DeaiPrompt, type DeaiPromptInput } from '@/services/api';
import type { Chapter } from '@/types';

interface DeaiRewriteModalProps {
  open: boolean;
  projectId: string;
  chapter: Chapter;
  /** 正文任务进行中：禁用「开始重写」 */
  busy: boolean;
  onClose: () => void;
  /** 按勾选顺序的提示词 id */
  onConfirm: (promptIds: string[]) => void;
}

const EMPTY_FORM: DeaiPromptInput = { name: '', content: '' };

export function DeaiRewriteModal({ open, projectId, chapter, busy, onClose, onConfirm }: DeaiRewriteModalProps) {
  const [prompts, setPrompts] = useState<DeaiPrompt[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [editingId, setEditingId] = useState<string | 'new' | null>(null);
  const [form, setForm] = useState<DeaiPromptInput>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPrompts(await deaiPromptApi.list(projectId));
    } catch {
      toast.error('加载去 AI 味提示词失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!open) return;
    setSelected([]);
    setEditingId(null);
    setForm(EMPTY_FORM);
    void load();
  }, [open, load]);

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const startEdit = (p: DeaiPrompt | null) => {
    setEditingId(p ? p.id : 'new');
    setForm(p ? { name: p.name, content: p.content } : EMPTY_FORM);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
  };

  const savePrompt = async () => {
    const payload = { name: form.name.trim(), content: form.content.trim() };
    if (!payload.name || !payload.content) return;
    setSaving(true);
    try {
      if (editingId === 'new') {
        const created = await deaiPromptApi.create(projectId, payload);
        setPrompts((prev) => [...prev, created]);
        setSelected((prev) => [...prev, created.id]);
      } else if (editingId) {
        const updated = await deaiPromptApi.update(projectId, editingId, payload);
        setPrompts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      }
      cancelEdit();
    } catch {
      /* api 拦截器已 toast */
    } finally {
      setSaving(false);
    }
  };

  const removePrompt = async (p: DeaiPrompt) => {
    if (!confirm(`删除提示词「${p.name}」？`)) return;
    try {
      await deaiPromptApi.remove(projectId, p.id);
      setPrompts((prev) => prev.filter((x) => x.id !== p.id));
      setSelected((prev) => prev.filter((x) => x !== p.id));
      if (editingId === p.id) cancelEdit();
    } catch {
      /* api 拦截器已 toast */
    }
  };

  if (!open) return null;

  const canSave = !saving && form.name.trim().length > 0 && form.content.trim().length > 0;

  return createPortal(
    <div className="hh-modal-mask">
      <div className="hh-modal max-w-[680px]" role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div className="min-w-0">
            <p className="hh-eyebrow">去 AI 味重写</p>
            <h2 className="mt-2 truncate text-xl font-semibold tracking-tight text-content">{chapter.title}</h2>
            <p className="mt-1 text-sm text-content-secondary">
              勾选要注入的提示词，AI 只拿「提示词 + 本章正文」重写，不带章纲 / 前文 / 设定。
            </p>
          </div>
          <button onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="hh-modal-body space-y-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium text-content">项目去 AI 味提示词（可多选，按勾选顺序注入）</p>
            <button
              onClick={() => startEdit(null)}
              disabled={editingId !== null}
              className="hh-chip flex items-center gap-1 px-2 py-1 text-[11px] text-brand disabled:opacity-50"
            >
              <Plus className="h-3 w-3" />
              新增提示词
            </button>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 py-2 text-xs text-content-secondary">
              <Loader2 className="h-3 w-3 animate-spin" />
              加载提示词…
            </div>
          ) : prompts.length === 0 && editingId !== 'new' ? (
            <div className="border border-dashed border-surface-border bg-white/60 px-3 py-4 text-center text-xs leading-5 text-content-secondary">
              本项目还没有去 AI 味提示词，点右上角「新增提示词」写一条（例如：删掉“仿佛 / 似乎 / 一丝”，长句拆短，对话别加“淡淡地说”……）。
            </div>
          ) : (
            <div className="space-y-1.5">
              {prompts.map((p) => {
                if (editingId === p.id) return null;
                const order = selected.indexOf(p.id);
                return (
                  <label
                    key={p.id}
                    className="flex cursor-pointer items-start gap-2 border border-surface-border bg-white/80 px-3 py-2 text-xs hover:border-brand/40"
                  >
                    <input type="checkbox" className="mt-0.5" checked={order >= 0} onChange={() => toggle(p.id)} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="font-medium text-content">{p.name}</span>
                        {order >= 0 && (
                          <span className="bg-brand/10 px-1.5 py-px text-[10px] font-medium text-brand tabular-nums">#{order + 1}</span>
                        )}
                      </span>
                      <span className="mt-0.5 line-clamp-3 block whitespace-pre-wrap text-[11px] leading-5 text-content-tertiary">{p.content}</span>
                    </span>
                    <span className="flex shrink-0 gap-0.5">
                      <button
                        type="button"
                        onClick={(e) => { e.preventDefault(); startEdit(p); }}
                        className="hh-icon-btn-plain h-7 w-7 hover:text-brand"
                        title="编辑"
                        aria-label="编辑"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.preventDefault(); void removePrompt(p); }}
                        className="hh-icon-btn-plain h-7 w-7 hover:text-red-500"
                        title="删除"
                        aria-label="删除"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  </label>
                );
              })}
            </div>
          )}

          {editingId !== null && (
            <div className="space-y-2 border border-brand/25 bg-brand/5 p-3">
              <p className="text-xs font-medium text-content">{editingId === 'new' ? '新增提示词' : '编辑提示词'}</p>
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="名称，例如：删机器词"
                maxLength={100}
                className="hh-field text-xs"
              />
              <textarea
                value={form.content}
                onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
                placeholder="提示词正文，会原样放进重写提示词里"
                rows={5}
                className="hh-textarea !resize-y bg-white/80 text-xs"
              />
              <div className="flex justify-end gap-2">
                <button onClick={cancelEdit} className="hh-btn-ghost hh-btn-sm">取消</button>
                <button onClick={() => void savePrompt()} disabled={!canSave} className="hh-btn-primary hh-btn-sm">
                  {saving && <Loader2 className="h-3 w-3 animate-spin" />}
                  保存
                </button>
              </div>
            </div>
          )}

          <p className="text-[11px] leading-5 text-content-tertiary">
            重写完成后<span className="font-medium text-amber-600">直接覆盖正文，不留版本、不能回滚</span>；本章已有的分析结果（记忆标注、伏笔 / 承诺、一致性等）会一并清除，需要时可重新「分析」。
          </p>
        </div>

        <div className="hh-modal-foot">
          <button onClick={onClose} className="hh-btn-ghost">取消</button>
          <button
            onClick={() => onConfirm(selected)}
            disabled={busy || selected.length === 0 || editingId !== null}
            title={selected.length === 0 ? '先勾选至少一条提示词' : editingId !== null ? '先保存或取消正在编辑的提示词' : undefined}
            className={cn('hh-btn-primary', selected.length === 0 && 'opacity-60')}
          >
            <RefreshCw className="h-4 w-4" />
            开始重写{selected.length > 0 ? `（${selected.length} 条提示词）` : ''}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
