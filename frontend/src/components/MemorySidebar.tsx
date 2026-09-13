import React, { useMemo, useEffect, useRef } from 'react';
import { Flame, Star, Zap, User, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { CollapseSection } from '@/components/ui/CollapseSection';
import { Pill } from '@/components/ui/Pill';
import type { MemoryAnnotation } from './AnnotatedText';

interface MemorySidebarProps {
  annotations: MemoryAnnotation[];
  activeAnnotationId?: string;
  onAnnotationClick?: (annotation: MemoryAnnotation) => void;
  scrollToAnnotation?: string;
}

// 类型配置
const TYPE_CONFIG: Record<MemoryAnnotation['type'], { label: string; Icon: LucideIcon; color: string }> = {
  hook: { label: '钩子', Icon: Flame, color: '#ff6b6b' },
  foreshadow: { label: '伏笔', Icon: Star, color: '#6b7bff' },
  plot_point: { label: '情节点', Icon: Zap, color: '#51cf66' },
  character_event: { label: '角色事件', Icon: User, color: '#ffd93d' },
};

/**
 * 记忆侧边栏组件
 * 展示章节的所有记忆标注
 */
const MemorySidebar: React.FC<MemorySidebarProps> = ({
  annotations,
  activeAnnotationId,
  onAnnotationClick,
  scrollToAnnotation,
}) => {
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // 当需要滚动到特定标注卡片时
  useEffect(() => {
    if (scrollToAnnotation && cardRefs.current[scrollToAnnotation]) {
      cardRefs.current[scrollToAnnotation]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [scrollToAnnotation]);

  // 按类型分组，每组按重要性排序
  const groupedAnnotations = useMemo(() => {
    const groups: Record<MemoryAnnotation['type'], MemoryAnnotation[]> = {
      hook: [],
      foreshadow: [],
      plot_point: [],
      character_event: [],
    };
    annotations.forEach((annotation) => {
      groups[annotation.type]?.push(annotation);
    });
    (Object.keys(groups) as MemoryAnnotation['type'][]).forEach((type) => {
      groups[type].sort((a, b) => b.importance - a.importance);
    });
    return groups;
  }, [annotations]);

  if (annotations.length === 0) {
    return <p className="py-8 text-center text-xs text-content-tertiary">暂无分析数据</p>;
  }

  // 渲染单个记忆卡片
  const renderMemoryCard = (annotation: MemoryAnnotation) => {
    const config = TYPE_CONFIG[annotation.type];
    const isActive = activeAnnotationId === annotation.id;
    return (
      <div
        key={annotation.id}
        ref={(el) => { cardRefs.current[annotation.id] = el; }}
        onClick={() => onAnnotationClick?.(annotation)}
        className={cn('hh-subpanel mb-2 cursor-pointer border-l-4 p-3 transition-colors hover:border-brand/40', isActive && 'ring-1 ring-brand/30')}
        style={{ borderLeftColor: config.color, backgroundColor: isActive ? `${config.color}11` : undefined }}
      >
        <div className="mb-1.5 flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-content">
            <config.Icon className="h-3.5 w-3.5 shrink-0" style={{ color: config.color }} />
            <span className="truncate">{annotation.title}</span>
          </div>
          <span className="shrink-0 px-1.5 py-px text-[11px] font-semibold text-white tabular-nums" style={{ backgroundColor: config.color }}>
            {(annotation.importance * 10).toFixed(1)}
          </span>
        </div>
        <p className="mb-1.5 text-[13px] leading-relaxed text-content-secondary">
          {annotation.content.length > 100 ? `${annotation.content.slice(0, 100)}...` : annotation.content}
        </p>
        {annotation.tags && annotation.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {annotation.tags.map((tag, index) => <Pill key={index}>{tag}</Pill>)}
          </div>
        )}
        {/* 特殊元数据 */}
        {annotation.metadata.strength && <p className="mt-1 text-[11px] text-content-tertiary">强度: {annotation.metadata.strength}/10</p>}
        {annotation.metadata.foreshadowType && (
          <Pill tone={annotation.metadata.foreshadowType === 'planted' ? 'brand' : 'green'} className="mt-1">
            {annotation.metadata.foreshadowType === 'planted' ? '已埋下' : '已回收'}
          </Pill>
        )}
      </div>
    );
  };

  return (
    <div className="h-full overflow-y-auto">
      {/* 统计概览 */}
      <div className="hh-subpanel mb-3 p-3">
        <p className="mb-2 text-sm font-semibold text-content">分析概览</p>
        <div className="grid grid-cols-2 gap-2">
          {(Object.keys(TYPE_CONFIG) as MemoryAnnotation['type'][]).map((type) => (
            <div key={type}>
              <p className="text-xs text-content-tertiary">{TYPE_CONFIG[type].label}</p>
              <p className="text-xl font-semibold tabular-nums" style={{ color: TYPE_CONFIG[type].color }}>{groupedAnnotations[type].length}</p>
            </div>
          ))}
        </div>
      </div>

      {/* 分类展示（角色事件默认收起） */}
      {(Object.keys(groupedAnnotations) as MemoryAnnotation['type'][]).map((type) => {
        const items = groupedAnnotations[type];
        if (items.length === 0) return null;
        const config = TYPE_CONFIG[type];
        return (
          <CollapseSection
            key={type}
            defaultOpen={type !== 'character_event'}
            count={items.length}
            title={<><config.Icon className="h-3.5 w-3.5" style={{ color: config.color }} />{config.label}</>}
          >
            {items.map(renderMemoryCard)}
          </CollapseSection>
        );
      })}
    </div>
  );
};

export default MemorySidebar;
