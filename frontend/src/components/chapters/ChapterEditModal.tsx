/** 新建 / 编辑章节弹窗（编辑态可一键仿写追加正文） */
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, Sparkles, X } from 'lucide-react';
import { toast } from 'sonner';
import { chapterApi } from '@/services/api';
import { useChapterSync } from '@/store/hooks';
import { ImitationDialog } from '@/components/ImitationDialog';
import type { Chapter } from '@/types';

interface ChapterEditModalProps {
  open: boolean;
  projectId: string;
  /** null = 新建 */
  editing: Chapter | null;
  defaultChapterNumber: number;
  onClose: () => void;
  onSaved: (chapterId: string) => void;
}

interface FormData {
  title: string;
  chapter_number: number;
  content: string;
}

export function ChapterEditModal({ open, projectId, editing, defaultChapterNumber, onClose, onSaved }: ChapterEditModalProps) {
  const { createChapter, updateChapter } = useChapterSync();
  const [form, setForm] = useState<FormData>({ title: '', chapter_number: 1, content: '' });
  const [submitting, setSubmitting] = useState(false);
  const [loadingContent, setLoadingContent] = useState(false);
  const [showImitationDialog, setShowImitationDialog] = useState(false);

  useEffect(() => {
    if (!open) return;
    setShowImitationDialog(false);
    if (!editing) {
      setForm({ title: '', chapter_number: defaultChapterNumber, content: '' });
      return;
    }
    setForm({ title: editing.title, chapter_number: editing.chapter_number, content: '' });
    setLoadingContent(true);
    let cancelled = false;
    chapterApi.getChapter(editing.id)
      .then((detail) => { if (!cancelled) setForm((prev) => ({ ...prev, content: detail.content || '' })); })
      .catch(() => { if (!cancelled) toast.error('加载章节内容失败'); })
      .finally(() => { if (!cancelled) setLoadingContent(false); });
    return () => { cancelled = true; };
  }, [open, editing, defaultChapterNumber]);

  const handleSubmit = async () => {
    if (!form.title.trim()) return;
    setSubmitting(true);
    try {
      if (editing) {
        // content 传原值（含空串）：`|| undefined` 会让"清空正文"被后端忽略而无法保存
        await updateChapter(editing.id, { title: form.title, content: form.content });
        toast.success('章节已更新');
        onSaved(editing.id);
      } else {
        const created = await createChapter({
          project_id: projectId,
          title: form.title,
          chapter_number: form.chapter_number,
          content: form.content || undefined,
        });
        toast.success('章节已创建');
        onSaved(created.id);
      }
      onClose();
    } catch {
      toast.error(editing ? '更新失败' : '创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <>
      {createPortal(
        <div className="hh-modal-mask">
          <div className="hh-modal max-w-[760px]" role="dialog" aria-modal="true">
            <div className="hh-modal-head">
              <div>
                <p className="hh-eyebrow">章节</p>
                <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">{editing ? '编辑章节' : '新建章节'}</h2>
              </div>
              <button onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="hh-modal-body space-y-5">
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="hh-label">章节标题</label>
                  <input
                    value={form.title}
                    onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))}
                    placeholder="输入章节标题"
                    className="hh-field"
                  />
                </div>
                {!editing && (
                  <div className="w-32">
                    <label className="hh-label">章节序号</label>
                    <input
                      type="number"
                      min={1}
                      value={form.chapter_number}
                      onChange={(e) => setForm((p) => ({ ...p, chapter_number: Number(e.target.value) }))}
                      className="hh-field"
                    />
                  </div>
                )}
              </div>
              <div>
                <div className="mb-1.5 flex items-center justify-between">
                  <label className="text-[13px] font-medium text-content">正文内容</label>
                  <div className="flex items-center gap-2">
                    {loadingContent && (
                      <span className="inline-flex items-center gap-1 text-xs text-content-tertiary">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        加载中…
                      </span>
                    )}
                    {form.content && <span className="text-xs text-content-tertiary tabular-nums">{form.content.length.toLocaleString()} 字</span>}
                    {editing && (
                      <button
                        type="button"
                        onClick={() => setShowImitationDialog(true)}
                        className="hh-chip text-brand"
                        title="从已挂载参考包生成草稿追加到正文"
                      >
                        <Sparkles className="h-3 w-3" />
                        一键仿写
                      </button>
                    )}
                  </div>
                </div>
                <textarea
                  value={form.content}
                  onChange={(e) => setForm((p) => ({ ...p, content: e.target.value }))}
                  placeholder="输入或粘贴章节正文内容…"
                  rows={16}
                  className="hh-textarea !resize-y leading-7"
                />
              </div>
            </div>
            <div className="hh-modal-foot">
              <button onClick={onClose} className="hh-btn-ghost">
                取消
              </button>
              <button onClick={() => void handleSubmit()} disabled={submitting || !form.title.trim()} className="hh-btn-primary">
                {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
                {submitting ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* 一键仿写弹板（V3 R5） */}
      {editing && (
        <ImitationDialog
          isOpen={showImitationDialog}
          projectId={projectId}
          targetChapterId={editing.id}
          targetChapterTitle={form.title || '未命名章节'}
          onClose={() => setShowImitationDialog(false)}
          onApply={(draft) => {
            setForm((prev) => {
              const sep = prev.content && !prev.content.endsWith('\n') ? '\n\n' : '';
              return { ...prev, content: prev.content + sep + draft };
            });
          }}
        />
      )}
    </>
  );
}
