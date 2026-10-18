import type { Ref } from 'react';
import { Eye, EyeOff, Loader2, RotateCcw, Save, TriangleAlert, Undo2 } from 'lucide-react';

import type { ProjectPromptItem } from '@/types/prompts';
import { unknownVariables } from '@/utils/projectPrompts';

export interface PromptEditorProps {
  item: ProjectPromptItem;
  draft: string;
  saving: boolean;
  showDefault: boolean;
  textareaRef?: Ref<HTMLTextAreaElement>;
  onDraftChange: (value: string) => void;
  onInsertVariable: (name: string) => void;
  onSave: () => void;
  onRevert: () => void;
  onReset: () => void;
  onToggleDefault: () => void;
}

export function PromptEditor({
  item, draft, saving, showDefault, textareaRef,
  onDraftChange, onInsertVariable, onSave, onRevert, onReset, onToggleDefault,
}: PromptEditorProps) {
  const dirty = draft !== item.content;
  const unknown = unknownVariables(draft, item.variables.map((v) => v.name));
  const allowed = item.variables.length
    ? `这一条可用 ${item.variables.map((v) => `{${v.name}}`).join('、')}`
    : '这一条没有可用变量';

  return (
    <section className="hh-panel flex flex-col">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-border px-5 py-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold text-content">{item.title}</h2>
            {item.customized
              ? <span className="lj-badge lj-badge--ok">已自定义</span>
              : <span className="lj-badge lj-badge--muted">系统默认</span>}
          </div>
          <p className="mt-1.5 max-w-2xl text-[13px] leading-6 text-content-secondary">{item.description}</p>
        </div>
        {item.customized && (
          <button type="button" onClick={onToggleDefault} className="hh-btn-ghost hh-btn-sm">
            {showDefault ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            {showDefault ? '收起系统默认' : '查看系统默认'}
          </button>
        )}
      </header>

      {item.default_changed && (
        <div className="mx-5 mt-4 flex items-start gap-2 rounded border border-gold-300/40 bg-gold-50 px-3 py-2 text-xs leading-5 text-gold-500">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>系统默认已更新（版本升级，或本书换了类型 / 视角）：可以查看系统默认对照，需要时恢复默认。</span>
        </div>
      )}

      {item.variables.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 px-5 pt-4">
          <span className="text-xs text-content-tertiary">可用变量（点一下插入到光标处，生成时自动换成本书的值）：</span>
          {item.variables.map((v) => (
            <button key={v.name} type="button" onClick={() => onInsertVariable(v.name)} className="hh-chip" title={v.label}>
              <span className="font-mono">{`{${v.name}}`}</span>
              <span className="text-content-tertiary">{v.label}</span>
            </button>
          ))}
        </div>
      )}

      <div className="px-5 py-4">
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          spellCheck={false}
          aria-label={`${item.title}内容`}
          className="hh-textarea h-[52vh] min-h-[320px] resize-y rounded border border-surface-border font-mono text-[13px]"
        />
        {unknown.length > 0 && (
          <p className="mt-2 text-xs text-cinnabar">
            不认识的变量 {unknown.map((name) => `{${name}}`).join('、')}：{allowed}
          </p>
        )}
        {showDefault && item.customized && (
          <div className="mt-4">
            <p className="mb-1.5 text-xs font-medium text-content-tertiary">系统默认</p>
            <pre className="hh-subpanel max-h-72 overflow-y-auto whitespace-pre-wrap p-3 font-mono text-xs leading-5 text-content-secondary">
              {item.default_content}
            </pre>
          </div>
        )}
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-border bg-surface-paper px-5 py-3">
        <p className="text-xs text-content-tertiary">
          {draft.trim().length} 字 · 输出格式、作品资料由系统自动附加，改这里不会让生成结果解析出错
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {item.customized && (
            <button type="button" onClick={onReset} disabled={saving} className="hh-btn-ghost hh-btn-sm">
              <RotateCcw className="h-3.5 w-3.5" />
              恢复默认
            </button>
          )}
          {dirty && (
            <button type="button" onClick={onRevert} disabled={saving} className="hh-btn-secondary hh-btn-sm">
              <Undo2 className="h-3.5 w-3.5" />
              撤销修改
            </button>
          )}
          <button type="button" onClick={onSave} disabled={!dirty || saving || unknown.length > 0} className="hh-btn-primary hh-btn-sm">
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            保存
          </button>
        </div>
      </footer>
    </section>
  );
}
