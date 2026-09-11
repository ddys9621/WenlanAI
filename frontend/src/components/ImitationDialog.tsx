/**
 * 一键仿写弹板（V3 R5）
 *
 * 流程：
 * 1. 打开后请求该项目"已挂载参考包"列表，自动按挂载默认值勾选
 * 2. 用户调整 [参考包 / 维度 / 强度 / 目标字数 / 意图]
 * 3. 点击"生成草稿" → SSE 流式接 imitate-chapter-stream
 * 4. 完成后，用户可点击"追加到正文"把累积草稿回写到当前章节编辑器
 *
 * 设计动机：见 @/agent-docs/features/book_dissect_v3_imitation_design.md §5
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, RefreshCw, Sparkles, StopCircle, X } from 'lucide-react';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { imitationApi, referencePackApi } from '@/services/api';
import { AIJobError, runAIJob, useAIJob, useAIJobsStore } from '@/store/aiJobsStore';
import { AIJobProcess } from '@/components/ai-job/AIJobProcess';
import type {
  ImitateChapterRequest,
  ImitationPackUsage,
  ProjectReferencePackItem,
  ReferenceDimension,
  ReferenceStrength,
} from '@/types/reference_pack';

interface ImitationDialogProps {
  isOpen: boolean;
  projectId: string;
  targetChapterId: string;
  targetChapterTitle: string;
  onClose: () => void;
  /** 用户点击「追加到正文」后回调（父组件负责把 draft 追加到当前编辑内容末尾） */
  onApply: (draft: string) => void;
}

const DIMENSION_LABELS: Record<ReferenceDimension, string> = {
  synopsis: '故事梗概', // V3.2 Story Bible 层
  // V3.2-P2 模式三维度
  entities: '实体分布',
  relations: '关系频谱',
  events: '事件节奏',
  methodology: '方法论',
  style: '文风',
  structure: '结构手法',
  archetypes: '角色塑造',
  worldbuilding: '世界观',
  // V4.1 维度
  bridges: '桥段范本',
  character_archive: '角色档案',
  corpus: '灵感语料',
};

const STRENGTH_LABELS: Record<ReferenceStrength, string> = {
  light: '轻参考',
  medium: '中参考',
  deep: '深参考',
};

export function ImitationDialog({
  isOpen,
  projectId,
  targetChapterId,
  targetChapterTitle,
  onClose,
  onApply,
}: ImitationDialogProps) {
  const [loadingAttachments, setLoadingAttachments] = useState(false);
  const [attachments, setAttachments] = useState<ProjectReferencePackItem[]>([]);

  // 表单
  const [selectedPackIds, setSelectedPackIds] = useState<string[]>([]);
  const [dimensions, setDimensions] = useState<ReferenceDimension[]>([]);
  const [strength, setStrength] = useState<ReferenceStrength>('medium');
  const [userIntent, setUserIntent] = useState('');
  const [targetWordCount, setTargetWordCount] = useState(2000);

  // 流式
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState('');
  const [draft, setDraft] = useState('');
  const [meta, setMeta] = useState<{
    used_packs: ImitationPackUsage[];
    used_dimensions: string[];
    strength: ReferenceStrength;
  } | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  // 生成走通用后台任务：关弹窗不中断（托盘可见）；这里记任务 id 以便停止与展示过程面板
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useAIJob(jobId);
  const cancelJob = useAIJobsStore((s) => s.cancel);
  const [showProcess, setShowProcess] = useState(false);
  const draftRef = useRef<HTMLTextAreaElement | null>(null);

  // 加载挂载列表 + 初始化默认值
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setLoadingAttachments(true);
    setErrorMsg(null);
    referencePackApi
      .listAttachments(projectId)
      .then((items) => {
        if (cancelled) return;
        setAttachments(items);
        // 默认全选已就绪的 pack
        const readyIds = items
          .filter((x) => x.pack_summary.status === 'ready' || x.pack_summary.status === 'partial')
          .map((x) => x.pack_id);
        setSelectedPackIds(readyIds);
        // 默认维度 = 选中 pack 的 default_dimensions 并集
        const dimUnion = new Set<ReferenceDimension>();
        items
          .filter((x) => readyIds.includes(x.pack_id))
          .forEach((x) => x.default_dimensions.forEach((d) => dimUnion.add(d)));
        setDimensions(Array.from(dimUnion));
        // 默认强度 = 最深
        const rank: ReferenceStrength[] = ['light', 'medium', 'deep'];
        const max = items
          .filter((x) => readyIds.includes(x.pack_id))
          .reduce<ReferenceStrength>((acc, x) => {
            return rank.indexOf(x.default_strength) > rank.indexOf(acc) ? x.default_strength : acc;
          }, 'light');
        setStrength(max);
      })
      .catch(() => {
        if (!cancelled) toast.error('加载已挂载参考包失败');
      })
      .finally(() => {
        if (!cancelled) setLoadingAttachments(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, projectId]);

  // 关闭时重置本地视图（任务本身归 store：仍在跑的仿写在托盘里可见，可从那里停止）
  useEffect(() => {
    if (!isOpen) {
      setGenerating(false);
      setProgress(0);
      setDraft('');
      setMeta(null);
      setErrorMsg(null);
      setJobId(null);
    }
  }, [isOpen]);

  const togglePack = (id: string) => {
    setSelectedPackIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const toggleDimension = (d: ReferenceDimension) => {
    setDimensions((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]));
  };

  // 已选 pack 真实生成的维度（用于灰显不可用项）
  const availableDimensions = useMemo(() => {
    const set = new Set<ReferenceDimension>(['corpus']); // corpus 永远可用
    attachments
      .filter((x) => selectedPackIds.includes(x.pack_id))
      .forEach((x) => x.pack_summary.generated_dimensions.forEach((d) => set.add(d as ReferenceDimension)));
    return set;
  }, [attachments, selectedPackIds]);

  const handleStart = async () => {
    if (!userIntent.trim()) {
      toast.error('请填写本次创作意图');
      return;
    }
    if (selectedPackIds.length === 0) {
      toast.error('请至少选择一个参考包');
      return;
    }

    const validDims = dimensions.filter((d) => availableDimensions.has(d));
    const finalDims = validDims.length > 0 ? validDims : ['corpus' as ReferenceDimension];

    const payload: ImitateChapterRequest = {
      user_intent: userIntent.trim(),
      target_chapter_id: targetChapterId,
      pack_ids: selectedPackIds,
      dimensions: finalDims,
      strength,
      target_word_count: targetWordCount,
    };

    setGenerating(true);
    setDraft('');
    setProgress(0);
    setProgressMsg('启动中…');
    setMeta(null);
    setErrorMsg(null);

    try {
      await runAIJob({
        kind: 'chapter_imitate',
        title: `一键仿写「${targetChapterTitle}」`,
        projectId,
        openModal: false,
        meta: { target_chapter_id: targetChapterId },
        onStarted: setJobId,
        connect: (options) => imitationApi.imitateChapterStream(projectId, payload, options),
        onEvent: (m) => {
          if (m.type === 'progress') {
            if (typeof m.progress === 'number') setProgress(m.progress);
            if (typeof m.message === 'string' && m.message) setProgressMsg(m.message);
          } else if (m.type === 'meta') {
            // 流内 meta 事件：后端已按"实际产出"收敛 used_dimensions，这里直接消费，
            // 不再依赖 onBlur 的 preview 请求（其结果可能过期）
            setMeta({
              used_packs: (m.used_packs as ImitationPackUsage[]) ?? [],
              used_dimensions: (m.used_dimensions as string[]) ?? [],
              strength: (m.strength as ReferenceStrength) ?? 'medium',
            });
          } else if (m.type === 'content' && typeof m.content === 'string') {
            const chunk = m.content;
            setDraft((prev) => {
              const next = prev + chunk;
              requestAnimationFrame(() => {
                if (draftRef.current) draftRef.current.scrollTop = draftRef.current.scrollHeight;
              });
              return next;
            });
          }
        },
      });
      setProgress(100);
    } catch (err) {
      if (err instanceof AIJobError && err.job.status === 'cancelled') {
        toast.info('已停止生成');
      } else {
        const message = (err as Error)?.message || '生成中断';
        setErrorMsg(message);
        toast.error(`仿写失败：${message}`);
      }
    } finally {
      setGenerating(false);
    }
  };

  // meta 获取有两条路：
  // 1) 生成时：SSE 流内 type=meta 事件（上方 onMeta，权威来源，含"实际产出"的维度）
  // 2) 生成前：意图输入框失焦时调一次 preview 做预估展示（下方，可能与最终选择有出入）
  const fetchMetaPreview = async () => {
    if (!userIntent.trim() || selectedPackIds.length === 0) return;
    try {
      const validDims = dimensions.filter((d) => availableDimensions.has(d));
      const finalDims = validDims.length > 0 ? validDims : ['corpus' as ReferenceDimension];
      const res = await imitationApi.preview(projectId, {
        user_intent: userIntent.trim() || '占位意图',
        target_chapter_id: targetChapterId,
        pack_ids: selectedPackIds,
        dimensions: finalDims,
        strength,
        target_word_count: targetWordCount,
      });
      setMeta({
        used_packs: res.used_packs,
        used_dimensions: res.used_dimensions,
        strength: res.strength,
      });
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      const detail = err?.response?.data?.detail || err?.message || '';
      if (detail) setErrorMsg(detail);
    }
  };

  const handleCancel = () => {
    if (jobId) void cancelJob(jobId);
  };

  const handleApply = () => {
    if (!draft.trim()) {
      toast.error('当前没有可应用的草稿');
      return;
    }
    onApply(draft);
    // 如实提示：此时只写入了编辑器 state，尚未持久化到数据库
    toast.success('已追加到编辑器，请记得点击「保存」写入正文');
    onClose();
  };

  if (!isOpen) return null;

  const readyAttachments = attachments.filter(
    (x) => x.pack_summary.status === 'ready' || x.pack_summary.status === 'partial',
  );

  return createPortal(
    <div className="hh-modal-mask z-[60]">
      <div className="hh-modal max-w-[760px]" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div className="min-w-0">
            <p className="hh-eyebrow">一键仿写</p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">为本章生成仿写草稿</h2>
            <p className="mt-1 text-sm leading-6 text-content-secondary">
              目标章节：{targetChapterTitle}。基于已挂载的拆书参考包生成草稿，确认后可追加到正文。
            </p>
          </div>
          <button onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="hh-modal-body space-y-5">
          {/* 已挂载参考包选择 */}
          <section>
            <label className="hh-label">
              参考包
              <span className="ml-1.5 text-xs font-normal text-content-tertiary">可多选</span>
            </label>
            {loadingAttachments ? (
              <div className="flex items-center gap-2 text-sm text-content-secondary">
                <Loader2 className="h-4 w-4 animate-spin text-brand" />
                加载已挂载参考包…
              </div>
            ) : readyAttachments.length === 0 ? (
              <div className="border border-amber-200 bg-amber-50/80 px-4 py-3 text-xs leading-5 text-amber-700">
                当前项目尚未挂载任何就绪的参考包。请先到「项目设置 · 参考库」挂载至少一个参考包后再使用一键仿写。
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {readyAttachments.map((item) => {
                  const checked = selectedPackIds.includes(item.pack_id);
                  return (
                    <label
                      key={item.pack_id}
                      className={cn(
                        'hh-subpanel flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors',
                        checked ? 'border-brand bg-brand/5' : 'hover:border-brand/40',
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4"
                        checked={checked}
                        onChange={() => togglePack(item.pack_id)}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-content">
                          {item.pack_summary.source_book_title}
                        </span>
                        <span className="mt-0.5 block text-[11px] text-content-tertiary">
                          生成维度：{item.pack_summary.generated_dimensions.length} 个 · 默认强度：
                          {STRENGTH_LABELS[item.default_strength] || item.default_strength}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </section>

          {/* 维度多选 */}
          <section>
            <label className="hh-label">
              参考维度
              <span className="ml-1.5 text-xs font-normal text-content-tertiary">可多选</span>
            </label>
            <div className="flex flex-wrap gap-1.5">
              {(Object.keys(DIMENSION_LABELS) as ReferenceDimension[]).map((d) => {
                const enabled = availableDimensions.has(d);
                const checked = dimensions.includes(d);
                return (
                  <button
                    key={d}
                    type="button"
                    disabled={!enabled}
                    onClick={() => toggleDimension(d)}
                    className={cn('hh-chip', enabled && checked && 'hh-chip--active')}
                  >
                    {DIMENSION_LABELS[d]}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-xs leading-5 text-content-tertiary">
              灰色项表示所选参考包未生成该维度，无法启用。「灵感语料」始终可用（来自原书章节摘要）。
            </p>
          </section>

          {/* 强度 */}
          <section>
            <label className="hh-label">参考强度</label>
            <div className="inline-flex border border-surface-border bg-white/60 p-1">
              {(Object.keys(STRENGTH_LABELS) as ReferenceStrength[]).map((s) => {
                const selected = strength === s;
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStrength(s)}
                    className={cn(
                      'px-3.5 py-1.5 text-xs font-medium transition-colors',
                      selected ? 'bg-brand text-white shadow-[0_8px_20px_-12px_rgba(0,122,255,0.6)]' : 'text-content-secondary hover:text-content',
                    )}
                  >
                    {STRENGTH_LABELS[s]}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-xs leading-5 text-content-tertiary">
              轻：仅文风 · 中：核心维度按需裁剪 · 深：全维度足量参考（成本最高）
            </p>
          </section>

          {/* 目标字数 */}
          <section>
            <div className="mb-1.5 flex items-center justify-between gap-3">
              <label className="text-[13px] font-medium text-content">目标字数</label>
              <span className="text-xs text-content-tertiary tabular-nums">{targetWordCount.toLocaleString()} 字</span>
            </div>
            <input
              type="range"
              min={500}
              max={6000}
              step={250}
              value={targetWordCount}
              onChange={(e) => setTargetWordCount(Number(e.target.value))}
              className="w-full accent-brand"
            />
          </section>

          {/* 意图 */}
          <section>
            <label className="hh-label">本次创作意图</label>
            <textarea
              value={userIntent}
              onChange={(e) => setUserIntent(e.target.value)}
              onBlur={fetchMetaPreview}
              placeholder="例如：主角第一次面对宿敌；要写出从压抑到爆发的情绪曲线，结尾留个钩子"
              rows={3}
              className="hh-textarea"
            />
          </section>

          {/* Meta 预览 */}
          {meta && !generating && (
            <div className="hh-subpanel px-4 py-3 text-xs leading-6 text-content-secondary">
              本次将启用 <strong className="font-semibold text-content">{meta.used_packs.length}</strong> 个参考包，
              共 <strong className="font-semibold text-content">{meta.used_dimensions.length}</strong> 个维度（
              {meta.used_dimensions.map((d) => DIMENSION_LABELS[d as ReferenceDimension] || d).join(' · ')}），
              强度 <strong className="font-semibold text-content">{STRENGTH_LABELS[meta.strength] || meta.strength}</strong>。
            </div>
          )}

          {errorMsg && (
            <div className="border border-red-200 bg-red-50/80 px-4 py-3 text-xs leading-5 text-red-600">
              {errorMsg}
            </div>
          )}

          {/* 草稿区 */}
          {(generating || draft) && (
            <section>
              <div className="mb-1.5 flex items-center justify-between gap-3">
                <label className="text-[13px] font-medium text-content">生成草稿</label>
                <span className="truncate text-xs text-content-tertiary tabular-nums">
                  {draft.length.toLocaleString()} 字 · {progress}%
                  {progressMsg ? ` · ${progressMsg}` : ''}
                </span>
              </div>
              {generating && (
                <div className="hh-progress mb-2">
                  <div className="hh-progress-bar" style={{ width: `${Math.min(progress, 100)}%` }} />
                </div>
              )}
              {job && (
                <div className="mb-2">
                  <button type="button" onClick={() => setShowProcess((v) => !v)} className="hh-btn-ghost hh-btn-sm">
                    {showProcess ? '收起过程' : '查看过程（参考包 / 模型进度）'}
                  </button>
                  {showProcess && (
                    <div className="mt-2">
                      <AIJobProcess job={job} />
                    </div>
                  )}
                </div>
              )}
              <textarea
                ref={draftRef}
                value={draft}
                readOnly
                rows={10}
                className="hh-textarea leading-7"
                placeholder={generating ? 'AI 正在创作中…' : '生成完成'}
              />
            </section>
          )}
        </div>

        <div className="hh-modal-foot">
          <button onClick={onClose} className="hh-btn-ghost">
            关闭
          </button>
          {generating ? (
            <button onClick={handleCancel} className="hh-btn-ghost text-red-500 hover:bg-red-50 hover:text-red-600">
              <StopCircle className="h-4 w-4" />
              取消生成
            </button>
          ) : draft ? (
            <>
              <button onClick={handleStart} disabled={selectedPackIds.length === 0} className="hh-btn-secondary">
                <RefreshCw className="h-4 w-4" />
                重新生成
              </button>
              <button onClick={handleApply} className="hh-btn-primary">
                追加到正文
              </button>
            </>
          ) : (
            <button
              onClick={handleStart}
              disabled={selectedPackIds.length === 0 || !userIntent.trim() || readyAttachments.length === 0}
              className="hh-btn-primary"
            >
              <Sparkles className="h-4 w-4" />
              生成草稿
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
