/**
 * R8 通用：拆书参考包选择器
 *
 * 在各生成场景的对话框里嵌入此组件，让用户精细控制：
 * - 是否启用拆书参考（开关）
 * - 用哪几个参考包（多选；空 = 用项目所有挂载）
 * - 哪些维度（多选；空 = 用各 pack 的 default_dimensions）
 * - 强度（light / medium / deep）
 *
 * 父组件接住 onChange 后把字段透传到 generation API（pack_ids / dimensions / strength）。
 *
 * 设计文档：@/agent-docs/features/dissect_to_creation_pipeline.md §6.1
 */
import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Library, Loader2, Sparkles } from 'lucide-react';
import { toast } from 'sonner';

import { referencePackApi } from '@/services/api';
import type {
  ProjectReferencePackItem,
  ReferenceDimension,
  ReferencePackSummary,
  ReferenceStrength,
} from '@/types/reference_pack';

const DIMENSION_LABELS: Record<ReferenceDimension, string> = {
  synopsis: '全书骨架',
  bridges: '桥段库',
  style: '文风指纹',
  character_archive: '人物功能谱',
  methodology: '写法手册',
  structure: '结构统计',
  corpus: '拆书卡检索',
};

const STRENGTH_LABELS: Record<ReferenceStrength, string> = {
  light: '轻参考',
  medium: '中参考',
  deep: '深参考',
};

const STRENGTH_HINT: Record<ReferenceStrength, string> = {
  light: '每维度 ~600 字符上限；corpus top 1',
  medium: '每维度 ~1500 字符；corpus top 2',
  deep: '每维度 ~3500 字符；corpus top 3',
};

export interface ReferencePackSelectorValue {
  enabled: boolean;
  packIds: string[]; // 空数组 = 用项目所有已挂载的 ready/partial pack
  dimensions: ReferenceDimension[]; // 空数组 = 用各 pack 的 default_dimensions
  strength: ReferenceStrength;
}

// eslint-disable-next-line react-refresh/only-export-components
export const DEFAULT_SELECTOR_VALUE: ReferencePackSelectorValue = {
  enabled: false,
  packIds: [],
  dimensions: [],
  strength: 'medium',
};

// ============================================================
// P2-1 性能优化：TTL 缓存
// - 项目级缓存（projectId 为 key）：项目内反复打开多个生成对话框（30s 窗口内复用）
// - 用户级缓存（V3.2-B：项目未创建场景）：灵感模式入口选包、拆书页仿写需要拉全部 pack 列表
// 外部变更（挂载/卸载）调 invalidateAttachmentsCache 主动清除对应 key。
// ============================================================

const CACHE_TTL_MS = 30 * 1000;
const USER_PACKS_CACHE_KEY = '__user_packs__';  // 用户级缓存的虚拟 key
type _CacheEntry = { items: ProjectReferencePackItem[]; expireAt: number };
const _attachmentsCache = new Map<string, _CacheEntry>();

function _getCached(key: string): ProjectReferencePackItem[] | null {
  const entry = _attachmentsCache.get(key);
  if (!entry) return null;
  if (Date.now() >= entry.expireAt) {
    _attachmentsCache.delete(key);
    return null;
  }
  return entry.items;
}

function _setCached(key: string, items: ProjectReferencePackItem[]): void {
  _attachmentsCache.set(key, {
    items,
    expireAt: Date.now() + CACHE_TTL_MS,
  });
}

/** 把 ReferencePackSummary 包装成虚拟的 ProjectReferencePackItem（未挂载场景使用）。 */
function _wrapAsAttachment(pack: ReferencePackSummary): ProjectReferencePackItem {
  return {
    id: `virtual-${pack.id}`,  // 虚拟主键，仅用于 React key
    project_id: '',
    pack_id: pack.id,
    pack_summary: pack,
    default_dimensions: [],  // 未挂载时无默认维度，用 selector 最终 fallback
    default_strength: 'medium',
    attached_at: pack.created_at,
  };
}

/**
 * 供挂载/卸载/拆书变更后主动失效缓存。
 * - 传 projectId：仅失效该项目的项目级缓存
 * - 不传（或 'all'）：清除所有缓存（包含用户级）
 */
// eslint-disable-next-line react-refresh/only-export-components
export function invalidateAttachmentsCache(projectId?: string): void {
  if (projectId && projectId !== 'all') {
    _attachmentsCache.delete(projectId);
  } else {
    _attachmentsCache.clear();
  }
}

interface Props {
  /**
   * V3.2-B：projectId 为可选。
   * - 传：项目已存在，拉该项目挂载的 pack（原有行为）
   * - 不传：「项目创建前选包」场景（灵感模式入口、拆书仿写 CTA）——
   *           拉当前用户全部可用 pack，包装成虚拟挂载项
   */
  projectId?: string;
  value: ReferencePackSelectorValue;
  onChange: (v: ReferencePackSelectorValue) => void;
  /** 场景提示，如「为本次故事大纲生成提供对标书参考」 */
  hint?: string;
  /** 关闭时（enabled=false）显示的标题，默认「使用拆书参考包」 */
  disabledTitle?: string;
}

export function ReferencePackSelector({
  projectId,
  value,
  onChange,
  hint,
  disabledTitle = '使用拆书参考包',
}: Props) {
  const [attachments, setAttachments] = useState<ProjectReferencePackItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [errored, setErrored] = useState(false);
  // V4：默认隐藏维度+强度（V4 后端自动决策），用户可点开'高级设置'查看 V3 兼容选项
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);

  // 仅当用户首次启用时拉取（懒加载，避免每个对话框打开就请求）
  const shouldLoad = value.enabled && attachments.length === 0 && !errored;
  useEffect(() => {
    if (!shouldLoad) return;
    const cacheKey = projectId || USER_PACKS_CACHE_KEY;
    // P2-1：命中缓存时同步填充，不再请求 API
    const cached = _getCached(cacheKey);
    if (cached) {
      setAttachments(cached);
      return;
    }
    let cancelled = false;
    setLoading(true);

    // 传 projectId：拉项目挂载列表；不传：拉全用户 pack 并包装成虚拟挂载项
    const fetcher: Promise<ProjectReferencePackItem[]> = projectId
      ? referencePackApi.listAttachments(projectId).then((items) => items ?? [])
      : referencePackApi
          .list()
          .then((packs) => (packs ?? [])
            // 只要 ready/partial。generating/failed 不可用
            .filter((p) => p.status === 'ready' || p.status === 'partial')
            .map(_wrapAsAttachment)
          );

    fetcher
      .then((list) => {
        if (cancelled) return;
        _setCached(cacheKey, list); // 写入缓存
        setAttachments(list);
      })
      .catch(() => {
        if (cancelled) return;
        setErrored(true);
        toast.error(projectId ? '加载项目挂载的参考包失败' : '加载拆书参考包列表失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, shouldLoad]);

  // 仅展示 ready / partial 的包（generating/failed 不可用）
  const usablePacks = useMemo(
    () => attachments.filter(
      (a) => a.pack_summary.status === 'ready' || a.pack_summary.status === 'partial'
    ),
    [attachments],
  );

  // 该 packs 集合上"至少一个 pack 提供了"的维度并集（决定哪些维度可勾选）
  const availableDimensions = useMemo(() => {
    const set = new Set<ReferenceDimension>(['corpus']); // corpus 永远可用
    const targetPacks =
      value.packIds.length > 0
        ? usablePacks.filter((p) => value.packIds.includes(p.pack_id))
        : usablePacks;
    targetPacks.forEach((p) => {
      (p.pack_summary.generated_dimensions ?? []).forEach((d: string) => {
        set.add(d as ReferenceDimension);
      });
    });
    return set;
  }, [usablePacks, value.packIds]);

  // 关闭态：只显示开关行
  if (!value.enabled) {
    return (
      <div className="hh-subpanel flex items-center justify-between gap-3 px-4 py-3 text-sm">
        <div className="flex min-w-0 items-center gap-2">
          <Sparkles className="h-4 w-4 shrink-0 text-content-secondary" />
          <span className="font-medium text-content">{disabledTitle}</span>
          {hint && <span className="truncate text-[11px] text-content-tertiary">— {hint}</span>}
        </div>
        <button
          type="button"
          onClick={() => onChange({ ...value, enabled: true })}
          className="hh-chip shrink-0 text-brand"
        >
          启用
        </button>
      </div>
    );
  }

  // 启用但加载中
  if (loading) {
    return (
      <div className="hh-subpanel flex items-center gap-2 px-4 py-3 text-sm text-content-secondary">
        <Loader2 className="h-4 w-4 animate-spin text-brand" />
        加载项目挂载的参考包…
      </div>
    );
  }

  // 启用但项目未挂载任何 pack / 用户账号下未拆任何书
  if (usablePacks.length === 0) {
    return (
      <div className="space-y-2 border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-amber-700">
            <Library className="h-4 w-4" />
            <span>
              {projectId ? '项目未挂载任何就绪的参考包' : '你还没有任何拆书参考包'}
            </span>
          </div>
          <button
            type="button"
            onClick={() => onChange({ ...value, enabled: false })}
            className="hh-chip shrink-0"
          >
            关闭
          </button>
        </div>
        <p className="text-[11px] text-amber-700/80">
          {projectId ? (
            <>
              请先去
              <a
                href={`/project/${projectId}/reference-packs`}
                target="_blank"
                rel="noreferrer"
                className="mx-1 font-medium underline-offset-2 hover:underline"
              >
                项目参考包
              </a>
              页面挂载至少一个拆书参考包，再回来启用。
            </>
          ) : (
            <>
              请先到
              <a
                href="/book-dissect"
                target="_blank"
                rel="noreferrer"
                className="mx-1 font-medium underline-offset-2 hover:underline"
              >
                拆书页面
              </a>
              上传一本你想参考的书，拆书完成后再回来启用。
            </>
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3 border border-brand/25 bg-brand/5 px-4 py-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 text-content">
          <Sparkles className="h-4 w-4 shrink-0 text-brand" />
          <span className="font-medium">{disabledTitle}</span>
          {hint && <span className="truncate text-[11px] text-content-tertiary">— {hint}</span>}
        </div>
        <button
          type="button"
          onClick={() => onChange({ ...DEFAULT_SELECTOR_VALUE })}
          className="hh-chip shrink-0"
        >
          关闭
        </button>
      </div>

      {/* 参考包多选（空 = 全部挂载的） */}
      <div>
        <div className="mb-1.5 text-xs font-medium text-content-secondary">
          参考包
          <span className="ml-1 text-[11px] font-normal text-content-tertiary">
            （不勾选则使用全部挂载的 {usablePacks.length} 本）
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {usablePacks.map((p) => {
            const checked = value.packIds.includes(p.pack_id);
            return (
              <button
                key={p.pack_id}
                type="button"
                onClick={() => {
                  const next = checked
                    ? value.packIds.filter((id) => id !== p.pack_id)
                    : [...value.packIds, p.pack_id];
                  onChange({ ...value, packIds: next });
                }}
                className={`hh-chip ${checked ? 'hh-chip--active' : ''}`}
                title={p.pack_summary.status === 'partial' ? '部分维度未生成' : ''}
              >
                {p.pack_summary.source_book_title || p.pack_id.slice(0, 8)}
                {p.pack_summary.status === 'partial' && (
                  <span className="ml-1 text-[10px] opacity-80">·部分</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* V4 提示 + 高级设置折叠 */}
      <V4HintAndAdvancedToggle
        showAdvanced={showAdvanced}
        onToggle={() => setShowAdvanced((v) => !v)}
      />

      {showAdvanced && (
      <>
      {/* 维度多选（V3 兼容；V4 后端按场景+模型档位自动决策） */}
      <div>
        <div className="mb-1.5 text-xs font-medium text-content-secondary">
          参考维度
          <span className="ml-1 text-[11px] font-normal text-content-tertiary">
            （不勾选则使用挂载默认值；V4 装配会自适应覆盖）
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {(Object.keys(DIMENSION_LABELS) as ReferenceDimension[]).map((d) => {
            const enabledDim = availableDimensions.has(d);
            const checked = value.dimensions.includes(d);
            return (
              <button
                key={d}
                type="button"
                disabled={!enabledDim}
                onClick={() => {
                  const next = checked
                    ? value.dimensions.filter((x) => x !== d)
                    : [...value.dimensions, d];
                  onChange({ ...value, dimensions: next });
                }}
                className={`hh-chip ${checked ? 'hh-chip--active' : ''}`}
              >
                {DIMENSION_LABELS[d]}
              </button>
            );
          })}
        </div>
      </div>

      {/* 强度（V3 兼容；V4 后端按场景+模型档位自动决策） */}
      <div>
        <div className="mb-1.5 text-xs font-medium text-content-secondary">参考强度</div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex border border-surface-border bg-white/60 p-1">
            {(Object.keys(STRENGTH_LABELS) as ReferenceStrength[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onChange({ ...value, strength: s })}
                className={`px-3 py-1 text-xs font-medium transition-colors ${
                  value.strength === s
                    ? 'bg-brand text-white'
                    : 'text-content-secondary hover:text-content'
                }`}
              >
                {STRENGTH_LABELS[s]}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-content-tertiary">
            {STRENGTH_HINT[value.strength]}
          </span>
        </div>
      </div>
      </>
      )}
    </div>
  );
}

// V4 提示 + 高级设置折叠按钮（与 V4 设计 §6 配套）
function V4HintAndAdvancedToggle({
  showAdvanced,
  onToggle,
}: {
  showAdvanced: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="border border-surface-border/80 bg-white/70 px-3 py-2 text-[11px] text-content-secondary">
      <div className="flex items-center justify-between gap-2">
        <span>
          <strong className="font-semibold text-content">V4 自动装配</strong>：系统会按章节场景
          + 所选模型档位（S/M/L/XL）自动决定该用哪些维度、什么强度。无需手工选。
        </span>
        <button
          type="button"
          onClick={onToggle}
          className="hh-chip shrink-0 px-2 py-0.5 text-[11px] font-normal"
        >
          {showAdvanced ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          高级设置（V3 兼容）
        </button>
      </div>
    </div>
  );
}
