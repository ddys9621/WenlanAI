/**
 * 项目的仿写参考：选一本对标书（来自知识库）和仿写方式，按卷指定对标关系，按场景预览生成时会注入什么。
 * 路由：/project/:projectId/knowledge（取代原「仿写参考包」挂载页）
 *
 * 生成时自动按位置对位：分卷 → 细化卷纲 → 单元章纲 → 正文，一层层沿用上一层的对标（设计稿第 6 节）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { BookMarked, Eye, Library, Loader2, Save, Unlink } from 'lucide-react';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { chapterOutlineApi, knowledgeApi, volumeApi } from '@/services/api';
import type { ChapterOutline, Volume } from '@/types';
import type { KbMode, KbPreview, KbProjectLink, KbScene, KbSource } from '@/types/knowledge';
import { dissectedRangeLabel, KB_MODE_OPTIONS, KB_SCENE_LABEL, sourceVolumeLabel } from '@/utils/knowledge';

const BTN =
  'inline-flex items-center gap-1.5 rounded-pill border border-surface-border bg-surface px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-hover disabled:opacity-50';
const BTN_PRIMARY =
  'inline-flex items-center gap-1.5 rounded-pill bg-brand px-3.5 py-1.5 text-xs font-medium text-white hover:bg-brand-600 disabled:opacity-50';
const SELECT = 'rounded-lg border border-surface-border bg-surface px-3 py-1.5 text-sm text-content';
const SCENES = Object.keys(KB_SCENE_LABEL) as KbScene[];

export default function ProjectKnowledgePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [sources, setSources] = useState<KbSource[]>([]);
  const [link, setLink] = useState<KbProjectLink | null>(null);
  const [volumes, setVolumes] = useState<Volume[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sourceId, setSourceId] = useState('');
  const [mode, setMode] = useState<KbMode>('borrow');
  const [volumeMap, setVolumeMap] = useState<Record<string, number>>({});

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const [allSources, current, volumeList] = await Promise.all([
        knowledgeApi.listSources(),
        knowledgeApi.getProjectLink(projectId),
        volumeApi.list(projectId),
      ]);
      setSources(allSources);
      setLink(current.link);
      setVolumes(volumeList.items ?? []);
      setSourceId(current.link?.source_id ?? '');
      setMode(current.link?.mode ?? 'borrow');
      setVolumeMap(current.link?.volume_map ?? {});
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '加载仿写参考失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!projectId || !sourceId) return;
    setSaving(true);
    try {
      const sameSource = link?.source_id === sourceId;
      const saved = await knowledgeApi.setProjectLink(projectId, {
        source_id: sourceId,
        mode,
        volume_map: sameSource ? volumeMap : {},
      });
      setLink(saved);
      setVolumeMap(saved.volume_map);
      toast.success('已保存：之后生成会按它注入仿写参考');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const unlink = async () => {
    if (!projectId || !link) return;
    if (!window.confirm(`取消对标《${link.source_title}》？之后生成不再注入仿写参考（知识库里的书不会被删除）。`)) return;
    try {
      await knowledgeApi.deleteProjectLink(projectId);
      setLink(null);
      setSourceId('');
      setMode('borrow');
      setVolumeMap({});
      toast.success('已取消对标');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '取消失败');
    }
  };

  if (!projectId) return null;

  const dirty = (link?.source_id ?? '') !== sourceId || (link?.mode ?? 'borrow') !== mode
    || JSON.stringify(link?.volume_map ?? {}) !== JSON.stringify(volumeMap);

  return (
    <div className="animate-fade-in space-y-6">
      <section className="lj-page-header">
        <div className="min-w-0">
          <h1 className="lj-page-title">仿写参考</h1>
          <p className="mt-2 max-w-[680px] text-sm leading-6 text-content-secondary">
            选一本知识库里的书做对标。分卷、细化卷纲、展开章纲、写正文时，会按本书的位置自动取原书对应的那一段（去掉人名的版本），
            学它的节奏和结构；本书的人物、设定和情节照常由你决定。
          </p>
        </div>
      </section>

      {loading ? (
        <div className="flex items-center justify-center rounded-2xl border border-surface-border bg-surface py-16 text-content-secondary">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载中...
        </div>
      ) : sources.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-surface-border bg-surface px-6 py-12 text-center">
          <Library className="mx-auto h-8 w-8 text-content-tertiary" />
          <p className="mt-2 text-base font-medium text-content">知识库还是空的</p>
          <p className="mt-1 text-sm text-content-secondary">先去拆一本书，拆完会自动收进知识库，再回来选它做对标。</p>
          <Link to="/book-dissect" className={cn(BTN_PRIMARY, 'mt-4')}>去拆书</Link>
        </div>
      ) : (
        <>
          <section className="space-y-4 rounded-2xl border border-surface-border bg-surface p-5">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm font-medium text-content">对标书</span>
              <select value={sourceId} onChange={(e) => setSourceId(e.target.value)} className={SELECT}>
                <option value="">不对标</option>
                {sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    《{s.title}》{s.genre ? ` · ${s.genre}` : ''}
                  </option>
                ))}
              </select>
              {link && link.source_id === sourceId && (
                <>
                  <span className="text-xs text-content-tertiary">{dissectedRangeLabel(link)}</span>
                  <Link to={`/knowledge/${link.source_id}`} className={BTN}>
                    <BookMarked className="h-3.5 w-3.5" />
                    在知识库打开
                  </Link>
                </>
              )}
            </div>

            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {KB_MODE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setMode(option.value)}
                  disabled={!sourceId}
                  className={cn(
                    'rounded-xl border px-3 py-2 text-left transition disabled:opacity-50',
                    mode === option.value ? 'border-brand bg-brand/10' : 'border-surface-border hover:bg-surface-hover',
                  )}
                >
                  <div className="text-sm font-medium text-content">{option.label}</div>
                  <div className="mt-0.5 text-xs leading-5 text-content-secondary">{option.hint}</div>
                </button>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => void save()} disabled={!sourceId || saving || !dirty} className={BTN_PRIMARY}>
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                保存
              </button>
              {link && (
                <button type="button" onClick={() => void unlink()} className={cn(BTN, 'hover:text-rose-300')}>
                  <Unlink className="h-3.5 w-3.5" />
                  取消对标
                </button>
              )}
            </div>
          </section>

          {link && link.source_id === sourceId && (
            <VolumeMapSection link={link} volumes={volumes} value={volumeMap} onChange={setVolumeMap} />
          )}
          {link && <PreviewSection projectId={projectId} volumes={volumes} />}
        </>
      )}
    </div>
  );
}

function VolumeMapSection({
  link, volumes, value, onChange,
}: {
  link: KbProjectLink;
  volumes: Volume[];
  value: Record<string, number>;
  onChange: (next: Record<string, number>) => void;
}) {
  return (
    <section className="space-y-3 rounded-2xl border border-surface-border bg-surface p-5">
      <div>
        <h2 className="text-sm font-semibold text-content">卷对标</h2>
        <p className="mt-1 text-xs text-content-secondary">
          默认按全书位置自动对齐（只拆了一部分时按已拆的范围算）；也可以给某一卷指定对标原书的哪一卷。改完记得保存。
        </p>
      </div>
      {volumes.length === 0 ? (
        <p className="text-xs text-content-tertiary">本书还没有分卷：分卷时会按对标书的分卷结构参考，分好后可以回来调整。</p>
      ) : link.source_volumes.length === 0 ? (
        <p className="text-xs text-content-tertiary">《{link.source_title}》的拆书结果里没有分卷，生成时按全书位置对齐剧情单元。</p>
      ) : (
        <ul className="divide-y divide-surface-border">
          {volumes.map((volume) => {
            const key = String(volume.volume_number);
            return (
              <li key={volume.id} className="flex flex-wrap items-center justify-between gap-3 py-2">
                <span className="text-sm text-content">
                  第{volume.volume_number}卷《{volume.title}》
                  <span className="ml-2 text-xs text-content-tertiary">第{volume.chapter_start}-{volume.chapter_end}章</span>
                </span>
                <select
                  value={value[key] ?? ''}
                  onChange={(e) => {
                    const next = { ...value };
                    if (e.target.value) next[key] = Number(e.target.value);
                    else delete next[key];
                    onChange(next);
                  }}
                  className={SELECT}
                >
                  <option value="">自动（按全书位置）</option>
                  {link.source_volumes.map((v) => (
                    <option key={v.index} value={v.index}>{sourceVolumeLabel(v)}</option>
                  ))}
                </select>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function PreviewSection({ projectId, volumes }: { projectId: string; volumes: Volume[] }) {
  const [scene, setScene] = useState<KbScene>('volume_detail');
  const [volumeId, setVolumeId] = useState('');
  const [unitIndex, setUnitIndex] = useState<number | ''>('');
  const [outlines, setOutlines] = useState<ChapterOutline[]>([]);
  const [outlineId, setOutlineId] = useState('');
  const [kbChapter, setKbChapter] = useState('');
  const [preview, setPreview] = useState<KbPreview | null>(null);
  const [running, setRunning] = useState(false);

  const volume = useMemo(() => volumes.find((v) => v.id === volumeId) ?? null, [volumes, volumeId]);
  const needsVolume = scene === 'volume_detail' || scene === 'unit_outline' || scene === 'chapter';

  useEffect(() => {
    if (scene !== 'chapter' || !volumeId) return;
    let cancelled = false;
    chapterOutlineApi
      .getChapterOutlines(projectId, { volume_id: volumeId, limit: 100 })
      .then((res) => { if (!cancelled) setOutlines(res.items ?? []); })
      .catch(() => { if (!cancelled) setOutlines([]); });
    return () => { cancelled = true; };
  }, [scene, projectId, volumeId]);

  const pickScene = (next: KbScene) => {
    setScene(next);
    setPreview(null);
    setOutlines([]);
    setOutlineId('');
  };

  const pickVolume = (next: string) => {
    setVolumeId(next);
    setUnitIndex('');
    setOutlines([]);
    setOutlineId('');
  };

  const run = async () => {
    setRunning(true);
    try {
      setPreview(await knowledgeApi.previewProjectContext(projectId, {
        scene,
        volume_id: needsVolume && volumeId ? volumeId : undefined,
        unit_index: scene === 'unit_outline' && unitIndex !== '' ? unitIndex : undefined,
        chapter_outline_id: scene === 'chapter' && outlineId ? outlineId : undefined,
        kb_chapter: scene === 'chapter' && Number(kbChapter) > 0 ? Number(kbChapter) : undefined,
      }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '预览失败');
    } finally {
      setRunning(false);
    }
  };

  const missing = (needsVolume && !volumeId) || (scene === 'unit_outline' && unitIndex === '') || (scene === 'chapter' && !outlineId);

  return (
    <section className="space-y-3 rounded-2xl border border-surface-border bg-surface p-5">
      <div>
        <h2 className="text-sm font-semibold text-content">预览会注入什么</h2>
        <p className="mt-1 text-xs text-content-secondary">选一个生成场景，看看这次会带上原书的哪几条、为什么对上它（不调用模型）。</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select value={scene} onChange={(e) => pickScene(e.target.value as KbScene)} className={SELECT}>
          {SCENES.map((s) => <option key={s} value={s}>{KB_SCENE_LABEL[s]}</option>)}
        </select>
        {needsVolume && (
          <select value={volumeId} onChange={(e) => pickVolume(e.target.value)} className={SELECT}>
            <option value="">选择本书的卷</option>
            {volumes.map((v) => <option key={v.id} value={v.id}>第{v.volume_number}卷《{v.title}》</option>)}
          </select>
        )}
        {scene === 'unit_outline' && volume && (
          <select value={unitIndex} onChange={(e) => setUnitIndex(e.target.value ? Number(e.target.value) : '')} className={SELECT}>
            <option value="">选择剧情单元</option>
            {volume.units.map((u) => (
              <option key={u.index} value={u.index}>单元 {u.index}《{u.title}》第{u.chapter_start}-{u.chapter_end}章</option>
            ))}
          </select>
        )}
        {scene === 'chapter' && volumeId && (
          <>
            <select value={outlineId} onChange={(e) => setOutlineId(e.target.value)} className={SELECT}>
              <option value="">{outlines.length ? '选择章纲' : '本卷还没有章纲'}</option>
              {outlines.map((o) => <option key={o.id} value={o.id}>第{o.chapter_number}章《{o.title}》</option>)}
            </select>
            <input
              value={kbChapter}
              onChange={(e) => setKbChapter(e.target.value.replace(/\D/g, ''))}
              placeholder="对标原书第几章（可空）"
              className={cn(SELECT, 'w-44')}
            />
          </>
        )}
        <button type="button" onClick={() => void run()} disabled={running || missing} className={BTN_PRIMARY}>
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />}
          预览
        </button>
      </div>

      {preview && (
        preview.refs.length === 0 && !preview.style ? (
          <p className="text-xs text-content-tertiary">这个场景这次不会注入仿写参考（仿写方式不涉及它，或对标书里没有对应的条目）。</p>
        ) : (
          <div className="space-y-3">
            <ul className="space-y-1">
              {preview.refs.map((r) => (
                <li key={r.key} className="text-xs text-content-secondary">
                  <span className="mr-1 rounded bg-brand/10 px-1.5 py-0.5 font-mono text-brand">{r.key}</span>
                  {r.label}
                  <span className="ml-1 text-content-tertiary">· {r.reason}</span>
                </li>
              ))}
            </ul>
            {preview.text && (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-xl bg-surface-hover p-3 text-xs leading-5 text-content-secondary">
                {preview.text}
                {preview.ref_instruction ? `\n\n${preview.ref_instruction}` : ''}
              </pre>
            )}
            {preview.style && (
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-surface-hover p-3 text-xs leading-5 text-content-secondary">
                {preview.style}
              </pre>
            )}
          </div>
        )
      )}
    </section>
  );
}
