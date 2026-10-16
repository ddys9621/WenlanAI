// 记忆标注 → 正文片段 的纯函数切分逻辑（无 React 依赖，便于单独验证）

/** 标注类型：钩子 / 伏笔 / 关键转折（分析时记下原文引句，后端每次按当前正文重新定位） */
export const ANNOTATION_TYPES = ['hook', 'foreshadow', 'plot_point'] as const;
export type AnnotationType = (typeof ANNOTATION_TYPES)[number];

// 标注数据类型（GET /chapters/{id}/annotations）
export interface MemoryAnnotation {
  id: string;
  type: AnnotationType;
  title: string;
  /** 为什么值得标（分析说明） */
  content: string;
  importance: number;
  /** 引句在当前正文里的位置；找不到为 -1（侧栏照常列出，正文里不画） */
  position: number;
  length: number;
  tags: string[];
  metadata: {
    /** 分析时记下的原文引句 */
    quote?: string;
    [key: string]: unknown;
  };
}

/** 标注没有给出长度时默认标记的字符数 */
const DEFAULT_ANNOTATION_LENGTH = 30;

/** 一条标注在正文中对应的 [start, end) 区间 */
interface AnnotationSpan {
  annotation: MemoryAnnotation;
  start: number;
  end: number;
}

/** 正文被切成的片段：相邻两个标注边界之间的一段文字 */
export interface TextSegment {
  type: 'text' | 'annotated';
  start: number;
  content: string;
  /** 覆盖本片段的全部标注（按起点升序、重要性降序） */
  annotations: MemoryAnnotation[];
  /** 恰好从本片段开始的标注（用于挂 ref、画图标，保证每条标注只出现一次） */
  starting: MemoryAnnotation[];
}

function isAnnotationType(type: string): type is AnnotationType {
  return (ANNOTATION_TYPES as readonly string[]).includes(type);
}

/**
 * 把标注解析为正文区间：丢弃类型未知或位置不在正文范围内的标注，
 * 缺失长度时使用默认长度，末端裁剪到正文长度。
 */
export function resolveSpans(content: string, annotations: MemoryAnnotation[]): AnnotationSpan[] {
  const spans: AnnotationSpan[] = [];
  for (const annotation of annotations) {
    const { position, length } = annotation;
    if (!isAnnotationType(annotation.type)) continue;
    if (!(position >= 0 && position < content.length)) continue;
    const end = Math.min(content.length, position + (length > 0 ? length : DEFAULT_ANNOTATION_LENGTH));
    if (end <= position) continue;
    spans.push({ annotation, start: position, end });
  }
  return spans.sort(
    (a, b) => a.start - b.start || b.annotation.importance - a.annotation.importance || a.annotation.id.localeCompare(b.annotation.id)
  );
}

/**
 * 在所有标注的起止点处切分正文。
 * 每个正文字符恰好出现在一个片段里（重叠、嵌套、完全相同的标注区间都不会导致文字重复或错位），
 * 一个片段可能同时被多条标注覆盖。
 */
export function buildSegments(content: string, spans: AnnotationSpan[]): TextSegment[] {
  if (spans.length === 0) {
    return [{ type: 'text', start: 0, content, annotations: [], starting: [] }];
  }

  const boundaries = Array.from(
    new Set<number>([0, content.length, ...spans.flatMap((s) => [s.start, s.end])])
  ).sort((a, b) => a - b);

  const segments: TextSegment[] = [];
  for (let i = 0; i < boundaries.length - 1; i++) {
    const start = boundaries[i];
    const end = boundaries[i + 1];
    // 边界集合包含了每条标注的起止点，因此一条标注要么完整覆盖 [start, end)，要么与之不相交
    const covering = spans.filter((s) => s.start <= start && s.end >= end);
    const text = content.slice(start, end);
    const previous = segments[segments.length - 1];

    if (covering.length === 0) {
      if (previous && previous.type === 'text') {
        previous.content += text;
      } else {
        segments.push({ type: 'text', start, content: text, annotations: [], starting: [] });
      }
      continue;
    }

    segments.push({
      type: 'annotated',
      start,
      content: text,
      annotations: covering.map((s) => s.annotation),
      starting: covering.filter((s) => s.start === start).map((s) => s.annotation),
    });
  }
  return segments;
}
