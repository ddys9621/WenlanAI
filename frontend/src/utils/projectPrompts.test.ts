import { describe, expect, it } from 'vitest';

import type { ProjectPromptGroup, ProjectPromptItem } from '@/types/prompts';
import { countCustomized, groupPrompts, insertAt, unknownVariables } from './projectPrompts';

function item(key: string, group: string, customized = false): ProjectPromptItem {
  return {
    key, group, title: key, description: '', variables: [], default_content: '默认', content: customized ? '改过' : '默认',
    customized, default_changed: false, updated_at: null,
  };
}

describe('unknownVariables', () => {
  it('只认登记过的英文变量；中文花括号、JSON 示例不算', () => {
    expect(unknownVariables('第 {start}-{ennd} 章，{主角}，{"a": 1}', ['start', 'end'])).toEqual(['ennd']);
    expect(unknownVariables('{x}{x}{y}', [])).toEqual(['x', 'y']);
    expect(unknownVariables('没有变量', [])).toEqual([]);
  });
});

describe('insertAt', () => {
  it('替换选区并把光标放到插入内容之后', () => {
    expect(insertAt('用写', 1, 1, '{narrative_perspective}')).toEqual({ text: '用{narrative_perspective}写', caret: 24 });
    expect(insertAt('abcdef', 1, 4, 'X')).toEqual({ text: 'aXef', caret: 2 });
  });
});

describe('groupPrompts', () => {
  it('按分组顺序归类，没有条目的分组不出现', () => {
    const groups: ProjectPromptGroup[] = [
      { id: 'chapter', title: '正文写作', description: '' },
      { id: 'empty', title: '空', description: '' },
      { id: 'planning', title: '规划', description: '' },
    ];
    const result = groupPrompts(groups, [item('a', 'planning'), item('b', 'chapter'), item('c', 'planning')]);
    expect(result.map((g) => [g.group.id, g.items.map((i) => i.key)])).toEqual([
      ['chapter', ['b']],
      ['planning', ['a', 'c']],
    ]);
  });
});

describe('countCustomized', () => {
  it('数出改过的条目', () => {
    expect(countCustomized([item('a', 'x', true), item('b', 'x'), item('c', 'x', true)])).toBe(2);
  });
});
