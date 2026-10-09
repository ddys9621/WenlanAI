/** 批量生成范围弹窗：起止章节 + 服务端批量选项（严重问题暂停 / 质量闸门 / 流水线 / 缺章纲自动规划） */
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Layers, X } from 'lucide-react';
import type { Chapter } from '@/types';

export interface BatchStartArgs {
  from: number;
  to: number;
  pauseOnCritical: boolean;
  qualityGate: boolean;
  pipeline: boolean;
  autoExpand: boolean;
}

interface BatchGenerateModalProps {
  open: boolean;
  /** 已按 chapter_number 排好序 */
  chapters: Chapter[];
  onClose: () => void;
  onStart: (args: BatchStartArgs) => void;
}

/** 允许把结束章号填到现有章节之后：服务端会按滚动规划自动展开桥段补出章纲（最多往后 200 章） */
const MAX_LOOKAHEAD = 200;

export function BatchGenerateModal({ open, chapters, onClose, onStart }: BatchGenerateModalProps) {
  const first = chapters.length > 0 ? chapters[0].chapter_number : 1;
  const last = chapters.length > 0 ? chapters[chapters.length - 1].chapter_number : 5;
  const [from, setFrom] = useState(first);
  const [to, setTo] = useState(last);
  const [pauseOnCritical, setPauseOnCritical] = useState(true);
  const [qualityGate, setQualityGate] = useState(true);
  const [pipeline, setPipeline] = useState(false);
  const [autoExpand, setAutoExpand] = useState(true);

  useEffect(() => {
    if (!open) return;
    setFrom(first);
    setTo(last);
  }, [open, first, last]);

  if (!open) return null;

  const option = (checked: boolean, onChange: (v: boolean) => void, title: string, hint: string) => (
    <label className="flex cursor-pointer items-start gap-2 text-xs text-content-secondary">
      <input type="checkbox" className="mt-0.5" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="leading-5">
        <span className="font-medium text-content">{title}</span>
        {hint}
      </span>
    </label>
  );

  return createPortal(
    <div className="hh-modal-mask">
      <div className="hh-modal max-w-[500px]" role="dialog" aria-modal="true">
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
            批量任务在服务端运行：关掉页面也不会停，回来后会自动接上进度。每章依次「生成 → 质检 → 分析 → 一致性检查」，
            失败自动重试；已有正文的章节自动跳过，中断后用同样的范围重新开始即可接着写。
          </div>
          {option(pauseOnCritical, setPauseOnCritical, '遇严重一致性问题时暂停',
            '（每章分析完检查审计结果，发现 critical 问题先停下，避免错误设定影响后续章节）')}
          {option(qualityGate, setQualityGate, '质量闸门',
            '（AI 味分过高或字数严重不足时自动重写一次）')}
          {option(autoExpand, setAutoExpand, '缺章纲时自动规划',
            '（写到还没展开的桥段时，先自动填充 / 展开再写；配合「滚动规划」使用）')}
          {option(pipeline, setPipeline, '流水线加速',
            '（上一章分析和下一章生成同时进行，整体快约一半；严重问题会晚一章发现）')}
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <label className="hh-label">起始章节</label>
              <input type="number" min={1} max={to} value={from} onChange={(e) => setFrom(Number(e.target.value))} className="hh-field" />
            </div>
            <span className="pb-3 text-content-tertiary">—</span>
            <div className="flex-1">
              <label className="hh-label">结束章节</label>
              <input type="number" min={from} max={last + MAX_LOOKAHEAD} value={to} onChange={(e) => setTo(Number(e.target.value))} className="hh-field" />
            </div>
          </div>
        </div>
        <div className="hh-modal-foot">
          <button onClick={onClose} className="hh-btn-ghost">
            取消
          </button>
          <button onClick={() => onStart({ from, to, pauseOnCritical, qualityGate, pipeline, autoExpand })} className="hh-btn-primary">
            <Layers className="h-4 w-4" />
            开始生成
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
