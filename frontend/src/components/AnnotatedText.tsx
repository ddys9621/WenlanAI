import React, { useMemo, useEffect, useRef, useState } from 'react';
import {
  buildSegments,
  resolveSpans,
  type AnnotationType,
  type MemoryAnnotation,
  type TextSegment,
} from '@/utils/annotationSegments';

export type { MemoryAnnotation } from '@/utils/annotationSegments';

interface AnnotatedTextProps {
  content: string;
  annotations: MemoryAnnotation[];
  onAnnotationClick?: (annotation: MemoryAnnotation) => void;
  activeAnnotationId?: string;
  scrollToAnnotation?: string;
  style?: React.CSSProperties;
}

// 类型颜色映射
const TYPE_COLORS: Record<AnnotationType, string> = {
  hook: '#ff6b6b',
  foreshadow: '#6b7bff',
  plot_point: '#51cf66',
  character_event: '#ffd93d',
};

// 类型图标映射
const TYPE_ICONS: Record<AnnotationType, string> = {
  hook: '🎣',
  foreshadow: '🌟',
  plot_point: '💎',
  character_event: '👤',
};

/** 悬停中的片段：fixed 定位的浮层不受阅读区 overflow 裁剪，上方空间不够就翻到下方 */
interface HoverState {
  key: number;
  covering: MemoryAnnotation[];
  x: number;
  top: number;
  bottom: number;
}

/**
 * 带标注的文本组件
 * 将记忆标注可视化地展示在章节文本中
 */
const AnnotatedText: React.FC<AnnotatedTextProps> = ({
  content,
  annotations,
  onAnnotationClick,
  activeAnnotationId,
  scrollToAnnotation,
  style,
}) => {
  const annotationRefs = useRef<Record<string, HTMLSpanElement | null>>({});
  const [hover, setHover] = useState<HoverState | null>(null);

  // 当需要滚动到特定标注时
  useEffect(() => {
    if (scrollToAnnotation && annotationRefs.current[scrollToAnnotation]) {
      annotationRefs.current[scrollToAnnotation]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [scrollToAnnotation]);

  // 解析标注在正文中的区间（丢弃类型未知 / 位置无效的标注）
  const spans = useMemo(() => {
    const resolved = resolveSpans(content, annotations ?? []);
    const dropped = (annotations?.length ?? 0) - resolved.length;
    if (dropped > 0) {
      console.warn(`AnnotatedText: ${dropped}个标注无法在正文中定位，可展示标注${resolved.length}个`);
    }
    return resolved;
  }, [annotations, content]);

  // 在标注边界处切分正文；重叠 / 相同区间的标注共享同一片段，正文不会重复或错位
  const segments = useMemo(() => buildSegments(content, spans), [content, spans]);

  // 单条标注的工具提示内容
  const renderTooltipBody = (annotation: MemoryAnnotation) => (
    <div key={annotation.id}>
      <div className="mb-1 font-semibold">
        {TYPE_ICONS[annotation.type]} {annotation.title}
      </div>
      <div className="text-xs opacity-90">
        {annotation.content.slice(0, 100)}
        {annotation.content.length > 100 ? '...' : ''}
      </div>
      <div className="mt-2 text-[11px] opacity-70">重要性: {(annotation.importance * 10).toFixed(1)}/10</div>
      {annotation.tags && annotation.tags.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
          {annotation.tags.map((tag, i) => (
            <span key={i} className="bg-white/20 px-1.5 py-px">{tag}</span>
          ))}
        </div>
      )}
    </div>
  );

  // 渲染标注片段
  const renderAnnotatedSegment = (segment: TextSegment) => {
    if (segment.type === 'text') {
      return <span key={segment.start}>{segment.content}</span>;
    }

    const { annotations: covering, starting } = segment;
    // 片段样式以"从这里开始的标注"为主，否则沿用覆盖它的第一条标注
    const primary = starting[0] ?? covering[0];
    const color = TYPE_COLORS[primary.type];
    const isActive = covering.some((a) => a.id === activeAnnotationId);
    const isHovered = hover?.key === segment.start;

    // 多条标注共享片段时：点击在它们之间轮换，方便逐个查看
    const handleClick = () => {
      const activeIndex = covering.findIndex((a) => a.id === activeAnnotationId);
      onAnnotationClick?.(covering[(activeIndex + 1) % covering.length]);
    };

    return (
      <span
        key={segment.start}
        ref={(el) => {
          for (const annotation of starting) {
            annotationRefs.current[annotation.id] = el;
          }
        }}
        data-annotation-id={covering.map((a) => a.id).join(' ')}
        className={`annotated-text ${isActive ? 'active' : ''}`}
        style={{
          position: 'relative',
          borderBottom: `2px solid ${color}`,
          cursor: 'pointer',
          backgroundColor: isHovered ? `${color}33` : isActive ? `${color}22` : 'transparent',
          transition: 'all 0.2s',
          padding: '2px 0',
        }}
        onClick={handleClick}
        onMouseEnter={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setHover({ key: segment.start, covering, x: r.left + r.width / 2, top: r.top, bottom: r.bottom });
        }}
        onMouseLeave={() => setHover((h) => (h?.key === segment.start ? null : h))}
      >
        {segment.content}
        {starting.length > 0 && (
          <span
            style={{
              position: 'absolute',
              top: -20,
              left: '50%',
              transform: 'translateX(-50%)',
              fontSize: 14,
              whiteSpace: 'nowrap',
              pointerEvents: 'none',
            }}
          >
            {starting.map((a) => TYPE_ICONS[a.type]).join('')}
          </span>
        )}
      </span>
    );
  };

  const flipBelow = hover ? hover.top < 180 : false;

  return (
    <div
      style={{
        lineHeight: 2,
        fontSize: 16,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        ...style,
      }}
    >
      {segments.map(renderAnnotatedSegment)}
      {hover && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-50 flex max-w-[300px] flex-col gap-2.5 bg-content px-3 py-2 text-sm leading-normal text-white shadow-lg"
          style={{
            left: hover.x,
            top: flipBelow ? hover.bottom + 8 : hover.top - 8,
            transform: flipBelow ? 'translateX(-50%)' : 'translate(-50%, -100%)',
          }}
        >
          {hover.covering.map(renderTooltipBody)}
        </div>
      )}
    </div>
  );
};

export default AnnotatedText;
