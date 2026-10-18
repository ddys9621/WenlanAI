/**
 * 项目提示词：按本项目改写 AI 的写作指导（正文写作 + 总纲 / 卷纲 / 章纲的写法），单条或全部恢复默认。
 * 只开放最影响成稿的几段；输出格式、作品资料由后端自动附加，作者怎么改都不会让生成结果解析出错。
 */
import { useEffect, useRef, useState } from 'react';
import { Loader2, RotateCcw, ScrollText } from 'lucide-react';
import { toast } from 'sonner';

import { PromptEditor } from '@/components/prompts/PromptEditor';
import { PromptList } from '@/components/prompts/PromptList';
import { projectPromptApi } from '@/services/api';
import { useStore } from '@/store/index';
import type { ProjectPromptGroup, ProjectPromptItem } from '@/types/prompts';
import { countCustomized, insertAt } from '@/utils/projectPrompts';

export default function ProjectPrompts() {
  const { currentProject } = useStore();
  const projectId = currentProject?.id;
  const [groups, setGroups] = useState<ProjectPromptGroup[]>([]);
  const [items, setItems] = useState<ProjectPromptItem[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showDefault, setShowDefault] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const selected = items.find((item) => item.key === selectedKey) ?? null;
  const dirty = selected !== null && draft !== selected.content;
  const customizedCount = countCustomized(items);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    projectPromptApi
      .list(projectId)
      .then((res) => {
        if (cancelled) return;
        setGroups(res.groups);
        setItems(res.items);
        setSelectedKey(res.items[0]?.key ?? null);
        setDraft(res.items[0]?.content ?? '');
        setShowDefault(false);
      })
      .catch(() => { /* api 层已 toast */ })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const replaceItem = (next: ProjectPromptItem) => setItems((prev) => prev.map((item) => (item.key === next.key ? next : item)));

  const select = (key: string) => {
    if (key === selectedKey) return;
    if (dirty && !confirm('当前条目还有没保存的修改，放弃修改并切换？')) return;
    setSelectedKey(key);
    setDraft(items.find((item) => item.key === key)?.content ?? '');
    setShowDefault(false);
  };

  const save = async () => {
    if (!projectId || !selected) return;
    setSaving(true);
    try {
      const saved = await projectPromptApi.save(projectId, selected.key, draft);
      replaceItem(saved);
      if (saved.content !== draft.trim()) {
        toast.error('保存没有生效，请再保存一次');
        return;
      }
      setDraft(saved.content);
      toast.success(saved.customized ? '已保存，之后的生成按新的提示词来' : '和系统默认一致，按默认处理');
    } catch {
      /* api 层已 toast */
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    if (!projectId || !selected) return;
    if (!confirm(`把「${selected.title}」恢复成系统默认？你的修改会丢掉。`)) return;
    setSaving(true);
    try {
      const restored = await projectPromptApi.reset(projectId, selected.key);
      replaceItem(restored);
      setDraft(restored.content);
      setShowDefault(false);
      toast.success('已恢复系统默认');
    } catch {
      /* api 层已 toast */
    } finally {
      setSaving(false);
    }
  };

  const resetAll = async () => {
    if (!projectId) return;
    if (!confirm(`把本项目改过的 ${customizedCount} 条提示词全部恢复成系统默认？`)) return;
    setSaving(true);
    try {
      const res = await projectPromptApi.resetAll(projectId);
      setItems(res.items);
      setDraft(res.items.find((item) => item.key === selectedKey)?.content ?? '');
      setShowDefault(false);
      toast.success(`已把 ${res.reset} 条恢复成系统默认`);
    } catch {
      /* api 层已 toast */
    } finally {
      setSaving(false);
    }
  };

  const insertVariable = (name: string) => {
    const el = textareaRef.current;
    const { text, caret } = insertAt(draft, el?.selectionStart ?? draft.length, el?.selectionEnd ?? draft.length, `{${name}}`);
    setDraft(text);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(caret, caret);
    });
  };

  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">提示词</h1>
          <p className="lj-page-desc">
            按本书改写 AI 的写作指导，只影响这个项目。这里只开放最影响成稿的几段；输出格式、作品资料由系统自动附加，怎么改都不会让生成结果解析出错。
          </p>
        </div>
        <div className="lj-page-actions">
          <button type="button" onClick={resetAll} disabled={saving || customizedCount === 0} className="hh-btn-secondary">
            <RotateCcw className="h-4 w-4" />
            全部恢复默认{customizedCount > 0 ? `（${customizedCount}）` : ''}
          </button>
        </div>
      </section>

      {loading ? (
        <section className="hh-panel flex items-center justify-center py-14">
          <Loader2 className="h-6 w-6 animate-spin text-brand" />
        </section>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <PromptList groups={groups} items={items} selectedKey={selectedKey} onSelect={select} />
          {selected ? (
            <PromptEditor
              item={selected}
              draft={draft}
              saving={saving}
              showDefault={showDefault}
              textareaRef={textareaRef}
              onDraftChange={setDraft}
              onInsertVariable={insertVariable}
              onSave={save}
              onRevert={() => setDraft(selected.content)}
              onReset={reset}
              onToggleDefault={() => setShowDefault((v) => !v)}
            />
          ) : (
            <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
              <ScrollText className="h-7 w-7 text-brand" />
              <p className="mt-3 text-sm text-content-secondary">选择左侧的一条提示词查看和修改</p>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
