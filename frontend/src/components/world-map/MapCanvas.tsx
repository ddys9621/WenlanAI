/**
 * 世界地图画布：程序化纸质底图 + 地点标注。
 * - 浏览模式：拖动平移、滚轮缩放（50%–300%）、点地点看档案；不会挪动任何坐标
 * - 标注模式：拖动地点改坐标（移动超过 4px 才算一次拖动，取消会还原）；放置模式下点底图落点，底图外不落点
 * - 地点圆点与名牌不随缩放变大；平移 / 缩放只是视图状态，不会保存
 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { Maximize2, Minus, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { MapLocationKind } from '@/types/writing';
import { MAP_HEIGHT, MAP_WIDTH, type BaseMap } from '@/utils/proceduralMap';
import { clampPercent } from '@/utils/worldMap';

export interface CanvasMarker {
  id: string;
  name: string;
  x: number;
  y: number;
  kind: MapLocationKind;
}

interface MapCanvasProps {
  base: BaseMap;
  markers: CanvasMarker[];
  /** AI 布局候选的预览点（虚线，不可交互） */
  ghosts?: CanvasMarker[];
  selectedId: string | null;
  editable: boolean;
  /** 正在放置的地点名（点底图落点） */
  placing: string | null;
  showLabels: boolean;
  onSelect: (id: string | null) => void;
  /** 一次拖动开始（父组件记撤销快照） */
  onMoveStart: (id: string) => void;
  onMove: (id: string, x: number, y: number) => void;
  /** 拖动被取消：还原到起点 */
  onMoveCancel: (id: string, x: number, y: number) => void;
  onPlace: (x: number, y: number) => void;
  onPlaceOutside: () => void;
  /** 父组件先处理的按键（撤销 / Esc），返回 true 表示已处理 */
  onKeyCommand?: (e: ReactKeyboardEvent<HTMLDivElement>) => boolean;
}

const MIN_SCALE = 0.5;
const MAX_SCALE = 3;
const DRAG_THRESHOLD = 4;
const ASPECT = MAP_HEIGHT / MAP_WIDTH;

const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));

/** 抓住指针，拖出元素外也能收到 move / up；指针已失效（如触控取消）时浏览器会抛错，忽略即可 */
const capture = (el: Element, pointerId: number) => {
  try {
    el.setPointerCapture(pointerId);
  } catch {
    /* 指针不可捕获时退化为普通冒泡 */
  }
};

type Gesture =
  | { type: 'pan'; pointerId: number; startX: number; startY: number; tx: number; ty: number; moved: boolean; markerId: string | null }
  | { type: 'marker'; pointerId: number; startX: number; startY: number; id: string; originX: number; originY: number; dragging: boolean };

export function MapCanvas({
  base, markers, ghosts = [], selectedId, editable, placing, showLabels,
  onSelect, onMoveStart, onMove, onMoveCancel, onPlace, onPlaceOutside, onKeyCommand,
}: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const [size, setSize] = useState({ w: 800, h: 560 });
  const [view, setView] = useState({ scale: 1, tx: 0, ty: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      setSize({ w: entry.contentRect.width, h: entry.contentRect.height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const mapW = Math.max(200, Math.min(size.w, size.h / ASPECT));
  const mapH = mapW * ASPECT;
  const ox = (size.w - mapW) / 2;
  const oy = (size.h - mapH) / 2;

  const percentAt = useCallback((clientX: number, clientY: number) => {
    const rect = mapRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return null;
    return clampPercent(((clientX - rect.left) / rect.width) * 100, ((clientY - rect.top) / rect.height) * 100);
  }, []);

  const zoomAt = useCallback((factor: number, clientX?: number, clientY?: number) => {
    setView((v) => {
      const scale = clampScale(v.scale * factor);
      const rect = containerRef.current?.getBoundingClientRect();
      const px = clientX !== undefined && rect ? clientX - rect.left - ox : mapW / 2;
      const py = clientY !== undefined && rect ? clientY - rect.top - oy : mapH / 2;
      const mx = (px - v.tx) / v.scale;
      const my = (py - v.ty) / v.scale;
      return { scale, tx: px - mx * scale, ty: py - my * scale };
    });
  }, [mapW, mapH, ox, oy]);

  const fit = () => setView({ scale: 1, tx: 0, ty: 0 });

  // 滚轮缩放要阻止页面滚动：React 的 onWheel 是 passive，这里手动挂非 passive 监听
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX, e.clientY);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomAt]);

  const startPan = (e: ReactPointerEvent, markerId: string | null) => {
    gesture.current = { type: 'pan', pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, tx: view.tx, ty: view.ty, moved: false, markerId };
    capture(e.currentTarget, e.pointerId);
  };

  const onBackgroundDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest('[data-map-ui]')) return;
    e.preventDefault();
    containerRef.current?.focus();
    if (placing) {
      const pos = percentAt(e.clientX, e.clientY);
      if (pos) onPlace(pos[0], pos[1]);
      else onPlaceOutside();
      return;
    }
    startPan(e, null);
  };

  const onMarkerDown = (e: ReactPointerEvent<HTMLButtonElement>, marker: CanvasMarker) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    containerRef.current?.focus();
    if (placing) return;
    if (editable) {
      gesture.current = {
        type: 'marker', pointerId: e.pointerId, startX: e.clientX, startY: e.clientY,
        id: marker.id, originX: marker.x, originY: marker.y, dragging: false,
      };
      capture(e.currentTarget, e.pointerId);
    } else {
      startPan(e, marker.id);
    }
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    const g = gesture.current;
    if (!g || g.pointerId !== e.pointerId) return;
    const dx = e.clientX - g.startX;
    const dy = e.clientY - g.startY;
    if (g.type === 'pan') {
      if (!g.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      g.moved = true;
      setView((v) => ({ ...v, tx: g.tx + dx, ty: g.ty + dy }));
      return;
    }
    if (!g.dragging) {
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      g.dragging = true;
      onMoveStart(g.id);
    }
    const pos = percentAt(e.clientX, e.clientY);
    if (pos) onMove(g.id, pos[0], pos[1]);
  };

  const onPointerUp = (e: ReactPointerEvent) => {
    const g = gesture.current;
    if (!g || g.pointerId !== e.pointerId) return;
    gesture.current = null;
    if (g.type === 'pan') {
      if (!g.moved) onSelect(g.markerId);
      return;
    }
    if (!g.dragging) onSelect(g.id);
  };

  const onPointerCancel = (e: ReactPointerEvent) => {
    const g = gesture.current;
    if (!g || g.pointerId !== e.pointerId) return;
    gesture.current = null;
    if (g.type === 'marker' && g.dragging) onMoveCancel(g.id, g.originX, g.originY);
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (onKeyCommand?.(e)) return;
    const step = 40;
    const actions: Record<string, () => void> = {
      ArrowLeft: () => setView((v) => ({ ...v, tx: v.tx + step })),
      ArrowRight: () => setView((v) => ({ ...v, tx: v.tx - step })),
      ArrowUp: () => setView((v) => ({ ...v, ty: v.ty + step })),
      ArrowDown: () => setView((v) => ({ ...v, ty: v.ty - step })),
      '+': () => zoomAt(1.2),
      '=': () => zoomAt(1.2),
      '-': () => zoomAt(1 / 1.2),
      '0': fit,
    };
    const action = actions[e.key];
    if (action && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      action();
    }
  };

  const inverse = 1 / view.scale;

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onPointerDown={onBackgroundDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      className={cn(
        'relative h-[min(72vh,760px)] min-h-[420px] w-full touch-none select-none overflow-hidden bg-[#dfe6e1] outline-none focus-visible:ring-2 focus-visible:ring-brand/40',
        placing ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing',
      )}
      aria-label="世界地图画布：方向键平移，加减号缩放，0 复位"
    >
      <div
        ref={mapRef}
        className="absolute left-0 top-0 origin-top-left"
        style={{ width: mapW, height: mapH, transform: `translate(${ox + view.tx}px, ${oy + view.ty}px) scale(${view.scale})` }}
      >
        <BaseMapSvg base={base} />

        {ghosts.map((g) => (
          <div
            key={`ghost-${g.name}`}
            className="pointer-events-none absolute"
            style={{ left: `${g.x}%`, top: `${g.y}%`, transform: `translate(-50%, -50%) scale(${inverse})` }}
          >
            <span className="block h-3.5 w-3.5 rounded-full border-2 border-dashed border-brand bg-white/70" />
            {showLabels && <span className="absolute left-4 top-1/2 -translate-y-1/2 whitespace-nowrap rounded-sm border border-dashed border-brand/60 bg-white/80 px-1.5 text-[11px] text-brand-600">{g.name}</span>}
          </div>
        ))}

        {markers.map((m) => {
          const selected = m.id === selectedId;
          return (
            <button
              key={m.id}
              type="button"
              onPointerDown={(e) => onMarkerDown(e, m)}
              onPointerMove={(e) => { e.stopPropagation(); onPointerMove(e); }}
              onPointerUp={(e) => { e.stopPropagation(); onPointerUp(e); }}
              onPointerCancel={(e) => { e.stopPropagation(); onPointerCancel(e); }}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(m.id); } }}
              aria-pressed={selected}
              aria-label={`地点：${m.name}`}
              className={cn('group absolute flex items-center outline-none', editable ? 'cursor-move' : 'cursor-pointer')}
              style={{ left: `${m.x}%`, top: `${m.y}%`, transform: `translate(-9px, -50%) scale(${inverse})`, transformOrigin: '9px 50%' }}
            >
              <span className="relative flex h-[18px] w-[18px] items-center justify-center">
                <span className="absolute h-[18px] w-[30px] rounded-[50%] border border-[#E13E20]/30" style={{ transform: 'scaleY(0.45) translateY(18px)' }} />
                <span className={cn(
                  'h-3.5 w-3.5 rounded-full border-2 border-[#fff8ee] bg-[#E13E20] shadow-[0_1px_3px_rgba(0,0,0,0.35)]',
                  selected && 'ring-[3px] ring-brand/70',
                )} />
              </span>
              {(showLabels || selected) && (
                <span className={cn(
                  'ml-1 whitespace-nowrap rounded-sm border px-1.5 py-px font-serif text-[12px] leading-4 shadow-xs',
                  selected ? 'border-[#E13E20] bg-[#fffaf0] text-content' : 'border-[#e8a27f]/70 bg-[#fffaf0]/90 text-content group-hover:border-[#E13E20]',
                )}>
                  {m.name}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div data-map-ui className="absolute bottom-3 right-3 flex cursor-default items-center gap-1 rounded border border-surface-border bg-white/95 p-1 shadow-xs">
        <button type="button" onClick={() => zoomAt(1 / 1.2)} className="hh-icon-btn-plain h-7 w-7" aria-label="缩小"><Minus className="h-3.5 w-3.5" /></button>
        <span className="w-11 text-center text-[11px] tabular-nums text-content-secondary">{Math.round(view.scale * 100)}%</span>
        <button type="button" onClick={() => zoomAt(1.2)} className="hh-icon-btn-plain h-7 w-7" aria-label="放大"><Plus className="h-3.5 w-3.5" /></button>
        <button type="button" onClick={fit} className="hh-icon-btn-plain h-7 w-7" aria-label="复位"><Maximize2 className="h-3.5 w-3.5" /></button>
      </div>
      {placing && (
        <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded border border-brand/30 bg-white/95 px-3 py-1.5 text-xs text-content shadow-xs">
          点击底图放置「{placing}」 · Esc 取消
        </div>
      )}
    </div>
  );
}

/** 程序化纸质底图（SVG，1000×700 画布） */
function BaseMapSvg({ base }: { base: BaseMap }) {
  return (
    <svg viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
      <defs>
        <filter id="wm-paper" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="3" result="noise" />
          <feColorMatrix in="noise" type="matrix" values="0 0 0 0 0.45  0 0 0 0 0.40  0 0 0 0 0.30  0 0 0 0.07 0" result="grain" />
          <feComposite in="grain" in2="SourceGraphic" operator="in" result="grainIn" />
          <feMerge><feMergeNode in="SourceGraphic" /><feMergeNode in="grainIn" /></feMerge>
        </filter>
        <pattern id="wm-waves" width="36" height="18" patternUnits="userSpaceOnUse">
          <path d="M0 9 Q9 3 18 9 T36 9" fill="none" stroke="#9fb5ad" strokeWidth="0.8" opacity="0.55" />
        </pattern>
      </defs>
      <rect width={MAP_WIDTH} height={MAP_HEIGHT} fill="#cddbd5" />
      <rect width={MAP_WIDTH} height={MAP_HEIGHT} fill="url(#wm-waves)" />
      <path d={base.coastPath} fill="#efe8d6" filter="url(#wm-paper)" />
      <path d={base.coastPath} fill="none" stroke="#7d735f" strokeWidth="1.6" />
      <path d={base.coastPath} fill="none" stroke="#7d735f" strokeWidth="0.6" strokeDasharray="2 5" opacity="0.5" transform="translate(4 4)" />

      {Array.from({ length: 9 }, (_, i) => (
        <line key={`gx${i}`} x1={(i + 1) * 100} y1={0} x2={(i + 1) * 100} y2={MAP_HEIGHT} stroke="#5d5444" strokeWidth="0.4" opacity="0.12" />
      ))}
      {Array.from({ length: 6 }, (_, i) => (
        <line key={`gy${i}`} x1={0} y1={(i + 1) * 100} x2={MAP_WIDTH} y2={(i + 1) * 100} stroke="#5d5444" strokeWidth="0.4" opacity="0.12" />
      ))}

      {base.rivers.map((d, i) => (
        <g key={`river-${i}`}>
          <path d={d} fill="none" stroke="#e9f0ec" strokeWidth="5" strokeLinecap="round" />
          <path d={d} fill="none" stroke="#7fa3ad" strokeWidth="2.2" strokeLinecap="round" />
        </g>
      ))}

      {base.forests.map((f, i) => (
        <g key={`forest-${i}`} opacity="0.85">
          <circle cx={f.x} cy={f.y} r={f.r} fill="#bccaa8" stroke="#80946f" strokeWidth="0.8" />
          <circle cx={f.x + f.r * 0.7} cy={f.y + f.r * 0.3} r={f.r * 0.6} fill="#c8d4b4" stroke="#80946f" strokeWidth="0.6" />
        </g>
      ))}

      {base.mountains.map((m, i) => (
        <g key={`peak-${i}`}>
          <path d={`M${m.x - m.size} ${m.y} L${m.x} ${m.y - m.size * 1.25} L${m.x + m.size} ${m.y} Z`} fill="#ddd1b6" stroke="#6c624f" strokeWidth="1.1" strokeLinejoin="round" />
          <path d={`M${m.x} ${m.y - m.size * 1.25} L${m.x + m.size * 0.35} ${m.y} `} fill="none" stroke="#6c624f" strokeWidth="0.7" opacity="0.6" />
        </g>
      ))}

      {base.regions.map((r) => (
        <text key={`region-${r.name}`} x={r.x} y={r.y} textAnchor="middle" fontSize="22" letterSpacing="8" fill="#5d5444" opacity="0.45" style={{ fontFamily: '"Noto Serif SC", "Songti SC", serif' }}>
          {r.name}
        </text>
      ))}

      <g transform={`translate(${MAP_WIDTH - 70} 70)`} opacity="0.7">
        <circle r="30" fill="none" stroke="#6c624f" strokeWidth="0.8" />
        <path d="M0 -34 L6 0 L0 34 L-6 0 Z" fill="#6c624f" />
        <path d="M-34 0 L0 5 L34 0 L0 -5 Z" fill="#a39780" />
        <text y="-40" textAnchor="middle" fontSize="12" fill="#5d5444" style={{ fontFamily: '"Noto Serif SC", serif' }}>北</text>
      </g>
      <rect x="6" y="6" width={MAP_WIDTH - 12} height={MAP_HEIGHT - 12} fill="none" stroke="#6c624f" strokeWidth="1.2" opacity="0.7" />
      <rect x="11" y="11" width={MAP_WIDTH - 22} height={MAP_HEIGHT - 22} fill="none" stroke="#6c624f" strokeWidth="0.5" opacity="0.5" />
    </svg>
  );
}
