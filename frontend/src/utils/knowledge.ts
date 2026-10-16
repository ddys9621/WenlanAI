/** 知识库纯函数：条目类型顺序与显示名（与后端 entry_types.py 的排序一致）、分组、章号范围、书架计数；
 * 仿写参考：仿写方式、场景名、引用文案、对标书分卷与已拆范围。 */
import type {
  KbCitation, KbEntrySummary, KbEntryType, KbMode, KbProjectLink, KbScene, KbSource, KbSourceChoice, KbSourceVolume,
} from '@/types/knowledge';

export const ENTRY_TYPE_ORDER: KbEntryType[] = [
  'guide', 'synopsis', 'characters', 'methodology', 'structure', 'style', 'excerpt', 'volume', 'arc', 'chapter',
];

export const ENTRY_TYPE_LABEL: Record<KbEntryType, string> = {
  guide: '导读',
  synopsis: '全书骨架',
  characters: '人物功能谱',
  methodology: '写法手册',
  structure: '结构统计',
  style: '文风',
  excerpt: '典型片段',
  volume: '分卷',
  arc: '剧情单元',
  chapter: '章卡',
};

export interface KbEntryGroup {
  type: KbEntryType;
  label: string;
  items: KbEntrySummary[];
}

export function groupEntries(entries: KbEntrySummary[]): KbEntryGroup[] {
  const byType = new Map<KbEntryType, KbEntrySummary[]>();
  for (const entry of entries) {
    const list = byType.get(entry.entry_type) ?? [];
    list.push(entry);
    byType.set(entry.entry_type, list);
  }
  return ENTRY_TYPE_ORDER.filter((t) => byType.has(t)).map((t) => ({
    type: t,
    label: ENTRY_TYPE_LABEL[t],
    items: byType.get(t) ?? [],
  }));
}

export function entryRangeLabel(entry: Pick<KbEntrySummary, 'chapter_start' | 'chapter_end'>): string {
  if (entry.chapter_start == null) return '';
  if (entry.chapter_end == null || entry.chapter_end === entry.chapter_start) return `第${entry.chapter_start}章`;
  return `第${entry.chapter_start}-${entry.chapter_end}章`;
}

export function sourceCountsLine(counts: KbSource['entry_counts']): string {
  return ENTRY_TYPE_ORDER.filter((t) => t !== 'guide' && (counts[t] ?? 0) > 0)
    .map((t) => `${ENTRY_TYPE_LABEL[t]} ${counts[t]}`)
    .join(' · ');
}

export const KB_MODE_OPTIONS: { value: KbMode; label: string; hint: string }[] = [
  { value: 'follow', label: '跟写结构', hint: '单元数、每个单元的作用 / 章数 / 强弱 / 兑现方式尽量和对标一致，内容全部按本书重写' },
  { value: 'borrow', label: '借鉴节奏', hint: '参考节奏、强弱交替和兑现方式，按本书需要增减调整' },
  { value: 'style', label: '只学文风', hint: '只在写正文时参考文风和同类片段，规划不受影响' },
  { value: 'off', label: '关闭', hint: '保留对标书，但生成时不注入' },
];

export function kbModeLabel(mode: string): string {
  return KB_MODE_OPTIONS.find((o) => o.value === mode)?.label ?? mode;
}

export const NO_KB_CHOICE: KbSourceChoice = { sourceId: '', mode: 'borrow' };

/** 向导建项目那一步的请求字段：没选对标书时不带 */
export function kbChoicePayload(choice?: KbSourceChoice): { kb_source_id?: string; kb_mode?: KbMode } {
  return choice?.sourceId ? { kb_source_id: choice.sourceId, kb_mode: choice.mode } : {};
}

/** 生成弹窗里「仿写参考」一行的文案（undefined = 还在读取） */
export function kbHintText(link: Pick<KbProjectLink, 'source_title' | 'mode'> | null | undefined): string {
  if (link === undefined) return '读取中…';
  if (!link) return '未设对标书';
  return link.mode === 'off' ? `《${link.source_title}》· 已关闭` : `《${link.source_title}》· ${kbModeLabel(link.mode)}`;
}

export const KB_SCENE_LABEL: Record<KbScene, string> = {
  worldview: '世界观',
  characters: '角色',
  story_outline: '总纲',
  volume_skeleton: '分卷',
  volume_detail: '细化卷纲',
  unit_outline: '单元章纲',
  chapter: '正文',
};

export function citationText(citation: Pick<KbCitation, 'label' | 'stale'>): string {
  return `对标：${citation.label}${citation.stale ? '（已过期）' : ''}`;
}

/** 剧情单元的引用目标：卷 id + 单元序号（与后端 knowledge_citations.target_id 一致） */
export function unitCitationKey(volumeId: string, unitIndex: number): string {
  return `${volumeId}:${unitIndex}`;
}

export function sourceVolumeLabel(volume: KbSourceVolume): string {
  return `${volume.title}（第${volume.chapter_start}-${volume.chapter_end}章）`;
}

export function dissectedRangeLabel(link: Pick<KbProjectLink, 'dissected_range' | 'source_chapter_count'>): string {
  if (!link.dissected_range) return '';
  const [first, last] = link.dissected_range;
  if (last - first + 1 >= link.source_chapter_count) return `已拆完全书 ${link.source_chapter_count} 章`;
  return `已拆第${first}-${last}章（原书共 ${link.source_chapter_count} 章）`;
}
