/** 批量生成范围弹窗：起止章节 + 服务端批量选项（严重问题暂停 / 质量闸门 / 流水线 / 缺章纲自动规划） */
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Layers, X } from 'lucide-react';
import type { Chapter } from '@/types';
import { countBatchTargets, selectBatchChapters } from '@/utils/chapterBatch';

export interface BatchStartArgs {
  from: number;
  to: number;
  pauseOnCritical: boolean;
  qualityGate: boolean;
  pipeline: boolean;
  autoExpand: boolean;
  adherenceGate: boolean;
  requireConfirmedOutline: boolean;
}

interface BatchGenerateModalProps {
  open: boolean;
  /** 已按 chapter_number 排好序 */
  chapters: Chapter[];
  onClose: () => void;
  onStart: (args: BatchStartArgs) => void;
}

/** 允许把结束章号填到现有章节之后：服务端会按卷纲自动细化剧情单元、补出章纲（最多往后 200 章） */
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
  const [adherenceGate, setAdherenceGate] = useState(true);
  const [requireConfirmedOutline, setRequireConfirmedOutline] = useState(false);
  const { toGenerate, skipped } = selectBatchChapters(chapters, from, to);
  const targets = countBatchTargets(chapters, from, to);

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
            批量任务在服务端运行：关掉页面也不会停，回来后会自动接上进度。每章依次「生成候选稿 → 质检 / 章纲审校 → 自动采用 → 分析 → 一致性检查」，
            失败自动重试；已有正文的章节（包括手写的草稿）自动跳过，中断后用同样的范围重新开始即可接着写。
          </div>
          {option(pauseOnCritical, setPauseOnCritical, '遇严重一致性问题时暂停',
            '（每章分析完检查审计结果，发现 critical 问题先停下，避免错误设定影响后续章节）')}
          {option(qualityGate, setQualityGate, '质量闸门',
            '（AI 味分过高或字数严重不足时自动重写一次）')}
          {option(adherenceGate, setAdherenceGate, '章纲遵循度审校',
            '（漏写关键事件、没写到章末落点、抢跑下一章、新增未确认设定时重写一次；每章多一次模型调用）')}
          {option(requireConfirmedOutline, setRequireConfirmedOutline, '只写已确认的章纲',
            '（遇到 AI 草拟未确认、或上游卷纲 / 总纲改过的章纲就停下，先去确认）')}
          {option(autoExpand, setAutoExpand, '缺章纲时自动规划',
            '（写到还没有章纲的章节时，先按卷纲细化剧情单元、生成这一件事的章纲再写）')}
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
          <p className="text-xs text-content-secondary">
            将写 <span className="font-semibold text-content tabular-nums">{targets}</span> 章
            {skipped > 0 && <>，跳过 <span className="tabular-nums">{skipped}</span> 章已有正文的</>}
            {targets > toGenerate.length && <>（其中 <span className="tabular-nums">{targets - toGenerate.length}</span> 章需要先自动规划章纲）</>}
          </p>
        </div>
        <div className="hh-modal-foot">
          <button onClick={onClose} className="hh-btn-ghost">
            取消
          </button>
          <button
            onClick={() => onStart({ from, to, pauseOnCritical, qualityGate, pipeline, autoExpand, adherenceGate, requireConfirmedOutline })}
            disabled={targets === 0}
            className="hh-btn-primary"
          >
            <Layers className="h-4 w-4" />
            开始生成
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
