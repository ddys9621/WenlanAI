/**
 * 世界地图（参考岚笺「作者标注沙盘」）：程序化纸质底图 + 作者标注的地点 + 地点档案。
 * - 坐标是平面布局的 0–100 百分比；默认浏览模式不能挪点，切到「标注」才能拖动；改动要点「保存布局」才写入，可撤销 50 步
 * - 保存带版本号：别处改过就拒绝覆盖，保留你的调整，由你决定放弃后载入最新
 * - AI 只生成布局候选：先预览（虚线点），采用后才写入；默认不挪动你已经放好的地点
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { isAxiosError } from 'axios';
import { Check, Eye, Loader2, Map as MapIcon, MousePointer2, Move, Save, Shuffle, Sparkles, Undo2, X } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useStore } from '@/store';
import { worldMapApi } from '@/services/api';
import { AIJobError, runAIJob } from '@/store/aiJobsStore';
import { PageHeader } from '@/components/ui/PageHeader';
import { useAssistantDataChange, useAssistantDetail } from '@/hooks/useAssistantPage';
import type { AssistantDataChange } from '@/store/assistantStore';
import { MapCanvas, type CanvasMarker } from '@/components/world-map/MapCanvas';
import { LocationInspector } from '@/components/world-map/LocationInspector';
import type { MapLayoutCandidate, MapLocation, WorldMapView } from '@/types/writing';
import type { SSEClientOptions } from '@/utils/sseClient';
import { buildBaseMap } from '@/utils/proceduralMap';
import { createHistory, historyBoundary, markSaved, pushSnapshot, undo, type MapHistory } from '@/utils/mapHistory';
import { changedMarkers, rebaseDrafts, type LocationDraft } from '@/utils/worldMap';

export default function WorldMap() {
  const { currentProject } = useStore();
  const projectId = currentProject?.id;
  const [view, setView] = useState<WorldMapView | null>(null);
  const [drafts, setDrafts] = useState<LocationDraft[]>([]);
  const [history, setHistory] = useState<MapHistory>(createHistory);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editable, setEditable] = useState(false);
  const [placing, setPlacing] = useState<MapLocation | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [candidate, setCandidate] = useState<MapLayoutCandidate | null>(null);
  const [previewCandidate, setPreviewCandidate] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(true);

  const viewRef = useRef(view);
  viewRef.current = view;
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;

  const apply = useCallback((next: WorldMapView, keepLocal: boolean, baseline?: MapLocation[]) => {
    setDrafts(rebaseDrafts(baseline ?? viewRef.current?.locations ?? [], draftsRef.current, next.locations, keepLocal));
    setView(next);
  }, []);

  const load = useCallback(async (keepLocal: boolean) => {
    if (!projectId) return;
    try {
      const next = await worldMapApi.get(projectId);
      apply(next, keepLocal);
      if (next.map.has_candidate) {
        const res = await worldMapApi.getCandidate(projectId);
        setCandidate(res.candidate);
      } else {
        setCandidate(null);
      }
    } catch { /* 已 toast */ } finally {
      setLoading(false);
    }
  }, [projectId, apply]);

  useEffect(() => {
    setView(null);
    setDrafts([]);
    setHistory(createHistory());
    setSelectedId(null);
    setPlacing(null);
    setEditable(false);
    setConflict(false);
    setLoading(true);
    void load(false);
  }, [projectId, load]);

  // 全局智能助笔：改了地点档案、建了 / 改了「地图位置」规则就重新载入（保留未保存的布局调整）；登记正在看的地点
  const onAssistantData = useCallback((change: AssistantDataChange) => {
    if (change.entity === 'location' || change.entity === 'world_rule') void load(true);
  }, [load]);
  useAssistantDataChange(onAssistantData);
  const focused = view?.locations.find((l) => l.id === selectedId);
  useAssistantDetail(focused ? { label: `世界地图 · 地点「${focused.name}」`, location_id: focused.id } : null);

  const pending = useMemo(() => (view ? changedMarkers(view.locations, drafts) : []), [view, drafts]);
  const dirty = pending.length > 0;

  useEffect(() => {
    if (!dirty) return;
    const guard = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [dirty]);

  const base = useMemo(
    () => buildBaseMap(view?.map.seed ?? 1, candidate && previewCandidate ? candidate.terrain : view?.map.terrain ?? {}),
    [view?.map.seed, view?.map.terrain, candidate, previewCandidate],
  );

  const kindOf = useMemo(() => new Map((view?.locations ?? []).map((l) => [l.id, l.kind])), [view]);
  const markers: CanvasMarker[] = drafts
    .filter((d) => !d.unplaced)
    .map((d) => ({ id: d.id, name: d.name, x: d.x, y: d.y, kind: kindOf.get(d.id) ?? 'other' }));
  const placedNames = new Set(markers.map((m) => m.name));
  const ghosts: CanvasMarker[] = candidate && previewCandidate
    ? candidate.locations
      .filter((l) => l.x !== null && l.y !== null && !placedNames.has(l.name))
      .map((l) => ({ id: `ghost-${l.name}`, name: l.name, x: l.x as number, y: l.y as number, kind: l.kind }))
    : [];

  const remember = () => setHistory((h) => pushSnapshot(h, draftsRef.current));

  const doUndo = () => {
    const { history: next, snapshot } = undo(history);
    if (!snapshot) return;
    setHistory(next);
    setDrafts(snapshot as LocationDraft[]);
  };

  const onMove = (id: string, x: number, y: number) =>
    setDrafts((ds) => ds.map((d) => (d.id === id ? { ...d, x, y, unplaced: false } : d)));

  const onMoveCancel = (id: string, x: number, y: number) => {
    setHistory((h) => undo(h).history);
    onMove(id, x, y);
  };

  const onPlace = (x: number, y: number) => {
    if (!placing) return;
    remember();
    onMove(placing.id, x, y);
    setSelectedId(placing.id);
    setPlacing(null);
  };

  const onKeyCommand = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      if (placing) setPlacing(null);
      else if (editable) setEditable(false);
      else setSelectedId(null);
      return true;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      doUndo();
      return true;
    }
    return false;
  };

  const save = async () => {
    if (!projectId || !view || !dirty) return;
    const submitted = pending;
    const boundary = historyBoundary(history);
    const submittedState = view.locations.map((l) => {
      const change = submitted.find((m) => m.id === l.id);
      return change ? { ...l, x: change.x, y: change.y } : l;
    });
    setSaving(true);
    try {
      const next = await worldMapApi.saveLayout(projectId, view.map.revision, submitted);
      apply(next, true, submittedState);
      setHistory((h) => markSaved(h, boundary));
      setConflict(false);
      toast.success(`已保存 ${submitted.length} 个地点的位置`);
    } catch (err) {
      if (isAxiosError(err) && err.response?.status === 409) {
        setConflict(true);
      } else {
        const detail = isAxiosError(err) ? (err.response?.data as { detail?: string } | undefined)?.detail : undefined;
        toast.error(detail || '保存失败，你的调整还在，可以重试');
      }
    } finally {
      setSaving(false);
    }
  };

  const generate = async () => {
    if (!projectId) return;
    setGenerating(true);
    try {
      const job = await runAIJob({
        kind: 'world_map_generate',
        title: 'AI 设计世界地图布局',
        projectId,
        connect: (options: SSEClientOptions<unknown>) =>
          worldMapApi.generateStream(projectId, options as SSEClientOptions<{ candidate: MapLayoutCandidate }>),
      });
      const result = job.result as { candidate?: MapLayoutCandidate } | null;
      if (result?.candidate) {
        setCandidate(result.candidate);
        setPreviewCandidate(true);
        toast.success(`布局候选已生成：${result.candidate.locations.length} 个地点，预览后再决定是否采用`);
      }
      await load(true);
    } catch (error) {
      if (!(error instanceof AIJobError && error.job.status === 'cancelled')) {
        toast.error((error as Error)?.message || '生成失败');
      }
    } finally {
      setGenerating(false);
    }
  };

  const adopt = async (replacePositions: boolean) => {
    if (!projectId) return;
    if (replacePositions && !window.confirm('同名地点也改成候选里的坐标？你放好的位置会被覆盖（采用后仍可在标注模式下拖回）。')) return;
    try {
      const next = await worldMapApi.adoptCandidate(projectId, replacePositions);
      apply(next, !replacePositions);
      setCandidate(null);
      toast.success('已采用布局候选');
    } catch { /* 已 toast */ }
  };

  const discardCandidate = async () => {
    if (!projectId) return;
    try {
      apply(await worldMapApi.discardCandidate(projectId), true);
      setCandidate(null);
    } catch { /* 已 toast */ }
  };

  const reshuffle = async () => {
    if (!projectId) return;
    try {
      apply(await worldMapApi.updateSettings(projectId, { seed: Math.floor(Math.random() * 2_000_000_000) }), true);
    } catch { /* 已 toast */ }
  };

  if (!projectId) return null;

  const placedCount = markers.length;
  const total = drafts.length;

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        eyebrow="设定"
        title="世界地图"
        description="世界规则里的地点和故事里出现过的地点标在一张纸质地图上：拖动平移、滚轮缩放，点地点看档案和按章节的出处。AI 写正文、规划卷纲与章纲时会参考这里的方位远近；改坐标不会改动任何故事内容。"
        badges={<span className="lj-badge lj-badge--muted">{placedCount}/{total} 已定位</span>}
        actions={
          <>
            <button onClick={() => void generate()} disabled={generating} className="hh-btn-secondary">
              {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              AI 生成布局
            </button>
            <button onClick={() => void reshuffle()} disabled={dirty} className="hh-btn-ghost" title={dirty ? '先保存或撤销当前调整' : '换一张程序化底图（地点坐标不变）'}>
              <Shuffle className="h-4 w-4" />换底图
            </button>
            <button onClick={doUndo} disabled={history.past.length === 0 || saving} className="hh-btn-ghost" title="撤销（Ctrl+Z）">
              <Undo2 className="h-4 w-4" />撤销
            </button>
            <button onClick={() => void save()} disabled={!dirty || saving} className="hh-btn-primary">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              保存布局{dirty ? ` (${pending.length})` : ''}
            </button>
          </>
        }
      />

      {conflict && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-signal/30 bg-signal-soft px-4 py-3 text-sm text-cinnabar">
          <span>地图在别处被改过（版本已变化），没有覆盖。你的 {pending.length} 处调整还在这里。</span>
          <button onClick={() => { setConflict(false); setHistory(createHistory()); void load(false); }} className="hh-btn-secondary hh-btn-sm">
            放弃我的调整，载入最新
          </button>
        </div>
      )}

      {candidate && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-brand/30 bg-brand-50 px-4 py-3 text-sm">
          <span className="text-content">
            <span className="lj-badge lj-badge--candidate mr-2">AI 布局候选</span>
            {candidate.locations.length} 个地点{previewCandidate ? '，虚线点是候选位置' : ''}。采用前地图不会变化。
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => setPreviewCandidate((v) => !v)} className="hh-btn-ghost hh-btn-sm">
              <Eye className="h-3.5 w-3.5" />{previewCandidate ? '隐藏预览' : '预览'}
            </button>
            <button onClick={() => void discardCandidate()} className="hh-btn-ghost hh-btn-sm"><X className="h-3.5 w-3.5" />丢弃</button>
            <button onClick={() => void adopt(true)} className="hh-btn-secondary hh-btn-sm">采用并覆盖坐标</button>
            <button onClick={() => void adopt(false)} className="hh-btn-primary hh-btn-sm"><Check className="h-3.5 w-3.5" />采用（不挪已放好的）</button>
          </div>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="hh-panel overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border px-4 py-2">
            <div className="flex items-center gap-1 rounded border border-surface-border bg-surface p-0.5">
              <button
                onClick={() => setEditable(false)}
                className={cn('flex items-center gap-1 rounded-sm px-2.5 py-1 text-xs font-medium', !editable ? 'bg-brand text-white' : 'text-content-secondary')}
              >
                <MousePointer2 className="h-3.5 w-3.5" />浏览
              </button>
              <button
                onClick={() => setEditable(true)}
                className={cn('flex items-center gap-1 rounded-sm px-2.5 py-1 text-xs font-medium', editable ? 'bg-brand text-white' : 'text-content-secondary')}
              >
                <Move className="h-3.5 w-3.5" />标注
              </button>
            </div>
            <div className="flex items-center gap-3 text-xs text-content-secondary">
              <span className="hidden md:inline">{editable ? '拖动地点改位置 · Esc 退出标注' : '浏览不会挪动地点 · 切到「标注」才能拖'}</span>
              <label className="flex cursor-pointer items-center gap-1.5">
                <input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} />
                显示地名
              </label>
            </div>
          </div>
          {loading && !view ? (
            <div className="flex h-[420px] items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-brand" /></div>
          ) : (
            <div className="relative">
              <MapCanvas
                base={base}
                markers={markers}
                ghosts={ghosts}
                selectedId={selectedId}
                editable={editable}
                placing={placing?.name ?? null}
                showLabels={showLabels}
                onSelect={(id) => { if (!placing) setSelectedId(id); }}
                onMoveStart={remember}
                onMove={onMove}
                onMoveCancel={onMoveCancel}
                onPlace={onPlace}
                onPlaceOutside={() => toast.info('落点在底图外，没有放置')}
                onKeyCommand={onKeyCommand}
              />
              {total === 0 && !candidate && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                  <div className="pointer-events-auto max-w-sm rounded border border-surface-border bg-white/95 px-5 py-4 text-center shadow-md">
                    <MapIcon className="mx-auto h-7 w-7 text-brand" />
                    <p className="mt-2 text-sm font-medium text-content">地图上还没有地点</p>
                    <p className="mt-1 text-xs leading-5 text-content-secondary">点「AI 生成布局」按故事里出现过的地点排一版（先预览、采用才写入），或在右侧「故事地点」里逐个建。</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        <aside className="hh-panel flex max-h-[calc(min(72vh,760px)+44px)] min-h-[420px] flex-col overflow-hidden">
          {view && (
            <LocationInspector
              projectId={projectId}
              locations={view.locations}
              storyLocations={view.story_locations}
              drafts={drafts}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onStartPlacing={(location) => { setPlacing(location); setSelectedId(location.id); }}
              onChanged={() => load(true)}
            />
          )}
        </aside>
      </div>
    </div>
  );
}

