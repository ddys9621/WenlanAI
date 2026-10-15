/** 新建章节弹窗：只填标题与序号；正文、改标题、一键仿写都在稿纸里直接做 */
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, X } from 'lucide-react';
import { toast } from 'sonner';
import { useChapterSync } from '@/store/hooks';

interface ChapterEditModalProps {
  open: boolean;
  projectId: string;
  defaultChapterNumber: number;
  onClose: () => void;
  onCreated: (chapterId: string) => void;
}

export function ChapterEditModal({ open, projectId, defaultChapterNumber, onClose, onCreated }: ChapterEditModalProps) {
  const { createChapter } = useChapterSync();
  const [title, setTitle] = useState('');
  const [chapterNumber, setChapterNumber] = useState(1);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTitle('');
    setChapterNumber(defaultChapterNumber);
  }, [open, defaultChapterNumber]);

  const handleSubmit = async () => {
    if (!title.trim()) return;
    setSubmitting(true);
    try {
      const created = await createChapter({ project_id: projectId, title: title.trim(), chapter_number: chapterNumber });
      toast.success('章节已创建，直接在稿纸里写吧');
      onCreated(created.id);
      onClose();
    } catch {
      toast.error('创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return createPortal(
    <div className="hh-modal-mask">
      <div className="hh-modal max-w-[480px]" role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div>
            <p className="hh-eyebrow">章节</p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">新建章节</h2>
          </div>
          <button onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form className="hh-modal-body flex gap-4" onSubmit={(e) => { e.preventDefault(); void handleSubmit(); }}>
          <div className="flex-1">
            <label className="hh-label">章节标题</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="输入章节标题" className="hh-field" autoFocus />
          </div>
          <div className="w-28">
            <label className="hh-label">章节序号</label>
            <input
              type="number"
              min={1}
              value={chapterNumber}
              onChange={(e) => setChapterNumber(Number(e.target.value))}
              className="hh-field"
            />
          </div>
          <button type="submit" hidden />
        </form>
        <div className="hh-modal-foot">
          <button onClick={onClose} className="hh-btn-ghost">
            取消
          </button>
          <button onClick={() => void handleSubmit()} disabled={submitting || !title.trim()} className="hh-btn-primary">
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            {submitting ? '创建中…' : '创建并开写'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
