import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { KbEntry } from '@/types/knowledge';
import { EntryView } from './EntryView';

/** 条目阅读视图：服务端渲染冒烟（无 jsdom，只验证不抛 + 关键内容在场） */
const entry: KbEntry = {
  id: 'e1', source_id: 's1', entry_key: 'arc:1', entry_type: 'arc', layer: 'fact', title: '#1《入门》',
  summary: '成长突破·4章', chapter_start: 1, chapter_end: 4, volume_index: 1, arc_index: 1,
  origin: 'author', status: 'confirmed', upstream_changed: true, revision: 2,
  body: '林七入门', denamed_body: '【主角】入门', data: {}, tags: [], position: 0.5,
};

describe('EntryView', () => {
  it('原名版显示 body 与状态徽章', () => {
    const html = renderToStaticMarkup(h(EntryView, { entry, mode: 'named' }));
    expect(html).toContain('林七入门');
    expect(html).toContain('第1-4章');
    expect(html).toContain('作者已改');
    expect(html).toContain('已核对');
    expect(html).toContain('拆书结果已更新');
  });

  it('去名版显示 denamed_body', () => {
    const html = renderToStaticMarkup(h(EntryView, { entry, mode: 'denamed' }));
    expect(html).toContain('【主角】入门');
    expect(html).not.toContain('林七入门');
  });
});
