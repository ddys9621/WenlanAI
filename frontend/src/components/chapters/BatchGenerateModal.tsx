/** 批量生成范围弹窗：起止章节 + 遇严重一致性问题暂停开关 */
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Layers, X } from 'lucide-react';
import type { Chapter } from '@/types';

interface BatchGenerateModalProps {
  open: boolean;
  /** 已按 chapter_number 排好序 */
  chapters: Chapter[];
  onClose: () => void;
  onStart: (args: { from: number; to: number; pauseOnCritical: boolean }) => void;
}

export function BatchGenerateModal({ open, chapters, onClose, onStart }: BatchGenerateModalProps) {
  const first = chapters.length > 0 ? chapters[0].chapter_number : 1;
  const last = chapters.length > 0 ? chapters[chapters.length - 1].chapter_number : 5;
  const [from, setFrom] = useState(first);
  const [to, setTo] = useState(last);
  const [pauseOnCritical, setPauseOnCritical] = useState(true);

  useEffect(() => {
    if (!open) return;
    setFrom(first);
    setTo(last);
  }, [open, first, last]);

  if (!open) return null;

  return createPortal(
    <div className="hh-modal-mask">
      <div className="hh-modal max-w-[460px]" role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div>
            <p className="hh-eyebrow">批量</p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">批量生成</h2>
            <p className="mt-1 text-sm text-content-secondary">选择要批量生成的章节范围（按章节序号）。</p>
          </div>
          <button onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="hh-modal-body space-y-4">
          <div className="hh-subpanel px-4 py-3 text-xs leading-6 text-content-secondary">
            系统会按章节顺序自动串行生成，阅读区会切到当前章节显示流式内容与进度。已有内容的章节会自动跳过，避免覆盖现有正文。
          </div>
          <label className="flex cursor-pointer items-start gap-2 text-xs text-content-secondary">
            <input type="checkbox" className="mt-0.5" checked={pauseOnCritical} onChange={(e) => setPauseOnCritical(e.target.checked)} />
            <span className="leading-5">
              <span className="font-medium text-content">遇严重一致性问题时暂停</span>
              （每章分析完成后检查审计结果，发现 critical 问题先停下确认，避免错误设定影响后续章节）
            </span>
          </label>
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <label className="hh-label">起始章节</label>
              <input type="number" min={first} max={to} value={from} onChange={(e) => setFrom(Number(e.target.value))} className="hh-field" />
            </div>
            <span className="pb-3 text-content-tertiary">—</span>
            <div className="flex-1">
              <label className="hh-label">结束章节</label>
              <input type="number" min={from} max={last} value={to} onChange={(e) => setTo(Number(e.target.value))} className="hh-field" />
            </div>
          </div>
        </div>
        <div className="hh-modal-foot">
          <button onClick={onClose} className="hh-btn-ghost">
            取消
          </button>
          <button onClick={() => onStart({ from, to, pauseOnCritical })} className="hh-btn-primary">
            <Layers className="h-4 w-4" />
            开始生成
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
