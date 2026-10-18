import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { ProjectPromptGroup, ProjectPromptItem } from '@/types/prompts';
import { PromptList } from './PromptList';

const groups: ProjectPromptGroup[] = [
  { id: 'chapter', title: '正文写作', description: '单章与批量写作时给 AI 的写作指导。' },
  { id: 'planning', title: '规划（总纲 → 卷纲 → 章纲）', description: '' },
];

function item(key: string, title: string, group: string, extra: Partial<ProjectPromptItem> = {}): ProjectPromptItem {
  return {
    key, group, title, description: `${title}说明`, variables: [], default_content: '默认', content: '默认',
    customized: false, default_changed: false, updated_at: null, ...extra,
  };
}

describe('PromptList', () => {
  it('按分组列出条目，标出改过的、默认已更新的和当前选中的', () => {
    const items = [
      item('chapter_persona', '写作人设', 'chapter', { customized: true, content: '改过' }),
      item('chapter_style', '文风规则', 'chapter', { customized: true, default_changed: true, content: '改过' }),
      item('volume_skeleton', '分卷写法', 'planning'),
    ];
    const html = renderToStaticMarkup(h(PromptList, { groups, items, selectedKey: 'chapter_style', onSelect: () => {} }));
    expect(html).toContain('正文写作');
    expect(html).toContain('规划（总纲 → 卷纲 → 章纲）');
    expect(html).toContain('写作人设');
    expect(html).toContain('分卷写法');
    expect(html.match(/已改/g)?.length).toBe(2);
    expect(html).toContain('默认已更新');
    expect(html).toMatch(/lj-selected[^>]*>[\s\S]*?文风规则/);
  });
});
