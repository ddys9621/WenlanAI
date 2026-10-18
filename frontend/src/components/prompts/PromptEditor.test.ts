import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { ProjectPromptItem } from '@/types/prompts';
import { PromptEditor, type PromptEditorProps } from './PromptEditor';

/** 提示词编辑区：服务端渲染冒烟（无 jsdom，只验证关键内容与按钮状态） */
const style: ProjectPromptItem = {
  key: 'chapter_style', group: 'chapter', title: '文风规则', description: '决定成稿的段落、对话、口吻和用词。',
  variables: [{ name: 'narrative_perspective', label: '本书叙事视角' }],
  default_content: '默认文风全文', content: '我的文风', customized: true, default_changed: false,
  updated_at: '2026-10-16T08:00:00',
};

const noop = () => {};

function render(overrides: Partial<PromptEditorProps> = {}) {
  return renderToStaticMarkup(h(PromptEditor, {
    item: style, draft: style.content, saving: false, showDefault: false,
    onDraftChange: noop, onInsertVariable: noop, onSave: noop, onRevert: noop, onReset: noop, onToggleDefault: noop,
    ...overrides,
  }));
}

describe('PromptEditor', () => {
  it('显示说明、变量标签与当前内容；改过的条目可以恢复默认', () => {
    const html = render();
    expect(html).toContain('文风规则');
    expect(html).toContain('决定成稿的段落');
    expect(html).toContain('{narrative_perspective}');
    expect(html).toContain('本书叙事视角');
    expect(html).toContain('我的文风');
    expect(html).toContain('已自定义');
    expect(html).toContain('恢复默认');
    expect(html).toContain('输出格式');
  });

  it('没改过的条目不显示恢复默认，内容没变时保存按钮不可点', () => {
    const fresh = { ...style, customized: false, content: style.default_content, updated_at: null };
    const html = render({ item: fresh, draft: fresh.content });
    expect(html).toContain('系统默认');
    expect(html).not.toContain('恢复默认');
    expect(html).not.toContain('撤销修改');
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>[^<]*(<svg[\s\S]*?<\/svg>)?\s*保存/);
  });

  it('有未保存的修改时可以撤销；写错变量名时提示并禁止保存', () => {
    const dirty = render({ draft: '我的文风，第 {titel} 章' });
    expect(dirty).toContain('撤销修改');
    expect(dirty).toContain('不认识的变量 {titel}');
    expect(dirty).toMatch(/<button[^>]*disabled=""[^>]*>[^<]*(<svg[\s\S]*?<\/svg>)?\s*保存/);

    const ok = render({ draft: '我的文风，{narrative_perspective}' });
    expect(ok).not.toContain('不认识的变量');
    expect(ok).not.toMatch(/<button[^>]*disabled=""[^>]*>[^<]*(<svg[\s\S]*?<\/svg>)?\s*保存/);
  });

  it('系统默认更新过时提醒，并能展开查看默认原文', () => {
    const html = render({ item: { ...style, default_changed: true }, showDefault: true });
    expect(html).toContain('系统默认已更新');
    expect(html).toContain('默认文风全文');
  });
});
