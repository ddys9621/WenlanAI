/**
 * 地图右侧检查器：地点列表 / 故事地点原文 两个界面 + 地点档案（档案文字、类型、区域、绑定的原文地点、按章节的出处）。
 * 原文地点只做精确绑定，不按子串或相似名字猜；删除地点只删地图标注，不动故事内容。
 * 世界规则「地图位置」自动在这里出现（标「规则」，改名同步规则、要到规则页删）；没登记的地点可单个 / 全部登记成规则。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { mergeUntouched } from '@/utils/draftMerge';
import { ArrowLeft, Link2, Loader2, MapPin, Plus, ScrollText, Search, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { worldMapApi } from '@/services/api';
import type { MapLocation, MapLocationDossier, MapLocationKind, StoryLocation } from '@/types/writing';
import { KIND_LABELS, matchLocations, type LocationDraft } from '@/utils/worldMap';

interface LocationInspectorProps {
  projectId: string;
  locations: MapLocation[];
  storyLocations: StoryLocation[];
  drafts: LocationDraft[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onStartPlacing: (location: MapLocation) => void;
  /** 地点增删改后重新读取（保留本地未保存的坐标） */
  onChanged: () => Promise<void>;
}

const SOURCE_LABELS: Record<string, string> = { timeline: '事件', signal: '人物行踪', outline: '章纲场景', setting: '作品设定' };

export function LocationInspector({
  projectId, locations, storyLocations, drafts, selectedId, onSelect, onStartPlacing, onChanged,
}: LocationInspectorProps) {
  const [tab, setTab] = useState<'places' | 'story'>('places');
  const [query, setQuery] = useState('');
  const selected = locations.find((l) => l.id === selectedId) ?? null;
  const draftById = useMemo(() => new Map(drafts.map((d) => [d.id, d])), [drafts]);
  const list = matchLocations(locations, query).sort((a, b) => Number(draftById.get(a.id)?.unplaced) - Number(draftById.get(b.id)?.unplaced));
  const unregistered = locations.filter((l) => !l.rule_id);

  const register = async (ids?: string[]) => {
    try {
      await worldMapApi.registerRules(projectId, ids);
      await onChanged();
      return true;
    } catch {
      return false;
    }
  };

  const registerAll = async () => {
    const count = unregistered.length;
    if (!window.confirm(`把 ${count} 个未登记的地点都登记为世界规则「地图位置」？写作时会作为设定参考，之后可在世界规则页修改。`)) return;
    if (await register()) toast.success(`已把 ${count} 个地点登记到世界规则`);
  };

  const createFromName = async (name: string, sources: string[] = []) => {
    try {
      const created = await worldMapApi.createLocation(projectId, { name, source_names: sources });
      await onChanged();
      onSelect(created.id);
      setTab('places');
      return created;
    } catch {
      return null;
    }
  };

  const addLocation = async () => {
    const name = window.prompt('新地点的名字')?.trim();
    if (!name) return;
    const created = await createFromName(name);
    if (created) onStartPlacing(created);
  };

  const bindToSelected = async (raw: string) => {
    if (!selected) return;
    try {
      await worldMapApi.updateLocation(projectId, selected.id, { source_names: [...selected.source_names, raw] });
      await onChanged();
      toast.success(`已把「${raw}」绑定到「${selected.name}」`);
    } catch { /* 已 toast */ }
  };

  if (selected && tab === 'places') {
    return (
      <LocationDossier
        key={selected.id}
        projectId={projectId}
        location={selected}
        unplaced={draftById.get(selected.id)?.unplaced ?? true}
        storyLocations={storyLocations}
        onBack={() => onSelect(null)}
        onStartPlacing={() => onStartPlacing(selected)}
        onRegister={() => register([selected.id])}
        onChanged={onChanged}
        onDeleted={async () => { onSelect(null); await onChanged(); }}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="lj-pane-title">
        <div className="flex gap-1">
          {([['places', `地点 ${locations.length}`], ['story', `故事地点 ${storyLocations.length}`]] as const).map(([key, label]) => (
            <button key={key} onClick={() => setTab(key)} className={cn('hh-chip px-2.5 py-1 text-xs', tab === key && 'hh-chip--active')}>
              {label}
            </button>
          ))}
        </div>
        {tab === 'places' && (
          <button onClick={() => void addLocation()} className="hh-btn-ghost hh-btn-sm h-7 px-2" title="新建地点">
            <Plus className="h-3.5 w-3.5" />新建
          </button>
        )}
      </div>

      {tab === 'places' ? (
        <>
          <label className="mx-3 mt-3 flex items-center gap-2 rounded border border-surface-border bg-white px-2.5">
            <Search className="h-3.5 w-3.5 text-content-tertiary" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜地点名 / 区域 / 原文地点"
              className="h-8 w-full !border-0 !bg-transparent px-0 text-xs !shadow-none focus:!shadow-none"
            />
          </label>
          {unregistered.length > 0 && (
            <div className="mx-3 mt-2 flex items-center justify-between gap-2 rounded border border-surface-border-light bg-surface-paper px-2.5 py-1.5 text-[11px] text-content-secondary">
              <span>{unregistered.length} 个地点还没登记到世界规则</span>
              <button onClick={() => void registerAll()} className="hh-chip shrink-0 px-2 py-0.5 text-[11px]">
                <ScrollText className="h-3 w-3" />全部登记
              </button>
            </div>
          )}
          <ul className="mt-2 min-h-0 flex-1 divide-y divide-surface-border-light overflow-y-auto">
            {list.length === 0 && (
              <li className="px-4 py-8 text-center text-xs leading-5 text-content-tertiary">
                {locations.length === 0 ? '还没有地点：世界规则里的「地图位置」会自动出现在这里；也可以点「AI 生成布局」，或在「故事地点」里逐个建。' : '没有匹配的地点'}
              </li>
            )}
            {list.map((l) => {
              const unplaced = draftById.get(l.id)?.unplaced ?? true;
              return (
                <li key={l.id}>
                  <button onClick={() => onSelect(l.id)} className="flex w-full items-start gap-2 px-4 py-2.5 text-left hover:bg-surface-hover">
                    <MapPin className={cn('mt-0.5 h-3.5 w-3.5 shrink-0', unplaced ? 'text-content-tertiary' : 'text-[#E13E20]')} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-sm font-medium text-content">{l.name}</span>
                        <span className="text-[11px] text-content-tertiary">{KIND_LABELS[l.kind]}</span>
                        {l.rule_id && <span className="lj-badge lj-badge--ok" title="世界规则里的地点">规则</span>}
                        {unplaced && <span className="lj-badge lj-badge--muted">未定位</span>}
                        {l.origin === 'ai' && <span className="lj-badge lj-badge--candidate">AI</span>}
                      </span>
                      {(l.region || l.description) && (
                        <span className="mt-0.5 line-clamp-1 block text-[11px] text-content-tertiary">{[l.region, l.description].filter(Boolean).join(' · ')}</span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <ul className="min-h-0 flex-1 divide-y divide-surface-border-light overflow-y-auto">
          <li className="px-4 py-2.5 text-[11px] leading-5 text-content-tertiary">
            从时间轴事件、人物行踪、章纲场景和作品设定里按原文收集的地点。只做精确绑定：同一处的不同写法要手动绑到同一个地点。
          </li>
          {storyLocations.length === 0 && <li className="px-4 py-8 text-center text-xs text-content-tertiary">还没有故事地点：分析过的章节越多，这里越全。</li>}
          {storyLocations.map((s) => {
            const owner = locations.find((l) => l.id === s.bound_to);
            return (
              <li key={s.name} className="px-4 py-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate text-sm text-content">{s.name}</span>
                  <span className="shrink-0 text-[11px] tabular-nums text-content-tertiary">
                    {s.mentions} 次{s.first_chapter ? ` · 第 ${s.first_chapter} 章起` : ''}
                  </span>
                </div>
                <p className="mt-0.5 text-[11px] text-content-tertiary">{s.sources.map((k) => SOURCE_LABELS[k] ?? k).join(' / ')}</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {owner ? (
                    <button onClick={() => { onSelect(owner.id); setTab('places'); }} className="lj-badge lj-badge--ok">
                      <Link2 className="h-3 w-3" />已绑定：{owner.name}
                    </button>
                  ) : (
                    <>
                      <button onClick={() => void createFromName(s.name, [s.name])} className="hh-chip px-2 py-0.5 text-[11px]">
                        <Plus className="h-3 w-3" />建为地点
                      </button>
                      {selected && (
                        <button onClick={() => void bindToSelected(s.name)} className="hh-chip px-2 py-0.5 text-[11px]">
                          <Link2 className="h-3 w-3" />绑定到「{selected.name}」
                        </button>
                      )}
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function LocationDossier({
  projectId, location, unplaced, storyLocations, onBack, onStartPlacing, onRegister, onChanged, onDeleted,
}: {
  projectId: string;
  location: MapLocation;
  unplaced: boolean;
  storyLocations: StoryLocation[];
  onBack: () => void;
  onStartPlacing: () => void;
  /** 登记为世界规则「地图位置」；成功返回 true */
  onRegister: () => Promise<boolean>;
  onChanged: () => Promise<void>;
  onDeleted: () => Promise<void>;
}) {
  const formOf = (l: MapLocation) => ({
    name: l.name, kind: l.kind, region: l.region ?? '', description: l.description ?? '', source_names: l.source_names,
  });
  const [form, setForm] = useState(() => formOf(location));
  const [dossier, setDossier] = useState<MapLocationDossier | null>(null);
  const [saving, setSaving] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [addSource, setAddSource] = useState('');

  // 地点数据刷新（如智能助笔应用了修改）：只更新作者没动过的字段，正在填的不被冲掉
  const baseRef = useRef(formOf(location));
  useEffect(() => {
    const next = { name: location.name, kind: location.kind, region: location.region ?? '', description: location.description ?? '', source_names: location.source_names };
    const base = baseRef.current;
    baseRef.current = next;
    setForm((prev) => mergeUntouched(prev, base, next));
  }, [location.name, location.kind, location.region, location.description, location.source_names]);

  useEffect(() => {
    let cancelled = false;
    worldMapApi.dossier(projectId, location.id).then((d) => { if (!cancelled) setDossier(d); }).catch(() => {});
    return () => { cancelled = true; };
  }, [projectId, location.id, location.source_names, location.rule_id]);

  const dirty = form.name !== location.name || form.kind !== location.kind || form.region !== (location.region ?? '')
    || form.description !== (location.description ?? '') || form.source_names.join('\n') !== location.source_names.join('\n');
  const candidates = storyLocations.filter((s) => !form.source_names.includes(s.name));

  const save = async () => {
    if (!form.name.trim()) { toast.error('地点名不能为空'); return; }
    setSaving(true);
    try {
      await worldMapApi.updateLocation(projectId, location.id, {
        name: form.name.trim(), kind: form.kind, region: form.region.trim(), description: form.description, source_names: form.source_names,
      });
      await onChanged();
      toast.success('档案已保存');
    } catch { /* 已 toast */ } finally { setSaving(false); }
  };

  const clearPosition = async () => {
    try {
      await worldMapApi.updateLocation(projectId, location.id, { clear_position: true });
      await onChanged();
    } catch { /* 已 toast */ }
  };

  const remove = async () => {
    if (!window.confirm(`删除地点「${location.name}」？只删地图上的标注和档案，故事内容不受影响。`)) return;
    try {
      await worldMapApi.deleteLocation(projectId, location.id);
      toast.success('已删除');
      await onDeleted();
    } catch { /* 已 toast */ }
  };

  const register = async () => {
    setRegistering(true);
    if (await onRegister()) toast.success(`已把「${location.name}」登记到世界规则`);
    setRegistering(false);
  };

  const rule = dossier?.rule;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="lj-pane-title">
        <button onClick={onBack} className="flex items-center gap-1 text-xs font-medium text-content-secondary hover:text-content">
          <ArrowLeft className="h-3.5 w-3.5" />地点列表
        </button>
        <span className="flex items-center gap-1">
          {unplaced ? (
            <button onClick={onStartPlacing} className="hh-btn-secondary hh-btn-sm h-7 px-2"><MapPin className="h-3.5 w-3.5" />放到地图上</button>
          ) : (
            <button onClick={() => void clearPosition()} className="hh-btn-ghost hh-btn-sm h-7 px-2" title="从地图上拿下来（不删档案）">取消定位</button>
          )}
          <button
            onClick={() => void remove()}
            disabled={!!location.rule_id}
            title={location.rule_id ? '世界规则里的地点要到世界规则页删除；地图上可以取消定位' : '删除地点'}
            className="hh-icon-btn-plain h-7 w-7 hover:text-cinnabar disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="删除地点"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        <div>
          <label className="hh-label">
            地点名{location.rule_id && <span className="ml-1 font-normal text-content-tertiary">（改名会同步到世界规则）</span>}
          </label>
          <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className="hh-field h-9 font-serif" />
        </div>
        {location.rule_id ? (
          <div className="rounded border border-brand/20 bg-brand-50 px-3 py-2">
            <p className="flex items-center justify-between gap-2 text-xs font-medium text-content">
              <span className="flex items-center gap-1"><ScrollText className="h-3.5 w-3.5 text-brand" />世界规则设定</span>
              <Link to={`/project/${projectId}/world-rules`} className="text-[11px] font-normal text-brand hover:underline">去世界规则修改</Link>
            </p>
            {rule?.summary && <p className="mt-1 text-xs leading-5 text-content-secondary">{rule.summary}</p>}
            {rule?.details && <p className="mt-1 whitespace-pre-wrap text-[11px] leading-5 text-content-tertiary">{rule.details}</p>}
            {dossier && !rule?.summary && !rule?.details && <p className="mt-1 text-[11px] text-content-tertiary">规则里还没写简介和详情</p>}
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2 rounded border border-surface-border-light bg-surface-paper px-3 py-2 text-[11px] text-content-tertiary">
            <span>还没登记到世界规则</span>
            <button
              onClick={() => void register()}
              disabled={registering || dirty}
              title={dirty ? '先保存档案再登记' : '登记为世界规则「地图位置」，写作时作为设定参考'}
              className="hh-chip shrink-0 px-2 py-0.5 text-[11px]"
            >
              {registering ? <Loader2 className="h-3 w-3 animate-spin" /> : <ScrollText className="h-3 w-3" />}登记到世界规则
            </button>
          </div>
        )}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="hh-label">类型</label>
            <select value={form.kind} onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value as MapLocationKind }))} className="hh-field h-9">
              {(Object.keys(KIND_LABELS) as MapLocationKind[]).map((k) => <option key={k} value={k}>{KIND_LABELS[k]}</option>)}
            </select>
          </div>
          <div>
            <label className="hh-label">所属区域</label>
            <input value={form.region} onChange={(e) => setForm((f) => ({ ...f, region: e.target.value }))} className="hh-field h-9" />
          </div>
        </div>
        <div>
          <label className="hh-label">地点档案</label>
          <textarea
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            rows={4}
            placeholder="它在故事里是什么地方、谁在这里、有什么规矩……"
            className="hh-textarea text-[13px]"
          />
        </div>
        <div>
          <label className="hh-label">绑定的原文地点</label>
          <div className="flex flex-wrap gap-1.5">
            {form.source_names.length === 0 && <span className="text-[11px] text-content-tertiary">未绑定：档案只按地点名本身匹配出处</span>}
            {form.source_names.map((s) => (
              <span key={s} className="hh-tag">
                {s}
                <button onClick={() => setForm((f) => ({ ...f, source_names: f.source_names.filter((x) => x !== s) }))} className="text-brand/60 hover:text-cinnabar" aria-label={`解除绑定 ${s}`}>
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
          {candidates.length > 0 && (
            <div className="mt-2 flex gap-1.5">
              <select value={addSource} onChange={(e) => setAddSource(e.target.value)} className="hh-field h-8 flex-1 text-xs">
                <option value="">选一个故事里的原文地点…</option>
                {candidates.map((s) => (
                  <option key={s.name} value={s.name}>{s.name}（{s.mentions} 次）{s.bound_to ? ' · 已绑定别处' : ''}</option>
                ))}
              </select>
              <button
                onClick={() => { if (addSource) { setForm((f) => ({ ...f, source_names: [...f.source_names, addSource] })); setAddSource(''); } }}
                disabled={!addSource}
                className="hh-btn-secondary hh-btn-sm h-8"
              >
                绑定
              </button>
            </div>
          )}
        </div>
        {dirty && (
          <button onClick={() => void save()} disabled={saving} className="hh-btn-primary hh-btn-sm w-full">
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}保存档案
          </button>
        )}

        <div className="border-t border-surface-border-light pt-3">
          <p className="mb-1.5 text-xs font-medium text-content">故事里的出处（按章节顺序）</p>
          {!dossier ? (
            <Loader2 className="h-4 w-4 animate-spin text-brand" />
          ) : dossier.mentions.length === 0 ? (
            <p className="text-[11px] leading-5 text-content-tertiary">还没有找到出处：把故事里对应的原文地点绑定进来，或等更多章节分析后再看。</p>
          ) : (
            <ul className="space-y-1.5">
              {dossier.mentions.map((m, i) => (
                <li key={`${m.chapter_number}-${m.source}-${i}`} className="rounded border border-surface-border-light bg-surface-paper px-2.5 py-1.5 text-xs">
                  <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-content-tertiary">
                    <span className="font-medium text-content-secondary">第 {m.chapter_number} 章{m.chapter_title ? `《${m.chapter_title}》` : ''}</span>
                    <span>{SOURCE_LABELS[m.source] ?? m.source}</span>
                    {m.raw_location !== location.name && <span className="rounded-sm bg-surface-muted px-1">地点原文：{m.raw_location}</span>}
                  </p>
                  <p className="mt-0.5 leading-5 text-content">{m.text}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
