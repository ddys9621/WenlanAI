/**
 * V3 仿写参考库：列表页
 *
 * 功能：
 * - 列出当前用户所有参考包，含来源原书 / 状态 / 已挂载项目数 / 创建时间
 * - 点击进入详情页 (7 tab 浏览)
 * - 删除（弹窗确认）
 * - 状态徽章：generating / ready / partial / failed
 *
 * 参考包是**独立资料库**，不绑定到具体项目。
 * 跳过此页用户可以从拆书页 -> 直接进入详情；本页是统一资料库入口。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Clock,
  Library,
  Loader2,
  RefreshCw,
  Sparkles,
  Trash2,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';

import { referencePackApi } from '@/services/api';
import type {
  ReferencePackStatus,
  ReferencePackSummary,
} from '@/types/reference_pack';
import { isV5Pack } from '@/types/reference_pack';

const STATUS_CLASS: Record<ReferencePackStatus, string> = {
  generating: 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30',
  ready: 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30',
  partial: 'bg-orange-500/15 text-orange-300 ring-1 ring-orange-500/30',
  failed: 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30',
};

const STATUS_LABEL: Record<ReferencePackStatus, string> = {
  generating: '生成中',
  ready: '就绪',
  partial: '部分就绪',
  failed: '失败',
};

const DIMENSION_LABEL: Record<string, string> = {
  synopsis: '全书骨架',
  bridges: '桥段库',
  style: '文风指纹',
  character_archive: '人物功能谱',
  methodology: '写法手册',
  structure: '结构统计',
  // 老包（V2-V4）generated_dimensions 里可能残留的维度，仅列表展示用
  archetypes: '角色塑造（旧）',
  worldbuilding: '世界观（旧）',
  entities: '实体分布（旧）',
  relations: '关系频谱（旧）',
  events: '事件节奏（旧）',
};

function formatDate(iso?: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false });
  } catch {
    return iso;
  }
}

function StatusBadge({ status }: { status: ReferencePackStatus }) {
  const Icon =
    status === 'ready' ? CheckCircle2 :
    status === 'failed' ? XCircle :
    status === 'partial' ? AlertTriangle :
    Loader2;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[status]}`}
    >
      <Icon className={`h-3 w-3 ${status === 'generating' ? 'animate-spin' : ''}`} />
      {STATUS_LABEL[status]}
    </span>
  );
}

export default function ReferencePackLibrary() {
  const [packs, setPacks] = useState<ReferencePackSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchPacks = useCallback(async () => {
    try {
      setError(null);
      const data = await referencePackApi.list();
      setPacks(Array.isArray(data) ? data : []);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPacks();
  }, [fetchPacks]);

  const handleDelete = useCallback(
    async (pack: ReferencePackSummary) => {
      const confirmMsg =
        pack.attached_project_count > 0
          ? `参考包「${pack.source_book_title}」已挂载到 ${pack.attached_project_count} 个项目。\n删除后这些项目将无法再使用此参考包。\n\n确定删除吗？`
          : `确定删除参考包「${pack.source_book_title}」吗？`;
      if (!window.confirm(confirmMsg)) return;
      try {
        setDeletingId(pack.id);
        await referencePackApi.delete(pack.id);
        setPacks((prev) => prev.filter((p) => p.id !== pack.id));
        toast.success('已删除');
      } catch (err) {
        const msg = err instanceof Error ? err.message : '删除失败';
        toast.error(msg);
      } finally {
        setDeletingId(null);
      }
    },
    [],
  );

  const stats = useMemo(() => {
    const total = packs.length;
    const ready = packs.filter((p) => p.status === 'ready').length;
    const attached = packs.reduce((s, p) => s + (p.attached_project_count || 0), 0);
    return { total, ready, attached };
  }, [packs]);

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-6 py-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 rounded-pill bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
            <Library className="h-3.5 w-3.5" />
            仿写资料库
          </div>
          <h1 className="mt-2 text-2xl font-semibold text-content">参考包</h1>
          <p className="mt-1 text-sm text-content-secondary">
            从拆书任务沉淀的"如何写"指南，可挂载到多个项目，用于一键仿写章节。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={fetchPacks}
            className="inline-flex items-center gap-1.5 rounded-pill border border-surface-border bg-surface px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-hover"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            刷新
          </button>
          <Link
            to="/book-dissect"
            className="inline-flex items-center gap-1.5 rounded-pill bg-brand px-3.5 py-1.5 text-xs font-medium text-white hover:bg-brand-600"
          >
            <Sparkles className="h-3.5 w-3.5" />
            去拆书生成参考包
          </Link>
        </div>
      </header>

      {/* 顶部统计 */}
      <section className="grid grid-cols-3 gap-3">
        <StatCard label="参考包总数" value={stats.total} />
        <StatCard label="就绪可用" value={stats.ready} />
        <StatCard label="累计挂载次数" value={stats.attached} />
      </section>

      {loading ? (
        <div className="flex items-center justify-center rounded-2xl border border-surface-border bg-surface py-16 text-content-secondary">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载中...
        </div>
      ) : error ? (
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 px-4 py-6 text-sm text-rose-300">
          <AlertTriangle className="mb-1 inline h-4 w-4" />
          加载失败：{error}
        </div>
      ) : packs.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="space-y-3">
          {packs.map((pack) => (
            <li
              key={pack.id}
              className="rounded-2xl border border-surface-border bg-surface p-4 transition hover:border-brand/40 hover:bg-surface-hover"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <BookOpen className="h-4 w-4 text-brand shrink-0" />
                    <Link
                      to={`/reference-packs/${pack.id}`}
                      className="truncate text-base font-semibold text-content hover:text-brand"
                    >
                      {pack.source_book_title || '未命名拆书'}
                    </Link>
                    <StatusBadge status={pack.status} />
                    {!isV5Pack(pack) && (
                      <span
                        className="rounded-pill border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-700"
                        title="旧版流水线生成，只读；建议重新上传原书按 V5 抽取"
                      >
                        V{pack.pipeline_version ?? 2} 旧包
                      </span>
                    )}
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-content-tertiary">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {formatDate(pack.created_at)}
                    </span>
                    <span>
                      已挂载 {pack.attached_project_count} 个项目
                    </span>
                    <span>id: {pack.id.slice(0, 8)}…</span>
                  </div>

                  {/* 维度徽章 */}
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {pack.generated_dimensions.length === 0 ? (
                      <span className="text-xs text-content-tertiary">无成功维度</span>
                    ) : (
                      pack.generated_dimensions.map((dim) => (
                        <span
                          key={dim}
                          className="rounded-pill bg-brand/10 px-2 py-0.5 text-xs text-brand"
                        >
                          {DIMENSION_LABEL[dim] || dim}
                        </span>
                      ))
                    )}
                  </div>

                  {pack.error_message && (
                    <div className="mt-2 rounded-md bg-orange-500/10 px-2 py-1 text-xs text-orange-300">
                      <AlertTriangle className="mr-1 inline h-3 w-3" />
                      {pack.error_message}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Link
                    to={`/reference-packs/${pack.id}`}
                    className="inline-flex items-center gap-1 rounded-pill bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-600"
                  >
                    打开
                    <ChevronRight className="h-3 w-3" />
                  </Link>
                  <button
                    type="button"
                    onClick={() => handleDelete(pack)}
                    disabled={deletingId === pack.id}
                    className="inline-flex items-center gap-1 rounded-pill border border-surface-border bg-surface px-3 py-1.5 text-xs font-medium text-content-tertiary hover:border-rose-500/40 hover:text-rose-300 disabled:opacity-50"
                  >
                    {deletingId === pack.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3" />
                    )}
                    删除
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-surface-border bg-surface px-4 py-3">
      <div className="text-xs text-content-tertiary">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-content">{value}</div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-surface-border bg-surface px-6 py-16 text-center">
      <div className="mx-auto inline-flex h-12 w-12 items-center justify-center rounded-full bg-brand/10 text-brand">
        <Library className="h-6 w-6" />
      </div>
      <p className="mt-3 text-base font-medium text-content">还没有参考包</p>
      <p className="mt-1 text-sm text-content-secondary">
        到拆书页上传一本参考书，完成后会自动产出参考包。
      </p>
      <Link
        to="/book-dissect"
        className="mt-4 inline-flex items-center gap-1.5 rounded-pill bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-600"
      >
        <Sparkles className="h-3.5 w-3.5" />
        去拆书
      </Link>
    </div>
  );
}
