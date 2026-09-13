/**
 * 桥段规划页（工程化桥段流水线）
 *
 * 路由：/project/:projectId/plot-bridges
 *
 * 三段流程：
 * 1. 生成桥段骨架：预览槽位表（主线节点 → 桥段数 / 章号，纯计算）→ 确认后建 N 个 draft 桥段
 * 2. AI 填充桥段内容：按主线节点分批 LLM 填 title/goal/爽点/四章卡（SSE，可续跑）
 * 3. 展开为章纲：按 bridge_number 顺序把 ready 桥段展开为第 4(n-1)+1…4n 章
 *
 * 其它：编辑单个桥段、删除桥段、重置骨架（未展开时）
 *
 * K2 设计：桥段四章结构（C1 代入+信息差 / C2 拉扯+开装 / C3 兑现爽点 / C4 善后+下一目标）
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  ConfigProvider,
  Form,
  Input,
  Modal,
  Popconfirm,
  Popover,
  Select,
  Tooltip,
} from 'antd';
import { ReloadOutlined, ThunderboltOutlined, ExpandAltOutlined } from '@ant-design/icons';
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Expand,
  Loader2,
  Pencil,
  RefreshCw,
  Rocket,
  Target,
  Trash2,
  Unlink,
  Zap,
} from 'lucide-react';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { ANTD_THEME } from '@/lib/antdTheme';
import { plotBridgesApi } from '@/services/plotBridgesApi';
import { settingsApi } from '@/services/api';
import { AIJobBanner } from '@/components/ai-job/AIJobBanner';
import { useAIJob, useAIJobsStore, useRunningAIJobs } from '@/store/aiJobsStore';
import type { AIJobLLM, AIJobState } from '@/types/ai_job';
import type { SSEMessage } from '@/utils/sseClient';
import {
  BRIDGE_STATUS_LABEL,
  BRIDGE_TEMPLATE_UI,
  LINE_MODE_LABEL,
  isPrimaryTask,
  resolveTemplateKey,
  type BridgeGenerationMeta,
  type BridgeSlotPreview,
  type BridgeStatus,
  type ExpandAllBridgesResponse,
  type ExpandBridgeResponse,
  type FillBridgesEvent,
  type FillBridgesResult,
  type FillPartialEvent,
  type FillThinkingEvent,
  type PartialBridge,
  type PlotBridge,
  type UpdateBridgeRequest,
} from '@/types/plot_bridge';

const BRIDGE_STATUS_CLASS: Record<BridgeStatus, string> = {
  draft: 'bg-surface-hover text-content-secondary',
  ready: 'bg-brand/10 text-brand',
  generating: 'bg-amber-50 text-amber-600',
  completed: 'bg-emerald-50 text-emerald-600',
};

type ModelOption = { value: string; label: string };

// 兜底候选：用户未配置 API、加载失败、或使用 Anthropic（无公开 /models 接口）时显示
const FALLBACK_MODEL_OPTIONS: ModelOption[] = [
  { value: 'deepseek-v3', label: 'DeepSeek V3（推荐，64K 大窗口）' },
  { value: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5（旗舰，200K）' },
  { value: 'qwen-max', label: '通义千问 Max（32K）' },
  { value: 'doubao-pro-32k', label: '豆包 Pro 32K' },
  { value: 'gpt-4o', label: 'GPT-4o（128K）' },
  { value: 'glm-4', label: 'GLM-4（64K）' },
];

/**
 * 拉取用户在「设置」中配置的 API 的真实可用模型列表。
 * - 默认模型 = Settings 里的 llm_model（如有）
 * - Anthropic 没公开 /models 接口 → 走 fallback + 补上用户的默认模型
 * - 拉取失败 → 静默降级到 fallback，不阻塞 UI
 */
function useAvailableModels() {
  const [options, setOptions] = useState<ModelOption[]>(FALLBACK_MODEL_OPTIONS);
  const [defaultModel, setDefaultModel] = useState<string>('');
  const [loading, setLoading] = useState(false);

  const loadModels = useCallback(async (showToast: boolean) => {
    try {
      setLoading(true);
      const settings = await settingsApi.getSettings();
      const userDefault = settings?.llm_model || '';
      if (userDefault) setDefaultModel(userDefault);

      const provider = settings?.api_provider || 'openai';

      // Anthropic 没公开 /models 接口
      if (provider === 'anthropic') {
        if (userDefault && !FALLBACK_MODEL_OPTIONS.some((o) => o.value === userDefault)) {
          setOptions([{ value: userDefault, label: `${userDefault}（设置中默认）` }, ...FALLBACK_MODEL_OPTIONS]);
        }
        return;
      }

      if (!settings?.api_key || !settings?.api_base_url) {
        // 未配置 API → 保留 fallback
        return;
      }

      const res = await settingsApi.getAvailableModels({
        api_key: settings.api_key,
        api_base_url: settings.api_base_url,
        provider,
      });
      const fetched = (res.models || []).map((m) => ({ value: m.value, label: m.label }));
      if (fetched.length) {
        // 若用户默认模型不在返回列表里，补到最前（避免下拉框看不到当前默认）
        const finalList =
          userDefault && !fetched.some((o) => o.value === userDefault)
            ? [{ value: userDefault, label: `${userDefault}（设置中默认）` }, ...fetched]
            : fetched;
        setOptions(finalList);
        if (showToast) toast.success(`已加载 ${fetched.length} 个可用模型`);
      } else if (showToast) {
        toast.warning('API 未返回模型列表，使用内置候选');
      }
    } catch (err) {
      console.warn('[PlotBridges] 加载用户模型失败，使用内置候选:', err);
      if (showToast) toast.warning('加载模型列表失败，使用内置候选');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadModels(false);
  }, [loadModels]);

  return { options, defaultModel, loading, refresh: () => void loadModels(true) };
}

/** 本页是唯一还在用 antd 的页面：ConfigProvider 跟着页面懒加载，不再放在 main.tsx 拖累首屏主包 */
export default function PlotBridgesPage() {
  return (
    <ConfigProvider theme={ANTD_THEME}>
      <PlotBridgesPageInner />
    </ConfigProvider>
  );
}

function PlotBridgesPageInner() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [bridges, setBridges] = useState<PlotBridge[]>([]);
  const [loading, setLoading] = useState(true);
  const [planning, setPlanning] = useState(false);
  const [preview, setPreview] = useState<BridgeSlotPreview | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [fillOpen, setFillOpen] = useState(false);
  // 填充任务：由通用 store 持有（订阅 / 重连 / 停止），页面只记 id 并订阅场景级事件
  const [fillJobId, setFillJobId] = useState<string | null>(null);
  const fillJob = useAIJob(fillJobId);
  const filling = fillJob?.status === 'running';
  // 打字机快照 / 正在生成的节点 / 子批耗时（ETA）
  const [partials, setPartials] = useState<Record<number, PartialBridge>>({});
  const [activeBeat, setActiveBeat] = useState<number | null>(null);
  const [batchTimes, setBatchTimes] = useState<Array<{ at: number; count: number }>>([]);
  const startJob = useAIJobsStore((s) => s.start);
  const subscribeJob = useAIJobsStore((s) => s.subscribe);
  const onJobSettled = useAIJobsStore((s) => s.onSettled);
  const allJobs = useAIJobsStore((s) => s.jobs);
  // 展开任务（单个 / 批量共用互斥键）：由 store 派生运行态
  const expanding = useRunningAIJobs(projectId, ['bridge_expand']).length > 0;
  const [editingBridge, setEditingBridge] = useState<PlotBridge | null>(null);
  const [expandingBridge, setExpandingBridge] = useState<PlotBridge | null>(null);

  // 从用户配置的 API 拉取真实可用模型列表（plan/expand 弹窗共用）
  const {
    options: modelOptions,
    defaultModel,
    loading: loadingModels,
    refresh: refreshModels,
  } = useAvailableModels();

  const fetchBridges = useCallback(async () => {
    if (!projectId) return;
    try {
      setLoading(true);
      const data = await plotBridgesApi.list(projectId);
      setBridges(Array.isArray(data) ? data : []);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '加载桥段列表失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchBridges();
  }, [fetchBridges]);

  /** 第 1 段·预览：纯计算槽位表，400 时后端 detail 会说明缺主线/缺节点 */
  const handleOpenPreview = useCallback(async () => {
    if (!projectId) return;
    try {
      const p = await plotBridgesApi.planPreview(projectId);
      setPreview(p);
      setPreviewOpen(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '无法计算桥段骨架');
    }
  }, [projectId]);

  /** 第 1 段·建骨架：N 个 draft 桥段，无 LLM */
  const handlePlan = useCallback(async () => {
    if (!projectId) return;
    setPlanning(true);
    try {
      const created = await plotBridgesApi.plan(projectId);
      toast.success(`已建骨架：${created.length} 个桥段（${created.length * 4} 章）`);
      setPreviewOpen(false);
      await fetchBridges();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '建骨架失败');
    } finally {
      setPlanning(false);
    }
  }, [projectId, fetchBridges]);

  const handleReset = useCallback(async () => {
    if (!projectId) return;
    if (!window.confirm('重置将删除全部桥段骨架（仅限尚未展开为章纲时）。是否继续？')) return;
    try {
      const res = await plotBridgesApi.reset(projectId);
      toast.success(`已删除 ${res.deleted} 个桥段`);
      await fetchBridges();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '重置失败');
    }
  }, [projectId, fetchBridges]);

  /** bridges 事件：后端刚写回的桥段（填充完成 / 展开完成）原位翻新卡片 */
  const applyBridgesEvent = useCallback((ev: FillBridgesEvent) => {
    setBridges((prev) => {
      const byId = new Map(prev.map((b) => [b.id, b]));
      for (const b of ev.bridges) byId.set(b.id, b);
      return Array.from(byId.values());
    });
  }, []);

  /** 填充任务的场景级事件（首连与重连共用）：thinking 高亮节点、partial 幽灵文本、bridges 翻新卡片 */
  const handleFillEvent = useCallback((m: SSEMessage) => {
    switch (m.type) {
      case 'thinking':
        setActiveBeat((m as unknown as FillThinkingEvent).beat_index);
        break;
      case 'partial': {
        const ev = m as unknown as FillPartialEvent;
        setActiveBeat(ev.beat_index);
        setPartials((prev) => {
          const next = { ...prev };
          for (const b of ev.bridges) next[b.bridge_number] = b;
          return next;
        });
        break;
      }
      case 'bridges': {
        const ev = m as unknown as FillBridgesEvent;
        applyBridgesEvent(ev);
        setPartials((prev) => {
          const next = { ...prev };
          for (const b of ev.bridges) delete next[b.bridge_number];
          return next;
        });
        setBatchTimes((prev) => [...prev, { at: Date.now(), count: ev.bridges.length }]);
        break;
      }
      default:
        break;
    }
  }, [applyBridgesEvent]);

  /** 展开任务的场景级事件：每个桥段展开完成即翻卡为 completed */
  const handleExpandEvent = useCallback((m: SSEMessage) => {
    if (m.type === 'bridges') applyBridgesEvent(m as unknown as FillBridgesEvent);
  }, [applyBridgesEvent]);

  /** 任务结束（完成 / 失败 / 停止）后的收尾：清掉幽灵卡片、提示结果、刷新列表 */
  const finishFill = useCallback(
    async (job: AIJobState) => {
      setPartials({});
      setActiveBeat(null);
      setBatchTimes([]);
      if (job.status === 'done') {
        const r = job.result as FillBridgesResult | null;
        if (r) toast.success(`已填充 ${r.filled} 个桥段${r.remaining_drafts ? `，剩余 ${r.remaining_drafts} 个待填` : ''}`);
      } else if (job.status === 'cancelled') {
        toast.info(job.error ?? '已停止填充');
      } else if (job.status === 'error') {
        toast.error(job.error ?? '填充失败', { duration: 8000 });
      }
      await fetchBridges();
    },
    [fetchBridges],
  );

  // 发现本项目正在跑的填充任务（刷新后由 store 从后端同步进来）→ 接管其 id
  useEffect(() => {
    if (fillJobId && allJobs[fillJobId]) return;
    const running = Object.values(allJobs).find(
      (j) => j.kind === 'bridge_fill' && j.projectId === projectId && j.status === 'running',
    );
    if (running) setFillJobId(running.id);
  }, [allJobs, fillJobId, projectId]);

  // 订阅该任务的场景级事件 + 收尾回调（只随 fillJobId 变化重建；同一函数引用重复订阅会被 Set 去重）
  useEffect(() => {
    if (!fillJobId || fillJobId.startsWith('pending-')) return;
    const unsubscribe = subscribeJob(fillJobId, handleFillEvent);
    const unsettle = onJobSettled(fillJobId, (job) => void finishFill(job));
    return () => {
      unsubscribe();
      unsettle();
    };
  }, [fillJobId, subscribeJob, onJobSettled, handleFillEvent, finishFill]);

  /** ETA：按已完成子批的平均每桥段耗时 × 剩余 draft 数 */
  const etaSeconds = useMemo(() => {
    if (!fillJob || batchTimes.length === 0) return null;
    const doneCount = batchTimes.reduce((s, b) => s + b.count, 0);
    const perBridge = (batchTimes[batchTimes.length - 1].at - fillJob.startedAt) / 1000 / Math.max(1, doneCount);
    const remaining = bridges.filter((b) => b.status === 'draft').length;
    return Math.round(perBridge * remaining);
  }, [fillJob, batchTimes, bridges]);

  /** 第 2 段·填充：启动后台任务；通用弹窗接管进度 / 过程，弹窗可最小化、页面可刷新，任务不中断 */
  const handleFill = useCallback(
    async (values: { model: string }) => {
      if (!projectId) return;
      setPartials({});
      setBatchTimes([]);
      setActiveBeat(null);
      setFillOpen(false);
      try {
        const jobId = await startJob({
          kind: 'bridge_fill',
          title: 'AI 填充桥段内容',
          projectId,
          connect: (options) => plotBridgesApi.fillStream(projectId, { model: values.model || undefined }, options),
        });
        setFillJobId(jobId);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '填充失败', { duration: 8000 });
      }
    },
    [projectId, startJob],
  );

  const handleDelete = useCallback(
    async (bridgeId: string) => {
      try {
        await plotBridgesApi.delete(bridgeId);
        toast.success('已删除');
        setBridges((prev) => prev.filter((b) => b.id !== bridgeId));
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '删除失败');
      }
    },
    [],
  );

  // T2.1：桥段状态统计 + 批量展开
  const stats = useMemo(() => {
    const draft = bridges.filter((b) => b.status === 'draft').length;
    const ready = bridges.filter((b) => b.status === 'ready').length;
    const completed = bridges.filter((b) => b.status === 'completed').length;
    return {
      total: bridges.length,
      draft,
      ready,
      completed,
      allCompleted: bridges.length > 0 && draft === 0 && ready === 0 && completed === bridges.length,
    };
  }, [bridges]);

  /** 第 3 段·批量展开：后台任务，每个桥段展开完成即翻卡；通用弹窗显示每桥段 stage，可最小化 / 停止 */
  const handleExpandAll = useCallback(async () => {
    if (!projectId || stats.ready === 0) return;
    if (
      !window.confirm(
        `将展开 ${stats.ready} 个 ready 状态的桥段为 ${stats.ready * 4} 个章纲。\n` +
          `按顺序逐个展开，首个失败即停止（后续桥段依赖前序已展开）。是否继续？`,
      )
    ) {
      return;
    }
    try {
      await startJob({
        kind: 'bridge_expand',
        title: '展开全部就绪桥段为章纲',
        projectId,
        connect: (options) => plotBridgesApi.expandAllStream(projectId, { model: defaultModel || undefined }, options),
        onEvent: handleExpandEvent,
        onSettled: (job) => {
          if (job.status === 'done') {
            const res = job.result as ExpandAllBridgesResponse | null;
            if (res && res.failed.length === 0) {
              toast.success(`成功展开 ${res.succeeded.length} 个桥段，共创建 ${res.created_chapter_count} 个章纲`);
            } else if (res) {
              toast.warning(`部分完成：${res.succeeded.length}/${res.total} 成功，${res.failed.length} 失败：${res.failed[0]?.error ?? ''}`);
            }
          }
          void fetchBridges();
        },
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '批量展开失败');
    }
  }, [projectId, stats.ready, defaultModel, fetchBridges, startJob, handleExpandEvent]);

  /** 第 3 段·单个展开：后台任务（弹窗选完模型即关闭，进度在通用任务弹窗里） */
  const handleExpandOne = useCallback(
    async (bridge: PlotBridge, model?: string) => {
      if (!projectId) return;
      setExpandingBridge(null);
      try {
        await startJob({
          kind: 'bridge_expand',
          title: `展开桥段 ${bridge.bridge_number}《${bridge.title}》`,
          projectId,
          connect: (options) => plotBridgesApi.expandStream(bridge.id, { model }, options),
          onEvent: handleExpandEvent,
          onSettled: (job) => {
            if (job.status === 'done') {
              const res = job.result as ExpandBridgeResponse | null;
              if (res) toast.success(`已展开 ${res.chapter_count} 个章纲（第 ${bridge.chapter_start}-${bridge.chapter_end} 章）`);
            }
            void fetchBridges();
          },
        });
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '展开失败');
      }
    },
    [projectId, startJob, handleExpandEvent, fetchBridges],
  );

  const handleGoToChapterOutlines = useCallback(() => {
    if (!projectId) return;
    navigate(`/project/${projectId}/outline`);
  }, [navigate, projectId]);

  if (!projectId) return null;

  return (
    <div className="animate-fade-in space-y-6">
      <section className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <h1 className="text-[28px] font-semibold tracking-tight text-content md:text-[32px]">桥段规划</h1>
          <p className="mt-2 max-w-[640px] text-sm leading-6 text-content-secondary">
            每个桥段 4 章：
            <span className="font-medium text-content">C1 代入 → C2 拉扯 → C3 兑现 → C4 善后</span>
            。先由系统按主线节点权重建骨架（桥段数与章号），再让 AI 逐节点填内容，最后按序展开为章纲。
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={fetchBridges} className="hh-icon-btn h-11 w-11" title="刷新" aria-label="刷新">
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          </button>
          {bridges.length > 0 && stats.completed === 0 && (
            <button onClick={handleReset} className="hh-btn-ghost text-red-500 hover:bg-red-50 hover:text-red-600">
              <Trash2 className="h-4 w-4" />
              重置骨架
            </button>
          )}
          {bridges.length === 0 ? (
            <button onClick={handleOpenPreview} className="hh-btn-primary">
              <Rocket className="h-4 w-4" />
              生成桥段骨架
            </button>
          ) : stats.draft > 0 ? (
            <button onClick={() => setFillOpen(true)} disabled={filling} className="hh-btn-primary">
              {filling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
              {filling ? '填充中…' : `AI 填充桥段内容（${stats.draft} 待填）`}
            </button>
          ) : stats.ready > 0 ? (
            <button onClick={handleExpandAll} disabled={expanding} className="hh-btn-primary">
              {expanding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Expand className="h-4 w-4" />}
              {expanding ? '正在展开…' : `展开为章纲（${stats.ready} 个桥段）`}
            </button>
          ) : null}
        </div>
      </section>

      {/* 后台任务横幅：通用弹窗最小化后在这里看进度 / 重新打开 / 停止 */}
      <AIJobBanner projectId={projectId} />

      {/* 状态总览 + 完成跳转提示 */}
      {stats.total > 0 && (
        <section className="hh-panel grid grid-cols-2 divide-surface-border/80 md:grid-cols-5 md:divide-x">
          <StatItem label="桥段总数" value={stats.total} />
          <StatItem label="待填充" value={stats.draft} />
          <StatItem label="就绪待展开" value={stats.ready} />
          <StatItem label="已展开" value={stats.completed} />
          <StatItem label="总章数" value={stats.total * 4} />
        </section>
      )}

      {stats.allCompleted && (
        <section className="flex flex-col gap-3 border border-emerald-200 bg-emerald-50/80 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-center gap-2 text-sm text-emerald-700">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            全部桥段已展开为章纲，可前往章纲页继续创作。
          </p>
          <button onClick={handleGoToChapterOutlines} className="hh-btn-primary hh-btn-sm shrink-0">
            进入章纲页
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </section>
      )}

      {/* List */}
      {loading ? (
        <div className="hh-panel flex items-center justify-center gap-2 py-20 text-sm text-content-secondary">
          <Loader2 className="h-5 w-5 animate-spin text-brand" />
          加载中…
        </div>
      ) : bridges.length === 0 ? (
        <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <Rocket className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">还没有桥段骨架</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            点击右上角「生成桥段骨架」：系统按主线节点权重算出桥段数与章号，随后再用 AI 填充每个桥段的内容。
            需要先在「故事大纲 → 剧情线」里有且仅有一条主线（向导会自动生成）。
          </p>
        </section>
      ) : (
        <BridgeListByBeat
          bridges={bridges}
          partials={partials}
          activeBeat={filling ? activeBeat : null}
          llm={filling ? fillJob?.llm ?? null : null}
          eta={filling ? etaSeconds : null}
          onEdit={(b) => setEditingBridge(b)}
          onExpand={(b) => setExpandingBridge(b)}
          onDelete={(id) => handleDelete(id)}
        />
      )}

      {/* 第 1 段：骨架预览（纯计算，不写库）→ 确认建骨架 */}
      <Modal
        title="桥段骨架预览"
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        destroyOnClose
        width={560}
      >
        {preview && (
          <div className="space-y-4">
            <p className="text-sm leading-6 text-content-secondary">
              主线共 {Object.keys(preview.beat_quotas).length} 个节点 → {preview.total_bridges} 个桥段 →{' '}
              {preview.total_chapters} 章。桥段数与章号由系统按节点权重确定，AI 只负责填内容。
            </p>
            <ul className="hh-subpanel divide-y divide-surface-border/80 text-sm">
              {Object.entries(preview.beat_quotas).map(([beat, quota]) => {
                const slots = preview.slots.filter((s) => String(s.beat_index) === beat);
                const first = slots[0];
                const last = slots[slots.length - 1];
                return (
                  <li key={beat} className="flex items-center justify-between gap-3 px-4 py-2">
                    <span className="min-w-0 truncate text-content">
                      [节点 {beat}] {first?.beat_title}
                    </span>
                    <span className="shrink-0 text-content-tertiary tabular-nums">
                      {quota} 个桥段 · 第 {first?.chapter_start}-{last?.chapter_end} 章
                      {first && first.secondary.length > 0 ? ` · 副线任务 ${first.secondary.length}` : ''}
                    </span>
                  </li>
                );
              })}
            </ul>
            {preview.line_budgets.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-content-secondary">
                  支线预算：主推 = 作为该桥段主 B 线推进；保温 = 一句话带过。每个桥段只主推一条支线。
                </p>
                <ul className="hh-subpanel divide-y divide-surface-border/80 text-sm">
                  {preview.line_budgets.map((lb) => {
                    const short = lb.anchored && lb.primary_bridges < lb.primary_quota;
                    return (
                      <li key={lb.plot_line_id} className="flex items-center justify-between gap-3 px-4 py-2">
                        <span className="min-w-0 truncate text-content">
                          《{lb.line_title}》
                          <span className="ml-1 text-xs text-content-tertiary">
                            {lb.anchored && lb.mode
                              ? `${LINE_MODE_LABEL[lb.mode]} · 主线节点 ${lb.anchor_start_beat}-${lb.anchor_end_beat}`
                              : '未锚定 · 按进度均匀挂载'}
                          </span>
                        </span>
                        <span className={cn('shrink-0 tabular-nums', short ? 'text-amber-600' : 'text-content-tertiary')}>
                          {lb.anchored ? `预算 ${lb.estimated_chapters ?? '?'} 章 ≈ ${lb.primary_quota} 桥段 · ` : ''}
                          主推 {lb.primary_bridges} · 保温 {lb.mention_bridges}
                          {short ? ' · 主推不足' : ''}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button onClick={() => setPreviewOpen(false)}>取消</Button>
              <Button type="primary" loading={planning} onClick={handlePlan} icon={<ThunderboltOutlined />}>
                确认建骨架
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* 第 2 段：AI 填充桥段内容（后台任务；进度与过程在通用 AI 任务弹窗里） */}
      <Modal
        title="AI 填充桥段内容"
        open={fillOpen}
        onCancel={() => setFillOpen(false)}
        footer={null}
        destroyOnClose
        width={480}
      >
        <Form
          // 用 defaultModel 作为 key：异步加载完成后强制重渲染，让 initialValues 生效
          key={`fill-form-${defaultModel || 'pending'}`}
          layout="vertical"
          initialValues={{ model: defaultModel || modelOptions[0]?.value || 'deepseek-v3' }}
          onFinish={handleFill}
        >
          <Form.Item
            label={
              <div className="flex items-center gap-2">
                <span>使用模型</span>
                <Tooltip title="重新从「设置」中配置的 API 拉取模型列表">
                  <Button
                    type="text"
                    size="small"
                    icon={<ReloadOutlined spin={loadingModels} />}
                    onClick={refreshModels}
                  />
                </Tooltip>
              </div>
            }
            name="model"
            rules={[{ required: true }]}
            extra="列表来自「设置」中配置的 API；下拉所选模型会同时用于推理 + 决定 prompt 档位（XL/L/M/S）"
          >
            <Select
              options={modelOptions}
              loading={loadingModels}
              showSearch
              optionFilterProp="label"
              placeholder={loadingModels ? '加载模型中...' : '选择模型'}
            />
          </Form.Item>
          <p className="mb-4 text-xs leading-5 text-content-tertiary">
            按主线节点逐批填充（每批 ≤4 个桥段一次 LLM 调用），任务在后台运行：关掉弹窗、刷新页面都不会中断；
            停止或失败后再次点击会从剩余的 {stats.draft} 个待填桥段续跑。
          </p>
          <Form.Item className="!mb-0 text-right">
            <Button onClick={() => setFillOpen(false)} className="mr-2">
              取消
            </Button>
            <Button type="primary" htmlType="submit" icon={<ThunderboltOutlined />}>
              {`开始填充（${stats.draft} 个）`}
            </Button>
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑桥段弹窗 */}
      <EditBridgeModal
        bridge={editingBridge}
        onClose={() => setEditingBridge(null)}
        onSaved={(updated) => {
          setBridges((prev) =>
            prev.map((b) => (b.id === updated.id ? updated : b)),
          );
          setEditingBridge(null);
        }}
      />

      {/* 展开为 4 章弹窗 */}
      <ExpandBridgeModal
        bridge={expandingBridge}
        modelOptions={modelOptions}
        defaultModel={defaultModel}
        loadingModels={loadingModels}
        refreshModels={refreshModels}
        onClose={() => setExpandingBridge(null)}
        onStart={handleExpandOne}
      />
    </div>
  );
}

// ============================================================
// 按节点分组列表（V4.1 方案 C）
// ============================================================

interface BridgeListByBeatProps {
  bridges: PlotBridge[];
  /** 打字机快照：bridge_number → 已写出的字段（只对 draft 卡片生效） */
  partials: Record<number, PartialBridge>;
  /** 正在生成的主线节点（分组标题显示旋转指示） */
  activeBeat: number | null;
  /** 当前任务的模型思考 / 输出计数（来自通用任务状态） */
  llm: AIJobLLM | null;
  /** 预计剩余秒数（按已完成子批估算） */
  eta: number | null;
  onEdit: (b: PlotBridge) => void;
  onExpand: (b: PlotBridge) => void;
  onDelete: (id: string) => void;
}

/**
 * 按 (plot_line_id, beat_index) 把桥段分组渲染。
 *
 * 分组规则：
 * - 同 plot_line_id + 同 beat_index → 同一个节点组（按 beat_coverage_start 排序）
 * - plot_line_id / beat_index 缺失 → 落入「未绑节点」分组（free 模式 / 老数据）
 * - 节点组按 (plot_line_id, beat_index) 自然顺序排列，未绑节点组排最后
 *
 * 节点 title / 剧情线 title 用 plot_line_id 短哈希做 fallback —— 完整剧情线数据
 * 可在后续版本通过 plotLinesApi 拉来填充更友好的 label。
 */
function BridgeListByBeat({
  bridges,
  partials,
  activeBeat,
  llm,
  eta,
  onEdit,
  onExpand,
  onDelete,
}: BridgeListByBeatProps) {
  // 分组
  const groups = useMemo(() => {
    const map = new Map<string, PlotBridge[]>();
    const KEY_UNBOUND = '__unbound__';
    for (const b of bridges) {
      const key =
        b.plot_line_id && b.beat_index != null
          ? `${b.plot_line_id}::${b.beat_index}`
          : KEY_UNBOUND;
      const arr = map.get(key) ?? [];
      arr.push(b);
      map.set(key, arr);
    }
    // 节点组内按 coverage_start asc → bridge_number asc 排序
    for (const arr of map.values()) {
      arr.sort((a, b) => {
        const ca = a.beat_coverage_start ?? 0;
        const cb = b.beat_coverage_start ?? 0;
        if (ca !== cb) return ca - cb;
        return (a.bridge_number ?? 0) - (b.bridge_number ?? 0);
      });
    }
    return map;
  }, [bridges]);

  // 渲染顺序：先所有绑节点的组（按 plot_line_id + beat_index），再未绑组
  const orderedKeys = useMemo(() => {
    const bound: string[] = [];
    let unbound: string | null = null;
    for (const key of groups.keys()) {
      if (key === '__unbound__') unbound = key;
      else bound.push(key);
    }
    bound.sort((a, b) => {
      const [la, ia] = a.split('::');
      const [lb, ib] = b.split('::');
      if (la !== lb) return la.localeCompare(lb);
      return Number(ia) - Number(ib);
    });
    return unbound ? [...bound, unbound] : bound;
  }, [groups]);

  return (
    <div className="space-y-6">
      {orderedKeys.map((key) => {
        const groupBridges = groups.get(key) ?? [];
        const isUnbound = key === '__unbound__';
        const first = groupBridges[0];
        const groupLabel = isUnbound
          ? '未绑节点（旧数据，建议重置骨架后重新规划）'
          : `主线节点 ${first?.beat_index ?? '?'} · 第 ${first?.chapter_start ?? '?'}-${groupBridges[groupBridges.length - 1]?.chapter_end ?? '?'} 章`;
        return (
          <div key={key} className="space-y-3">
            <div className="flex items-center gap-2 text-sm">
              <span
                className={cn(
                  'flex h-7 w-7 items-center justify-center',
                  isUnbound ? 'bg-surface-hover text-content-tertiary' : 'bg-brand/10 text-brand',
                )}
              >
                {isUnbound ? <Unlink className="h-3.5 w-3.5" /> : <Target className="h-3.5 w-3.5" />}
              </span>
              <span className={cn('font-medium', isUnbound ? 'text-content-secondary' : 'text-content')}>{groupLabel}</span>
              <span className="text-xs text-content-tertiary tabular-nums">{groupBridges.length} 个桥段</span>
              {!isUnbound && activeBeat != null && activeBeat === first?.beat_index && (
                <span className="inline-flex items-center gap-1 text-xs text-brand tabular-nums">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {llm && llm.content_chars === 0 && llm.reasoning_chars > 0
                    ? `思考中 ${llm.reasoning_chars.toLocaleString()} 字`
                    : '生成中'}
                  {eta != null ? ` · 预计还需 ~${Math.max(5, eta)}s` : ''}
                </span>
              )}
            </div>
            <div className="space-y-3">
              {groupBridges.map((bridge) => (
                <BridgeCard
                  key={bridge.id}
                  bridge={bridge}
                  partial={bridge.status === 'draft' ? partials[bridge.bridge_number] ?? null : null}
                  generating={bridge.status === 'draft' && activeBeat != null && activeBeat === bridge.beat_index}
                  onEdit={() => onEdit(bridge)}
                  onExpand={() => onExpand(bridge)}
                  onDelete={() => onDelete(bridge.id)}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}


// ============================================================
// 桥段卡片组件
// ============================================================

interface BridgeCardProps {
  bridge: PlotBridge;
  /** 打字机快照（仅 draft 卡片）：LLM 已写出的字段以幽灵文本渲染 */
  partial?: PartialBridge | null;
  /** 本卡所属节点正在生成 */
  generating?: boolean;
  onEdit: () => void;
  onExpand: () => void;
  onDelete: () => void;
}

type GhostKey = Exclude<keyof PartialBridge, 'bridge_number'>;

function BridgeCard({ bridge, partial = null, generating = false, onEdit, onExpand, onDelete }: BridgeCardProps) {
  const isCompleted = bridge.status === 'completed';
  const isDraft = bridge.status === 'draft';
  const secondary = bridge.secondary_beats ?? [];
  const primaryCount = secondary.filter(isPrimaryTask).length;
  const mentionCount = secondary.length - primaryCount;
  // 填充时记录的题材模板决定卡片标签（装逼点 / 反转点 …，C1-C4 语义）
  const ui = BRIDGE_TEMPLATE_UI[resolveTemplateKey(bridge.template)];
  // 幽灵文本：真值为空时用打字机快照顶上
  const ghostText = (key: GhostKey) => (partial && typeof partial[key] === 'string' ? partial[key] : null);
  const show = (real: string | null | undefined, key: GhostKey) => (real && real.trim() ? real : ghostText(key));
  const isGhost = (real: string | null | undefined, key: GhostKey) => !(real && real.trim()) && !!ghostText(key);
  const titleGhost = isDraft && !!ghostText('title');
  // 桥段绑定主线节点时显示节点信息 Tag
  const hasBeatBinding =
    bridge.beat_index != null &&
    bridge.beat_coverage_start != null &&
    bridge.beat_coverage_end != null;
  const coveragePct = hasBeatBinding
    ? `${Math.round((bridge.beat_coverage_start ?? 0) * 100)}%-${Math.round(
        (bridge.beat_coverage_end ?? 0) * 100,
      )}%`
    : null;
  return (
    <article className="hh-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="hh-tag tabular-nums">#{bridge.bridge_number}</span>
          <h3 className={cn('text-[15px] font-semibold', titleGhost ? 'italic text-content-secondary' : 'text-content')}>
            {titleGhost ? ghostText('title') : bridge.title}
            {generating && !titleGhost && <span className="ml-2 text-xs font-normal text-brand">正在写…</span>}
          </h3>
          <span className={cn('px-2 py-0.5 text-[11px] font-medium', BRIDGE_STATUS_CLASS[bridge.status])}>
            {BRIDGE_STATUS_LABEL[bridge.status]}
          </span>
          <span className="inline-flex items-center border border-surface-border px-2 py-0.5 text-[11px] text-content-secondary tabular-nums">
            第 {bridge.chapter_start}-{bridge.chapter_end} 章
          </span>
          {hasBeatBinding && (
            <Tooltip
              title={
                `本桥段绑定到主线节点 ${bridge.beat_index}，覆盖该节点进度 ${coveragePct}。` +
                ' 展开为章纲时会把覆盖度均分到 4 章并回写剧情线进度。'
              }
            >
              <span className="inline-flex items-center gap-1 border border-surface-border px-2 py-0.5 text-[11px] text-content-secondary tabular-nums">
                <Target className="h-3 w-3" />
                节点 {bridge.beat_index} · {coveragePct}
              </span>
            </Tooltip>
          )}
          {secondary.length > 0 && (
            <Tooltip
              title={secondary
                .map(
                  (t) =>
                    `${isPrimaryTask(t) ? '主B线' : '保温'} · ${t.line_type === 'character' ? '角色线' : '支线'}《${t.line_title}》[节点 ${t.beat_index}] ${t.beat_title}`,
                )
                .join('；')}
            >
              <span className="inline-flex items-center border border-surface-border px-2 py-0.5 text-[11px] text-content-secondary tabular-nums">
                {primaryCount > 0 ? `主B线 ${primaryCount}` : ''}
                {primaryCount > 0 && mentionCount > 0 ? ' · ' : ''}
                {mentionCount > 0 ? `保温 ${mentionCount}` : ''}
              </span>
            </Tooltip>
          )}
          <ProvenanceChip meta={bridge.generation_meta ?? null} />
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <button onClick={onEdit} className="hh-icon-btn-plain h-8 w-8" title="编辑桥段" aria-label="编辑桥段">
            <Pencil className="h-4 w-4" />
          </button>
          <Popconfirm
            title={`确定删除桥段「${bridge.title}」？`}
            description="不会删除已展开的章纲，但会解除关联"
            onConfirm={onDelete}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <button className="hh-icon-btn-plain h-8 w-8 hover:text-red-500" title="删除桥段" aria-label="删除桥段">
              <Trash2 className="h-4 w-4" />
            </button>
          </Popconfirm>
          {isCompleted ? (
            <span className="ml-1 inline-flex items-center gap-1 text-xs text-emerald-600">
              <CheckCircle2 className="h-3.5 w-3.5" />
              已展开
            </span>
          ) : (
            <button
              onClick={onExpand}
              disabled={isDraft}
              className="hh-btn-primary hh-btn-sm ml-1"
              title={isDraft ? '请先用「AI 填充桥段内容」填充后再展开' : `展开为第 ${bridge.chapter_start}-${bridge.chapter_end} 章（需前一桥段已展开）`}
            >
              <Expand className="h-3.5 w-3.5" />
              {isDraft ? '待填充' : '展开 4 章'}
            </button>
          )}
        </div>
      </div>

      <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm md:grid-cols-[auto_1fr]">
        <dt className="text-content-tertiary">目标</dt>
        <dd className={cn('leading-6', isGhost(bridge.goal, 'goal') ? 'italic text-content-secondary' : 'text-content')}>
          {show(bridge.goal, 'goal') ?? (generating ? '…' : '')}
        </dd>
        <dt className="text-content-tertiary">{ui.payoffLabel}</dt>
        <dd className={cn('leading-6', isGhost(bridge.showoff_point, 'showoff_point') ? 'italic text-content-secondary' : 'text-content')}>
          {bridge.payoff_type && (
            <span className="mr-1.5 rounded bg-surface-hover px-1.5 py-0.5 text-xs text-content-secondary">{bridge.payoff_type}</span>
          )}
          {show(bridge.showoff_point, 'showoff_point') ?? (generating ? '…' : '')}
        </dd>
        {show(bridge.golden_finger_usage, 'golden_finger_usage') && (
          <>
            <dt className="text-content-tertiary">金手指</dt>
            <dd className={cn('leading-6 text-content-secondary', isGhost(bridge.golden_finger_usage, 'golden_finger_usage') && 'italic')}>
              {show(bridge.golden_finger_usage, 'golden_finger_usage')}
            </dd>
          </>
        )}
      </dl>

      {/* 4 章卡片预览（draft 时用打字机快照渲染幽灵文本） */}
      <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-4">
        <ChapterCardPreview label={ui.positions.intro} hint={ui.hints.intro} content={show(bridge.c1_intro, 'c1_intro')} ghost={isGhost(bridge.c1_intro, 'c1_intro')} />
        <ChapterCardPreview label={ui.positions.build} hint={ui.hints.build} content={show(bridge.c2_build, 'c2_build')} ghost={isGhost(bridge.c2_build, 'c2_build')} />
        <ChapterCardPreview label={ui.positions.payoff} hint={ui.hints.payoff} content={show(bridge.c3_payoff, 'c3_payoff')} ghost={isGhost(bridge.c3_payoff, 'c3_payoff')} />
        <ChapterCardPreview label={ui.positions.aftermath} hint={ui.hints.aftermath} content={show(bridge.c4_aftermath, 'c4_aftermath')} ghost={isGhost(bridge.c4_aftermath, 'c4_aftermath')} />
      </div>

      {bridge.next_bridge_hook && (
        <p className="mt-3 border-l-2 border-brand/40 pl-3 text-xs leading-6 text-content-secondary">
          <span className="font-medium text-content">下桥段钩子：</span>
          {bridge.next_bridge_hook}
        </p>
      )}
    </article>
  );
}

function ChapterCardPreview({
  label,
  hint,
  content,
  ghost = false,
}: {
  label: string;
  hint: string;
  content: string | null | undefined;
  /** 内容来自打字机快照（尚未落库） */
  ghost?: boolean;
}) {
  return (
    <div className="hh-subpanel p-3 text-xs">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="font-semibold text-brand">{label}</span>
        <span className="text-[10px] text-content-tertiary">{hint}</span>
      </div>
      <p
        className={cn(
          'line-clamp-3 leading-5',
          ghost ? 'italic text-content-secondary' : content ? 'text-content-secondary' : 'text-content-tertiary',
        )}
        title={content ?? undefined}
      >
        {content || '待 AI 规划'}
      </p>
    </div>
  );
}

// ============================================================
// 生成溯源：本桥段填充时参考了什么 / 缺了什么
// ============================================================

const SLOT_LABEL: Record<string, string> = {
  project_skeleton: '项目信息',
  project_characters: '本书角色',
  world_rules_table: '世界规则表',
  plot_lines_with_beats: '全书骨架',
  dissect_methodology: '拆书·方法论',
  dissect_structure: '拆书·结构',
  dissect_bridges: '拆书·桥段范本',
  dissect_character_archive: '拆书·角色档案',
  dissect_synopsis: '拆书·全书弧线',
  dissect_archetypes: '拆书·角色塑造',
  dissect_worldbuilding: '拆书·世界观',
  dissect_corpus: '拆书·范本片段',
  dissect_style: '拆书·文风',
  system_role: '系统角色',
  system_base_style: '基础文风',
  output_spec: '输出要求',
};

const slotLabel = (s: string) => SLOT_LABEL[s] ?? s;

function WarningList({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <ul className="mt-1 space-y-0.5 text-amber-600">
      {warnings.map((w) => (
        <li key={w} className="flex items-start gap-1">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          <span>{w}</span>
        </li>
      ))}
    </ul>
  );
}

function ProvenanceChip({ meta }: { meta: BridgeGenerationMeta | null }) {
  if (!meta) return null;
  const warn = meta.warnings.length;
  const templateName = BRIDGE_TEMPLATE_UI[resolveTemplateKey(meta.template)].name;
  const pack = meta.reference_pack;
  const inputs = meta.inputs;
  const content = (
    <div className="max-w-[360px] space-y-2 text-xs leading-5">
      <p className="text-content-secondary">
        {meta.model} · 档位 {meta.model_tier || '?'} · {templateName} · ≈{meta.tokens_estimate} tokens
      </p>
      <div>
        <p className="font-medium text-content">参考包</p>
        <p className="text-content-secondary">
          {pack
            ? `${pack.title}：${Object.entries(pack.dimensions).map(([d, s]) => `${slotLabel(`dissect_${d}`)}(${s})`).join('、')}`
            : '未挂载'}
        </p>
      </div>
      <div>
        <p className="font-medium text-content">业务输入</p>
        <p className="text-content-secondary">
          节点 {inputs.beat.index}《{inputs.beat.title}》
          {inputs.next_beat_title ? ` · 下节点《${inputs.next_beat_title}》` : ''}
          {inputs.ledger_bridge_numbers.length ? ` · 账本 ${inputs.ledger_bridge_numbers.length} 个桥段` : ' · 无前文账本'}
          {inputs.opening_rules ? ' · 黄金三章规则' : ''}
          {inputs.story_outline_fields.length ? ` · 大纲字段 ${inputs.story_outline_fields.length} 项` : ''}
        </p>
      </div>
      <div>
        <p className="font-medium text-content">注入槽位</p>
        <p className="text-content-secondary">{meta.slots.filled.map(slotLabel).join('、') || '—'}</p>
        {meta.slots.truncated.length > 0 && (
          <p className="text-amber-600">被截断：{meta.slots.truncated.map(slotLabel).join('、')}</p>
        )}
        {meta.slots.skipped.length > 0 && (
          <p className="text-content-tertiary">未注入（为空）：{meta.slots.skipped.map(slotLabel).join('、')}</p>
        )}
      </div>
      <WarningList warnings={meta.warnings} />
      <p className="text-content-tertiary">{meta.generated_at}</p>
    </div>
  );
  return (
    <Popover content={content} title="本桥段参考了什么" trigger="click" placement="bottomLeft">
      <button
        type="button"
        className={cn(
          'inline-flex items-center gap-1 border px-2 py-0.5 text-[11px] tabular-nums',
          warn > 0 ? 'border-amber-300 text-amber-600' : 'border-surface-border text-content-secondary',
        )}
        title="查看本桥段填充时参考的资料"
      >
        <BookOpen className="h-3 w-3" />
        参考 {meta.slots.filled.length}
        {warn > 0 ? ` · ⚠ ${warn}` : ''}
      </button>
    </Popover>
  );
}

function StatItem({ label, value }: { label: string; value: number }) {
  return (
    <div className="px-5 py-4 md:px-6">
      <p className="text-xs text-content-tertiary">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-content tabular-nums">{value}</p>
    </div>
  );
}

// ============================================================
// 编辑桥段弹窗
// ============================================================

function EditBridgeModal({
  bridge,
  onClose,
  onSaved,
}: {
  bridge: PlotBridge | null;
  onClose: () => void;
  onSaved: (updated: PlotBridge) => void;
}) {
  const [form] = Form.useForm<UpdateBridgeRequest>();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (bridge) {
      form.setFieldsValue({
        title: bridge.title,
        goal: bridge.goal,
        showoff_point: bridge.showoff_point,
        golden_finger_usage: bridge.golden_finger_usage ?? '',
        c1_intro: bridge.c1_intro ?? '',
        c2_build: bridge.c2_build ?? '',
        c3_payoff: bridge.c3_payoff ?? '',
        c4_aftermath: bridge.c4_aftermath ?? '',
        next_bridge_hook: bridge.next_bridge_hook ?? '',
      });
    }
  }, [bridge, form]);

  const handleSave = async (values: UpdateBridgeRequest) => {
    if (!bridge) return;
    setSaving(true);
    try {
      const updated = await plotBridgesApi.update(bridge.id, values);
      toast.success('已保存');
      onSaved(updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={bridge ? `编辑桥段 #${bridge.bridge_number}` : '编辑桥段'}
      open={!!bridge}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnClose
    >
      <Form layout="vertical" form={form} onFinish={handleSave}>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Form.Item label="桥段标题" name="title" rules={[{ required: true, max: 200 }]}>
            <Input placeholder="8-15 字简洁标题，如『拜师云鹿书院』" />
          </Form.Item>
          <Form.Item label="金手指用法" name="golden_finger_usage">
            <Input placeholder="本桥段如何使用金手指（20-40 字）" />
          </Form.Item>
        </div>
        <Form.Item label="桥段目标" name="goal" rules={[{ required: true }]}>
          <Input.TextArea rows={2} placeholder="本桥段要解决的具体问题（30-60 字）" />
        </Form.Item>
        <Form.Item label="装逼点设计" name="showoff_point" rules={[{ required: true }]}>
          <Input.TextArea rows={2} placeholder="装逼/爽点设计（40-80 字）" />
        </Form.Item>

        <div className="my-3 border-t border-surface-border pt-3">
          <p className="mb-2 text-sm font-semibold text-content">4 章内容卡（章纲展开时用）</p>
        </div>
        <Form.Item label="C1 代入+信息差（5:5）" name="c1_intro">
          <Input.TextArea rows={3} placeholder="上半日常代入素材 + 下半信息差（80-120 字）" />
        </Form.Item>
        <Form.Item label="C2 拉扯+开装（9:1，章尾开装）" name="c2_build">
          <Input.TextArea rows={3} placeholder="拉扯素材 + 章尾开装动作（80-120 字）" />
        </Form.Item>
        <Form.Item label="C3 兑现爽点（10:0，无钩子）" name="c3_payoff">
          <Input.TextArea rows={3} placeholder="装逼完整展开 + 配角反应（80-120 字）" />
        </Form.Item>
        <Form.Item label="C4 善后+下一目标（承上启下）" name="c4_aftermath">
          <Input.TextArea rows={3} placeholder="本桥段收尾事件 + 下桥段引子（60-100 字）" />
        </Form.Item>
        <Form.Item label="给下一桥段的钩子" name="next_bridge_hook">
          <Input placeholder="20-40 字" />
        </Form.Item>

        <Form.Item className="!mb-0 text-right">
          <Button onClick={onClose} className="mr-2">取消</Button>
          <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ============================================================
// 展开为 4 章弹窗
// ============================================================

function ExpandBridgeModal({
  bridge,
  onClose,
  onStart,
  modelOptions,
  defaultModel,
  loadingModels,
  refreshModels,
}: {
  bridge: PlotBridge | null;
  onClose: () => void;
  /** 选好模型 → 页面启动后台展开任务并关闭本弹窗（进度在通用任务弹窗里） */
  onStart: (bridge: PlotBridge, model?: string) => Promise<void>;
  modelOptions: ModelOption[];
  defaultModel: string;
  loadingModels: boolean;
  refreshModels: () => void;
}) {
  const [form] = Form.useForm<{ model: string }>();

  // 异步加载完成、或弹窗打开时，把表单 model 字段同步到用户默认模型
  useEffect(() => {
    if (!bridge) return;
    const target = defaultModel || modelOptions[0]?.value;
    if (target) form.setFieldValue('model', target);
  }, [bridge, defaultModel, modelOptions, form]);

  const handleExpand = (values: { model: string }) => {
    if (!bridge) return;
    void onStart(bridge, values.model || undefined);
  };

  return (
    <Modal
      title={bridge ? `展开「${bridge.title}」为 4 章` : '展开桥段'}
      open={!!bridge}
      onCancel={onClose}
      footer={null}
      width={480}
      destroyOnClose
    >
      <Form
        layout="vertical"
        form={form}
        initialValues={{
          model: defaultModel || modelOptions[0]?.value || 'deepseek-v3',
        }}
        onFinish={handleExpand}
      >
        <p className="mb-4 text-sm leading-6 text-content-secondary">
          将生成第 <span className="font-medium text-content tabular-nums">{bridge?.chapter_start}-{bridge?.chapter_end}</span> 章
          （章号由桥段序号决定，需前一桥段已展开）。
        </p>
        <Form.Item
          label={
            <div className="flex items-center gap-2">
              <span>使用模型</span>
              <Tooltip title="重新从「设置」中配置的 API 拉取模型列表">
                <Button
                  type="text"
                  size="small"
                  icon={<ReloadOutlined spin={loadingModels} />}
                  onClick={refreshModels}
                />
              </Tooltip>
            </div>
          }
          name="model"
          rules={[{ required: true }]}
          extra="列表来自「设置」中配置的 API"
        >
          <Select
            options={modelOptions}
            loading={loadingModels}
            showSearch
            optionFilterProp="label"
            placeholder={loadingModels ? '加载模型中...' : '选择模型'}
          />
        </Form.Item>
        <Form.Item className="!mb-0 text-right">
          <Button onClick={onClose} className="mr-2">取消</Button>
          <Button type="primary" htmlType="submit" icon={<ExpandAltOutlined />}>
            展开为 4 章
          </Button>
        </Form.Item>
      </Form>
    </Modal>
  );
}
