/**
 * V3 仿写：项目挂载的参考包管理页
 *
 * 路由：/project/:projectId/reference-packs
 *
 * 功能：
 * - 列出该项目已挂载的参考包
 * - 点击"挂载"打开侧抽屉，从我的参考库中选择
 * - 支持配置默认引用维度（multi-checkbox）+ 默认强度（light/medium/deep）
 * - 卸载（弹窗确认）
 *
 * 此页是 R5 一键仿写的前置：用户必须先在这里挂载至少 1 个参考包。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Library,
  Link2Off,
  Loader2,
  Plus,
  Settings2,
  X,
} from 'lucide-react';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { referencePackApi } from '@/services/api';
import { invalidateAttachmentsCache } from '@/components/ReferencePackSelector';
import type {
  ProjectReferencePackItem,
  ReferenceDimension,
  ReferencePackSummary,
  ReferenceStrength,
} from '@/types/reference_pack';

const DIMENSION_LABEL: Record<ReferenceDimension, string> = {
  synopsis: '全书骨架',
  bridges: '桥段库',
  style: '文风指纹',
  character_archive: '人物功能谱',
  methodology: '写法手册',
  structure: '结构统计',
  corpus: '拆书卡检索',
};

const STRENGTH_LABEL: Record<ReferenceStrength, string> = {
  light: '轻 · 仅文风',
  medium: '中 · 文风+方法论',
  deep: '深 · 全维度',
};

function inferDefaultDimensions(strength: ReferenceStrength): ReferenceDimension[] {
  if (strength === 'light') return ['style'];
  // 与后端 reference_pack._infer_default_dimensions 一致（V5 七维）
  if (strength === 'deep')
    return ['synopsis', 'bridges', 'methodology', 'style', 'structure', 'character_archive', 'corpus'];
  return ['synopsis', 'methodology', 'style', 'corpus'];
}

export default function ProjectReferencePacksPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [items, setItems] = useState<ProjectReferencePackItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<ProjectReferencePackItem | null>(null);

  const fetchItems = useCallback(async () => {
    if (!projectId) return;
    try {
      setError(null);
      const data = await referencePackApi.listAttachments(projectId);
      setItems(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  const handleDetach = useCallback(
    async (item: ProjectReferencePackItem) => {
      if (!projectId) return;
      if (!window.confirm(`确定从本项目卸载「${item.pack_summary.source_book_title}」吗？\n（不会删除参考包本身）`)) {
        return;
      }
      try {
        await referencePackApi.detach(projectId, item.pack_id);
        setItems((prev) => prev.filter((p) => p.id !== item.id));
        invalidateAttachmentsCache(projectId); // P2-1：失效选择器缓存
        toast.success('已卸载');
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '卸载失败');
      }
    },
    [projectId],
  );

  if (!projectId) {
    return null;
  }

  return (
    <div className="animate-fade-in space-y-6">
      <section className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <h1 className="text-[28px] font-semibold tracking-tight text-content md:text-[32px]">仿写参考包</h1>
          <p className="mt-2 max-w-[600px] text-sm leading-6 text-content-secondary">
            挂载到本项目的参考包，会作为一键仿写章节时的笔法、节奏、结构、角色与世界观来源。
            {items.length > 0 && ` 当前已挂载 ${items.length} 本。`}
          </p>
        </div>
        <button type="button" onClick={() => setDrawerOpen(true)} className="hh-btn-primary shrink-0">
          <Plus className="h-4 w-4" />
          挂载参考包
        </button>
      </section>

      {loading ? (
        <CenterLoader />
      ) : error ? (
        <ErrorBox msg={error} />
      ) : items.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="grid gap-4 lg:grid-cols-2">
          {items.map((it) => (
            <AttachmentRow
              key={it.id}
              item={it}
              onDetach={() => handleDetach(it)}
              onEdit={() => setEditing(it)}
            />
          ))}
        </ul>
      )}

      {drawerOpen && (
        <AttachDrawer
          projectId={projectId}
          existingPackIds={new Set(items.map((i) => i.pack_id))}
          onClose={() => setDrawerOpen(false)}
          onAttached={() => {
            setDrawerOpen(false);
            fetchItems();
          }}
        />
      )}

      {editing && (
        <EditDrawer
          item={editing}
          projectId={projectId}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            fetchItems();
          }}
        />
      )}
    </div>
  );
}

// ============================================================
// 行卡片
// ============================================================

function AttachmentRow({
  item,
  onDetach,
  onEdit,
}: {
  item: ProjectReferencePackItem;
  onDetach: () => void;
  onEdit: () => void;
}) {
  return (
    <li className="hh-panel flex flex-col p-5">
      <div className="flex items-start gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-brand/10 text-brand">
          <BookOpen className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/reference-packs/${item.pack_id}`}
              className="truncate text-[15px] font-semibold text-content hover:text-brand"
            >
              {item.pack_summary.source_book_title}
            </Link>
            <span className="bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
              {STRENGTH_LABEL[item.default_strength]}
            </span>
          </div>
          <p className="mt-1 text-xs text-content-tertiary">
            挂载于 {new Date(item.attached_at).toLocaleString('zh-CN', { hour12: false })}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <button type="button" onClick={onEdit} className="hh-icon-btn-plain h-8 w-8 hover:text-brand" title="配置默认维度与强度" aria-label="配置">
            <Settings2 className="h-4 w-4" />
          </button>
          <button type="button" onClick={onDetach} className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="从本项目卸载" aria-label="卸载">
            <Link2Off className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {item.default_dimensions.map((d) => (
          <span key={d} className="hh-tag">
            {DIMENSION_LABEL[d]}
          </span>
        ))}
      </div>
    </li>
  );
}

// ============================================================
// 挂载抽屉：从参考库选择
// ============================================================

function AttachDrawer({
  projectId,
  existingPackIds,
  onClose,
  onAttached,
}: {
  projectId: string;
  existingPackIds: Set<string>;
  onClose: () => void;
  onAttached: () => void;
}) {
  const [packs, setPacks] = useState<ReferencePackSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [strength, setStrength] = useState<ReferenceStrength>('medium');
  const [dimensions, setDimensions] = useState<ReferenceDimension[]>(inferDefaultDimensions('medium'));
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const data = await referencePackApi.list();
        setPacks(Array.isArray(data) ? data : []);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '加载参考库失败');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const availablePacks = useMemo(
    () =>
      packs.filter(
        (p) =>
          (p.status === 'ready' || p.status === 'partial') &&
          !existingPackIds.has(p.id),
      ),
    [packs, existingPackIds],
  );

  const handleSubmit = async () => {
    if (!selected) {
      toast.warning('请先选择参考包');
      return;
    }
    setSubmitting(true);
    try {
      await referencePackApi.attach(projectId, {
        pack_id: selected,
        default_dimensions: dimensions,
        default_strength: strength,
      });
      invalidateAttachmentsCache(projectId); // P2-1：失效选择器缓存
      toast.success('挂载成功');
      onAttached();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '挂载失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleStrengthChange = (s: ReferenceStrength) => {
    setStrength(s);
    setDimensions(inferDefaultDimensions(s));
  };

  return (
    <DrawerShell
      eyebrow="挂载"
      title="挂载参考包"
      description="从我的参考库中选择一本已拆解的书，并设置默认引用维度与强度。"
      onClose={onClose}
      footer={
        availablePacks.length > 0 && !loading ? (
          <>
            <button type="button" onClick={onClose} className="hh-btn-ghost">
              取消
            </button>
            <button type="button" disabled={!selected || submitting} onClick={handleSubmit} className="hh-btn-primary">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              挂载
            </button>
          </>
        ) : undefined
      }
    >
      {loading ? (
        <CenterLoader />
      ) : availablePacks.length === 0 ? (
        <div className="flex flex-col items-center py-8 text-center">
          <span className="flex h-12 w-12 items-center justify-center bg-brand/10 text-brand">
            <Library className="h-6 w-6" />
          </span>
          <p className="mt-4 text-sm font-medium text-content">没有可用参考包</p>
          <p className="mt-1 text-xs text-content-tertiary">已全部挂载，或参考包尚未就绪。</p>
          <Link to="/reference-packs" className="hh-btn-secondary hh-btn-sm mt-4">
            去参考库
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      ) : (
        <div className="space-y-5">
          <div>
            <label className="hh-label">从参考库选择</label>
            <ul className="hh-subpanel max-h-72 divide-y divide-surface-border/80 overflow-y-auto">
              {availablePacks.map((p) => {
                const active = selected === p.id;
                return (
                  <li
                    key={p.id}
                    onClick={() => setSelected(p.id)}
                    className={cn(
                      'cursor-pointer px-4 py-3 text-sm transition-colors',
                      active ? 'bg-brand/10 text-content' : 'text-content-secondary hover:bg-white/70',
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <BookOpen className={cn('h-4 w-4 shrink-0', active ? 'text-brand' : 'text-content-tertiary')} />
                      <span className="truncate font-medium">{p.source_book_title}</span>
                      {active && <CheckCircle2 className="ml-auto h-4 w-4 shrink-0 text-brand" />}
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {p.generated_dimensions.map((d) => (
                        <span key={d} className="hh-tag px-1.5 py-0.5 text-[10px]">
                          {DIMENSION_LABEL[d as ReferenceDimension] || d}
                        </span>
                      ))}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          <DimensionConfig
            strength={strength}
            dimensions={dimensions}
            onStrengthChange={handleStrengthChange}
            onDimensionsChange={setDimensions}
          />
        </div>
      )}
    </DrawerShell>
  );
}

// ============================================================
// 编辑抽屉：调整已挂载的默认配置
// ============================================================

function EditDrawer({
  item,
  projectId,
  onClose,
  onSaved,
}: {
  item: ProjectReferencePackItem;
  projectId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [strength, setStrength] = useState<ReferenceStrength>(item.default_strength);
  const [dimensions, setDimensions] = useState<ReferenceDimension[]>(item.default_dimensions);
  const [submitting, setSubmitting] = useState(false);

  const handleSave = async () => {
    setSubmitting(true);
    try {
      await referencePackApi.updateAttachment(projectId, item.pack_id, {
        default_strength: strength,
        default_dimensions: dimensions,
      });
      invalidateAttachmentsCache(projectId); // P2-1：失效选择器缓存
      toast.success('已保存');
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <DrawerShell
      eyebrow="配置"
      title={item.pack_summary.source_book_title}
      description="调整这本参考包在本项目中的默认引用维度与强度。"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className="hh-btn-ghost">
            取消
          </button>
          <button type="button" disabled={submitting} onClick={handleSave} className="hh-btn-primary">
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            保存
          </button>
        </>
      }
    >
      <DimensionConfig
        strength={strength}
        dimensions={dimensions}
        onStrengthChange={(s) => {
          setStrength(s);
          setDimensions(inferDefaultDimensions(s));
        }}
        onDimensionsChange={setDimensions}
      />
    </DrawerShell>
  );
}

// ============================================================
// 维度 + 强度配置（共用）
// ============================================================

function DimensionConfig({
  strength,
  dimensions,
  onStrengthChange,
  onDimensionsChange,
}: {
  strength: ReferenceStrength;
  dimensions: ReferenceDimension[];
  onStrengthChange: (s: ReferenceStrength) => void;
  onDimensionsChange: (d: ReferenceDimension[]) => void;
}) {
  const ALL_DIMS = Object.keys(DIMENSION_LABEL) as ReferenceDimension[];

  return (
    <div className="space-y-5">
      <div>
        <label className="hh-label">默认参考强度</label>
        <div className="inline-flex border border-surface-border bg-white/60 p-1">
          {(['light', 'medium', 'deep'] as ReferenceStrength[]).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onStrengthChange(s)}
              className={cn(
                'px-3.5 py-1.5 text-xs font-medium transition-colors',
                strength === s ? 'bg-brand text-white shadow-[0_8px_20px_-12px_rgba(0,122,255,0.6)]' : 'text-content-secondary hover:text-content',
              )}
            >
              {STRENGTH_LABEL[s]}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="hh-label">
          默认引用维度
          <span className="ml-1.5 text-xs font-normal text-content-tertiary">可手动调整</span>
        </label>
        <div className="flex flex-wrap gap-1.5">
          {ALL_DIMS.map((d) => {
            const checked = dimensions.includes(d);
            return (
              <button
                key={d}
                type="button"
                onClick={() => {
                  if (checked) {
                    onDimensionsChange(dimensions.filter((x) => x !== d));
                  } else {
                    onDimensionsChange([...dimensions, d]);
                  }
                }}
                className={cn('hh-chip', checked && 'hh-chip--active')}
              >
                {DIMENSION_LABEL[d]}
              </button>
            );
          })}
        </div>
        <p className="mt-2 text-[11px] text-content-tertiary">
          一键仿写时这些维度会自动注入 prompt；可在写章节时再次调整。
        </p>
      </div>
    </div>
  );
}

// ============================================================
// 共用小组件
// ============================================================

function DrawerShell({
  eyebrow,
  title,
  description,
  onClose,
  footer,
  children,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  onClose: () => void;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  return createPortal(
    <div className="hh-modal-mask">
      <div className="hh-modal max-w-[520px]" role="dialog" aria-modal="true">
        <div className="hh-modal-head">
          <div className="min-w-0">
            <p className="hh-eyebrow">{eyebrow}</p>
            <h3 className="mt-2 truncate text-xl font-semibold tracking-tight text-content">{title}</h3>
            {description && <p className="mt-1 text-sm text-content-secondary">{description}</p>}
          </div>
          <button type="button" onClick={onClose} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="hh-modal-body">{children}</div>
        {footer && <div className="hh-modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

function CenterLoader() {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-content-secondary">
      <Loader2 className="h-5 w-5 animate-spin text-brand" />
      加载中…
    </div>
  );
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="flex items-start gap-2 border border-red-200 bg-red-50/80 px-4 py-3 text-sm text-red-600">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      {msg}
    </div>
  );
}

function EmptyState() {
  return (
    <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
      <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
        <Library className="h-7 w-7" />
      </span>
      <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">还没有挂载参考包</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
        点击右上角「挂载参考包」，从参考库里选一本已拆解的书；挂载后写章节时可一键调用其笔法、结构、角色塑造与世界观。
      </p>
    </section>
  );
}
