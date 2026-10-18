import { cn } from '@/lib/utils';
import type { ProjectPromptGroup, ProjectPromptItem } from '@/types/prompts';
import { groupPrompts } from '@/utils/projectPrompts';

interface PromptListProps {
  groups: ProjectPromptGroup[];
  items: ProjectPromptItem[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
}

export function PromptList({ groups, items, selectedKey, onSelect }: PromptListProps) {
  return (
    <nav className="hh-panel overflow-hidden" aria-label="提示词条目">
      {groupPrompts(groups, items).map(({ group, items: groupItems }) => (
        <section key={group.id} className="border-b border-surface-border last:border-b-0">
          <h2 className="px-4 pb-1.5 pt-3 text-xs font-semibold text-content-tertiary">{group.title}</h2>
          <ul className="pb-2">
            {groupItems.map((item) => (
              <li key={item.key}>
                <button
                  type="button"
                  onClick={() => onSelect(item.key)}
                  className={cn(
                    'flex w-full items-start justify-between gap-2 px-4 py-2 text-left hover:bg-surface-hover',
                    item.key === selectedKey && 'lj-selected',
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-content">{item.title}</span>
                    <span className="mt-0.5 block truncate text-xs text-content-tertiary">{item.description}</span>
                  </span>
                  <span className="flex shrink-0 flex-col items-end gap-1">
                    {item.customized && <span className="lj-badge lj-badge--ok">已改</span>}
                    {item.default_changed && <span className="lj-badge lj-badge--draft">默认已更新</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </nav>
  );
}
