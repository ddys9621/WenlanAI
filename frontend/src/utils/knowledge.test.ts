import { describe, expect, it } from 'vitest';

import type { KbEntrySummary } from '@/types/knowledge';
import {
  citationText, dissectedRangeLabel, entryRangeLabel, groupEntries, kbChoicePayload, kbHintText, kbModeLabel,
  KB_MODE_OPTIONS, NO_KB_CHOICE, sourceCountsLine, sourceVolumeLabel, unitCitationKey,
} from './knowledge';

const e = (
  entry_type: KbEntrySummary['entry_type'],
  key: string,
  start: number | null = null,
  end: number | null = null,
): KbEntrySummary => ({
  id: key, source_id: 's', entry_key: key, entry_type, layer: 'fact', title: key, summary: '',
  chapter_start: start, chapter_end: end, volume_index: null, arc_index: null,
  origin: 'generated', status: 'unreviewed', upstream_changed: false, revision: 1,
});

describe('knowledge utils', () => {
  it('按固定类型顺序分组，空组不出现，组内保持原顺序', () => {
    const groups = groupEntries([e('chapter', 'chapter:1'), e('guide', 'guide'), e('arc', 'arc:1'), e('chapter', 'chapter:2')]);
    expect(groups.map((g) => g.type)).toEqual(['guide', 'arc', 'chapter']);
    expect(groups[2].items.map((x) => x.entry_key)).toEqual(['chapter:1', 'chapter:2']);
    expect(groups[1].label).toBe('剧情单元');
  });

  it('章号范围文案', () => {
    expect(entryRangeLabel(e('chapter', 'c', 3, 3))).toBe('第3章');
    expect(entryRangeLabel(e('arc', 'a', 3, 7))).toBe('第3-7章');
    expect(entryRangeLabel(e('guide', 'g'))).toBe('');
  });

  it('书架条目数一行（不含导读）', () => {
    expect(sourceCountsLine({ guide: 1, chapter: 200, volume: 3, arc: 40 })).toBe('分卷 3 · 剧情单元 40 · 章卡 200');
    expect(sourceCountsLine({})).toBe('');
  });

  it('仿写方式：四档、默认借鉴节奏排第二、未知值原样显示', () => {
    expect(KB_MODE_OPTIONS.map((o) => o.value)).toEqual(['follow', 'borrow', 'style', 'off']);
    expect(kbModeLabel('borrow')).toBe('借鉴节奏');
    expect(kbModeLabel('wild')).toBe('wild');
  });

  it('向导建项目时的对标书字段：没选不带', () => {
    expect(kbChoicePayload(NO_KB_CHOICE)).toEqual({});
    expect(kbChoicePayload(undefined)).toEqual({});
    expect(kbChoicePayload({ sourceId: 's1', mode: 'follow' })).toEqual({ kb_source_id: 's1', kb_mode: 'follow' });
  });

  it('生成弹窗的仿写参考一行', () => {
    expect(kbHintText(undefined)).toBe('读取中…');
    expect(kbHintText(null)).toBe('未设对标书');
    expect(kbHintText({ source_title: '原书', mode: 'borrow' })).toBe('《原书》· 借鉴节奏');
    expect(kbHintText({ source_title: '原书', mode: 'off' })).toBe('《原书》· 已关闭');
  });

  it('引用文案与单元引用键', () => {
    expect(citationText({ label: '《原书》#1《入门》（第1-4章）', stale: false })).toBe('对标：《原书》#1《入门》（第1-4章）');
    expect(citationText({ label: '《原书》第3章《夜》', stale: true })).toBe('对标：《原书》第3章《夜》（已过期）');
    expect(unitCitationKey('v1', 2)).toBe('v1:2');
  });

  it('对标书的分卷与已拆范围文案', () => {
    expect(sourceVolumeLabel({ index: 1, title: '第1卷《外门》', chapter_start: 1, chapter_end: 4 })).toBe('第1卷《外门》（第1-4章）');
    expect(dissectedRangeLabel({ dissected_range: [1, 40], source_chapter_count: 1531 })).toBe('已拆第1-40章（原书共 1531 章）');
    expect(dissectedRangeLabel({ dissected_range: [1, 40], source_chapter_count: 40 })).toBe('已拆完全书 40 章');
    expect(dissectedRangeLabel({ dissected_range: null, source_chapter_count: 10 })).toBe('');
  });
});
