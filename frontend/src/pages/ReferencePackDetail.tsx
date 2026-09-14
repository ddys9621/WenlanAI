/**
 * 参考包详情页
 *
 * - pipeline_version >= 5：复用拆书 V5 五 tab 视图（全书骨架 / 桥段库 / 逐章拆书表 / 文风指纹 / 人物功能谱）
 * - 老包（V2-V4）：顶部横幅提示重新抽取 + 各维度 JSON 只读展示
 */
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, BookOpen, Loader2 } from 'lucide-react';

import { referencePackApi } from '@/services/api';
import type { ReferencePackDetail, ReferencePackStatus } from '@/types/reference_pack';
import { isV5Pack } from '@/types/reference_pack';
import { BookDissectV5View } from '@/components/book-dissect/BookDissectV5View';
import { LegacyPackNotice } from '@/components/book-dissect/LegacyPackNotice';

const STATUS_CLASS: Record<ReferencePackStatus, string> = {
  generating: 'bg-amber-500/15 text-amber-300',
  ready: 'bg-emerald-500/15 text-emerald-300',
  partial: 'bg-orange-500/15 text-orange-300',
  failed: 'bg-rose-500/15 text-rose-300',
};

const STATUS_LABEL: Record<ReferencePackStatus, string> = {
  generating: '生成中',
  ready: '就绪',
  partial: '部分就绪',
  failed: '失败',
};

export default function ReferencePackDetailPage() {
  const { packId } = useParams<{ packId: string }>();
  const [pack, setPack] = useState<ReferencePackDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!packId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const data = await referencePackApi.get(packId);
        if (!cancelled) setPack(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [packId]);

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-content-secondary">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        加载中...
      </div>
    );
  }
  if (error || !pack) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 p-6 text-rose-300">
          <AlertTriangle className="mb-2 h-5 w-5" />
          <p className="font-medium">加载参考包失败</p>
          <p className="mt-1 text-sm">{error || '未找到参考包'}</p>
          <Link to="/reference-packs" className="mt-3 inline-flex items-center gap-1 text-xs text-brand hover:underline">
            <ArrowLeft className="h-3 w-3" />
            返回参考库
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <Header pack={pack} />
      {isV5Pack(pack) ? <BookDissectV5View taskId={pack.task_id} pack={pack} /> : <LegacyPackNotice pack={pack} />}
    </div>
  );
}

function Header({ pack }: { pack: ReferencePackDetail }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
      <div>
        <Link to="/reference-packs" className="inline-flex items-center gap-1 text-xs text-content-secondary hover:text-brand">
          <ArrowLeft className="h-3 w-3" />
          返回参考库
        </Link>
        <h1 className="mt-1 flex flex-wrap items-center gap-2 text-2xl font-semibold text-content">
          <BookOpen className="h-6 w-6 text-brand" />
          {pack.source_book_title}
          <span className={`inline-flex items-center rounded-pill px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[pack.status]}`}>
            {STATUS_LABEL[pack.status]}
          </span>
          <span className="rounded-pill border border-surface-border px-2 py-0.5 text-xs font-normal text-content-tertiary">
            {isV5Pack(pack) ? 'V5 流水线' : `V${pack.pipeline_version ?? 2} 旧包`}
          </span>
        </h1>
        <p className="mt-1 text-xs text-content-tertiary">
          已挂载到 {pack.attached_project_count} 个项目 · 创建于 {new Date(pack.created_at).toLocaleString('zh-CN', { hour12: false })}
          {' · '}
          <Link to="/book-dissect" className="text-brand hover:underline">
            查看拆书任务
          </Link>
        </p>
        {pack.error_message && (
          <div className="mt-2 inline-flex items-center gap-1 rounded-md bg-orange-500/10 px-2 py-1 text-xs text-orange-300">
            <AlertTriangle className="h-3 w-3" />
            {pack.error_message}
          </div>
        )}
      </div>
    </div>
  );
}
