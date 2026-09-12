/** 首次生成正文的配置弹窗：风格 / 目标字数 / MCP / 拆书参考包 + 本次会参考的内容预览 */
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Zap } from 'lucide-react';
import { writingStyleApi } from '@/services/api';
import { MCPSelector } from '@/components/MCPSelector';
import { ReferencePackSelector, DEFAULT_SELECTOR_VALUE, type ReferencePackSelectorValue } from '@/components/ReferencePackSelector';
import type { Chapter, ChapterCanGenerateResponse, ChapterGenerateRequest, PlotCardWithLinks, WritingStyle } from '@/types';

interface ChapterGenerateModalProps {
  open: boolean;
  projectId: string;
  chapter: Chapter;
  genCheck: ChapterCanGenerateResponse;
  relatedCards: PlotCardWithLinks[];
  loadingCards: boolean;
  onClose: () => void;
  onConfirm: (body: ChapterGenerateRequest) => void;
}

interface GenConfig {
  style_id: number | undefined;
  target_word_count: number;
  enable_mcp: boolean;
  selected_plugins: string[];
}

const DEFAULT_CONFIG: GenConfig = { style_id: undefined, target_word_count: 3000, enable_mcp: true, selected_plugins: [] };

export function ChapterGenerateModal({ open, projectId, chapter, genCheck, relatedCards, loadingCards, onClose, onConfirm }: ChapterGenerateModalProps) {
  const [genConfig, setGenConfig] = useState<GenConfig>(DEFAULT_CONFIG);
  // R8：拆书参考包选择器状态
  const [genRefPack, setGenRefPack] = useState<ReferencePackSelectorValue>(DEFAULT_SELECTOR_VALUE);
  const [styles, setStyles] = useState<WritingStyle[]>([]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    writingStyleApi.getProjectStyles(projectId)
      .then((res) => { if (!cancelled) setStyles(res.styles || []); })
      .catch(() => { /* ignore */ });
    return () => { cancelled = true; };
  }, [open, projectId]);

  const buildRequest = (): ChapterGenerateRequest => ({
    style_id: genConfig.style_id,
    target_word_count: genConfig.target_word_count,
    enable_mcp: genConfig.enable_mcp,
    selected_plugins: genConfig.enable_mcp && genConfig.selected_plugins.length > 0 ? genConfig.selected_plugins : undefined,
    // R8：仅 enabled 时透传拆书参考包参数
    ...(genRefPack.enabled ? {
      pack_ids: genRefPack.packIds.length > 0 ? genRefPack.packIds : undefined,
      dimensions: genRefPack.dimensions.length > 0 ? genRefPack.dimensions : undefined,
      strength: genRefPack.strength,
    } : {}),
  });

  if (!open) return null;

  const completedPreviousChapters = genCheck.previous_chapters.filter((c) => c.has_content);
  const previousChapterPreview = completedPreviousChapters.slice(-3);
  const relatedCardPreview = relatedCards.slice(0, 3);

  return createPortal(
    <div className="hh-modal-mask">
      <div className="hh-modal max-w-[680px]" role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div className="min-w-0">
            <p className="hh-eyebrow">AI 生成</p>
            <h2 className="mt-2 truncate text-xl font-semibold tracking-tight text-content">{chapter.title}</h2>
            <p className="mt-1 text-sm text-content-secondary">选择风格与目标字数，AI 会结合章纲、前文与设定生成正文。</p>
          </div>
          <button onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="hh-modal-body space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="hh-label">写作风格</label>
              <select
                value={genConfig.style_id ?? ''}
                onChange={(e) => setGenConfig((prev) => ({ ...prev, style_id: e.target.value ? Number(e.target.value) : undefined }))}
                className="hh-field"
              >
                <option value="">不使用风格（默认）</option>
                {styles.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="hh-label flex items-center justify-between">
                目标字数
                <span className="text-xs font-normal text-content-secondary tabular-nums">{genConfig.target_word_count.toLocaleString()} 字</span>
              </label>
              <input
                type="range"
                min={500}
                max={10000}
                step={500}
                value={genConfig.target_word_count}
                onChange={(e) => setGenConfig((prev) => ({ ...prev, target_word_count: Number(e.target.value) }))}
                className="mt-3 w-full accent-brand"
              />
              <div className="mt-1 flex justify-between text-xs text-content-tertiary tabular-nums">
                <span>500</span>
                <span>3000</span>
                <span>5000</span>
                <span>10000</span>
              </div>
            </div>
          </div>

          <MCPSelector
            value={{ enable: genConfig.enable_mcp, selected: genConfig.selected_plugins }}
            onChange={(val) => setGenConfig((prev) => ({ ...prev, enable_mcp: val.enable, selected_plugins: val.selected }))}
          />
          <ReferencePackSelector
            projectId={projectId}
            value={genRefPack}
            onChange={setGenRefPack}
            hint="让本章正文参考拆书的笔法/方法论/语料"
            disabledTitle="使用拆书参考包作为对标"
          />

          <div className="hh-subpanel space-y-3 p-4">
            <div>
              <p className="text-sm font-medium text-content">本次生成会参考的内容</p>
              <p className="mt-1 text-xs text-content-tertiary">后端会自动组合章纲、前文、关联剧情卡片、项目设定和可选 MCP 检索结果来生成正文。</p>
            </div>
            <div className="space-y-2 text-xs text-content-secondary">
              <div className="flex items-start justify-between gap-3">
                <span className="font-medium text-content">章纲与项目设定</span>
                <span>{chapter.chapter_outline_id ? '已关联章纲' : '未关联章纲'}</span>
              </div>
              <div className="flex items-start justify-between gap-3">
                <span className="font-medium text-content">前文承接</span>
                <span>{completedPreviousChapters.length > 0 ? `已纳入 ${completedPreviousChapters.length} 章前文` : '首章或暂无可参考前文'}</span>
              </div>
              {previousChapterPreview.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {previousChapterPreview.map((c) => (
                    <span key={c.id} className="border border-surface-border bg-white/80 px-2 py-0.5 text-[11px] text-content-secondary">
                      第 {c.chapter_number} 章：{c.title}
                    </span>
                  ))}
                </div>
              )}
              <div className="flex items-start justify-between gap-3">
                <span className="font-medium text-content">关联剧情卡片</span>
                <span>{loadingCards ? '加载中…' : relatedCards.length > 0 ? `${relatedCards.length} 张` : '暂无关联卡片'}</span>
              </div>
              {relatedCardPreview.length > 0 && (
                <div className="space-y-1.5">
                  {relatedCardPreview.map((card) => (
                    <div key={card.id} className="border border-surface-border bg-white/80 px-3 py-2">
                      <div className="text-[11px] font-medium text-content">{card.title}</div>
                      <div className="mt-0.5 line-clamp-2 text-[11px] text-content-tertiary">{card.content || '无卡片描述'}</div>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex items-start justify-between gap-3">
                <span className="font-medium text-content">MCP 外部参考</span>
                <span>
                  {genConfig.enable_mcp
                    ? genConfig.selected_plugins.length > 0
                      ? `已选 ${genConfig.selected_plugins.length} 个插件`
                      : '已启用，使用默认检索策略'
                    : '未启用'}
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="hh-modal-foot">
          <button onClick={onClose} className="hh-btn-ghost">
            取消
          </button>
          <button onClick={() => onConfirm(buildRequest())} className="hh-btn-primary">
            <Zap className="h-4 w-4" />
            开始生成
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
