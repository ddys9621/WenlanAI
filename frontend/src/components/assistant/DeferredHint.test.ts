import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { DeferredHint } from './CocreationParts';

const base = { message_id: 'm1', label: '生成2 个人物', pending: 3, total: 4, ready: false };

describe('DeferredHint', () => {
  it('还有卡没处理：说清处理完会接着做什么，不给按钮', () => {
    const html = renderToStaticMarkup(h(DeferredHint, { deferred: base, onContinue: () => {} }));
    expect(html).toContain('处理完待确认的 3 张卡，团队会接着');
    expect(html).toContain('生成2 个人物');
    expect(html).not.toContain('接着做</button>');
  });

  it('都处理完了（在别处处理的）：给一个接着做的按钮', () => {
    const html = renderToStaticMarkup(h(DeferredHint, { deferred: { ...base, pending: 0, ready: true }, onContinue: () => {} }));
    expect(html).toContain('上游卡片处理好了');
    expect(html).toContain('接着做</button>');
  });
});
