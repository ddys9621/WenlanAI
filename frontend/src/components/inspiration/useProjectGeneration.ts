/** 灵感模式 - 项目生成编排 Hook（支持逐节点重跑） */

import { useCallback, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { wizardStreamApi } from '../../services/api';
import type {
  ApiError,
  Character,
  GenerateOutlineResponse,
  Outline,
  WizardVolumesResponse,
  WorldBuildingResponse,
} from '../../types';
import type { WizardAction, WizardData } from './types';
import type { MCPSelectorValue } from '../MCPSelector';
import type { ReferencePackSelectorValue } from '../ReferencePackSelector';

export type GenerationNodeKey = 'worldBuilding' | 'characters' | 'outline' | 'volumes';

export interface GenerationArtifacts {
  worldBuilding: WorldBuildingResponse | null;
  characters: Character[];
  outline: Outline | null;
  volumes: WizardVolumesResponse | null;
}

/** 灵感模式固定用默认篇幅创建项目：全书章节数（卷纲按它分卷） */
const DEFAULT_CHAPTER_COUNT = 30;

interface UseProjectGenerationOptions {
  dispatch: React.Dispatch<WizardAction>;
  mcpSettings: MCPSelectorValue;
  /** V3.2-B：灵感模式入口选好的拆书参考包（可选）。
   * - enabled=true 时：三步生成都透传 R8 字段到后端
   * - 未提供/enabled=false：走原本默认逻辑（项目创建后不挂载，后端 注入到机制也跳过拆书） */
  refPackSettings?: ReferencePackSelectorValue;
}

/** 把 ReferencePackSelectorValue 转为 R8 API payload 字段（只在 enabled 时返回）。 */
function _r8Payload(v?: ReferencePackSelectorValue): { pack_ids?: string[]; dimensions?: string[]; strength?: 'light' | 'medium' | 'deep' } {
  if (!v || !v.enabled) return {};
  return {
    pack_ids: v.packIds.length > 0 ? v.packIds : undefined,
    dimensions: v.dimensions.length > 0 ? v.dimensions : undefined,
    strength: v.strength,
  };
}

const EMPTY_ARTIFACTS: GenerationArtifacts = {
  worldBuilding: null,
  characters: [],
  outline: null,
  volumes: null,
};

type StageProgressPreset = Partial<Record<GenerationNodeKey, [number, number]>>;

const NODE_PROGRESS_PRESETS: Record<GenerationNodeKey, StageProgressPreset> = {
  worldBuilding: {
    worldBuilding: [0, 25],
    characters: [25, 50],
    outline: [50, 75],
    volumes: [75, 100],
  },
  characters: {
    characters: [0, 34],
    outline: [34, 67],
    volumes: [67, 100],
  },
  outline: {
    outline: [0, 50],
    volumes: [50, 100],
  },
  volumes: {
    volumes: [0, 100],
  },
};

const INITIAL_NODE_STATUS: Record<GenerationNodeKey, Partial<Record<GenerationNodeKey, 'pending' | 'completed'>>> = {
  worldBuilding: {},
  characters: {
    worldBuilding: 'completed',
  },
  outline: {
    worldBuilding: 'completed',
    characters: 'completed',
  },
  volumes: {
    worldBuilding: 'completed',
    characters: 'completed',
    outline: 'completed',
  },
};

const mapProgress = (
  preset: StageProgressPreset,
  node: GenerationNodeKey,
  rawProgress: number,
) => {
  const [start, end] = getNodeRange(preset, node);
  const safeProgress = Math.max(0, Math.min(rawProgress, 100));
  return start + Math.floor(((end - start) * safeProgress) / 100);
};

const getNodeRange = (preset: StageProgressPreset, node: GenerationNodeKey): [number, number] =>
  preset[node] || [0, 100];

const getOutlineFromResponse = (response: GenerateOutlineResponse) =>
  response.outline || response.outlines?.[0] || null;

export function useProjectGeneration({ dispatch, mcpSettings, refPackSettings }: UseProjectGenerationOptions) {
  const [artifacts, setArtifacts] = useState<GenerationArtifacts>(EMPTY_ARTIFACTS);
  const [runningNode, setRunningNode] = useState<GenerationNodeKey | null>(null);
  const generationRunRef = useRef(0);

  const mcpEnabled = useMemo(
    () => mcpSettings.enable && mcpSettings.selected.length > 0,
    [mcpSettings.enable, mcpSettings.selected.length],
  );
  const mcpPlugins = useMemo(
    () => (mcpSettings.enable ? mcpSettings.selected : []),
    [mcpSettings.enable, mcpSettings.selected],
  );

  const resetArtifacts = useCallback(() => {
    setArtifacts(EMPTY_ARTIFACTS);
    setRunningNode(null);
  }, []);

  const createRunId = useCallback(() => {
    generationRunRef.current += 1;
    return generationRunRef.current;
  }, []);

  const isRunActive = useCallback((runId: number) => generationRunRef.current === runId, []);

  const dispatchIfActive = useCallback((runId: number, action: WizardAction) => {
    if (!isRunActive(runId)) return false;
    dispatch(action);
    return true;
  }, [dispatch, isRunActive]);

  const cancelGeneration = useCallback(() => {
    generationRunRef.current += 1;
    setRunningNode(null);
  }, []);

  const cleanupDownstreamData = useCallback(async (projectId: string, progressBase: number, runId: number) => {
    dispatchIfActive(runId, {
      type: 'GEN_PROGRESS',
      payload: {
        progress: progressBase,
        message: '正在清理旧的角色、大纲和章节...',
      },
    });

    await wizardStreamApi.cleanupWizardDataStream(projectId, {
      onProgress: (message, progress) => {
        if (!isRunActive(runId)) return;
        const nextProgress = progressBase + Math.floor((Math.max(progress, 0) / 100) * 8);
        dispatch({
          type: 'GEN_PROGRESS',
          payload: {
            progress: Math.min(nextProgress, progressBase + 8),
            message,
          },
        });
      },
    });
  }, [dispatch, dispatchIfActive, isRunActive]);

  const runWorldBuilding = useCallback(async (
    data: WizardData,
    preset: StageProgressPreset,
    runId: number,
    existingProjectId?: string,
  ) => {
    dispatchIfActive(runId, { type: 'GEN_STEP_UPDATE', payload: { worldBuilding: 'processing' } });
    dispatchIfActive(runId, {
      type: 'GEN_PROGRESS',
      payload: {
        progress: getNodeRange(preset, 'worldBuilding')[0],
        message: existingProjectId ? '正在重生成世界观...' : '正在生成世界观...',
      },
    });

    const result = existingProjectId
      ? await wizardStreamApi.regenerateWorldBuildingStream(
          existingProjectId,
          {
            enable_mcp: mcpEnabled,
            selected_plugins: mcpPlugins,
          },
          {
            onProgress: (message, progress) => {
              if (!isRunActive(runId)) return;
              dispatch({
                type: 'GEN_PROGRESS',
                payload: {
                  progress: mapProgress(preset, 'worldBuilding', progress),
                  message,
                },
              });
            },
            onResult: (response) => {
              if (!isRunActive(runId)) return;
              setArtifacts((current) => ({
                ...current,
                worldBuilding: response as WorldBuildingResponse,
              }));
              dispatch({ type: 'GEN_STEP_UPDATE', payload: { worldBuilding: 'completed' } });
            },
            onError: (error) => {
              if (!isRunActive(runId)) return;
              dispatch({ type: 'GEN_STEP_UPDATE', payload: { worldBuilding: 'error' } });
              throw new Error(error);
            },
          },
        )
      : await wizardStreamApi.generateWorldBuildingStream(
          {
            title: data.title,
            description: data.description,
            theme: data.theme,
            genre: data.genre.join('、'),
            narrative_perspective: data.narrative_perspective,
            target_words: 100000,
            chapter_count: 30,
            character_count: 5,
            enable_mcp: mcpEnabled,
            selected_plugins: mcpPlugins,
            // V3.2-B：灵感入口选好的拆书 pack 会在项目创建后被后端自动挂载
            ..._r8Payload(refPackSettings),
          },
          {
            onProgress: (message, progress) => {
              if (!isRunActive(runId)) return;
              dispatch({
                type: 'GEN_PROGRESS',
                payload: {
                  progress: mapProgress(preset, 'worldBuilding', progress),
                  message,
                },
              });
            },
            onResult: (response) => {
              if (!isRunActive(runId)) return;
              setArtifacts((current) => ({
                ...current,
                worldBuilding: response as WorldBuildingResponse,
              }));
              dispatch({ type: 'GEN_STEP_UPDATE', payload: { worldBuilding: 'completed' } });
            },
            onError: (error) => {
              if (!isRunActive(runId)) return;
              dispatch({ type: 'GEN_STEP_UPDATE', payload: { worldBuilding: 'error' } });
              throw new Error(error);
            },
          },
        );

    if (result?.project_id && isRunActive(runId)) {
      dispatch({ type: 'GEN_PROJECT_CREATED', payload: result.project_id });
    }

    return result as WorldBuildingResponse;
  }, [dispatch, dispatchIfActive, isRunActive, mcpEnabled, mcpPlugins, refPackSettings]);

  const runCharacters = useCallback(async (
    projectId: string,
    data: WizardData,
    preset: StageProgressPreset,
    worldBuilding: WorldBuildingResponse | null,
    runId: number,
  ) => {
    dispatchIfActive(runId, { type: 'GEN_STEP_UPDATE', payload: { characters: 'processing' } });
    dispatchIfActive(runId, {
      type: 'GEN_PROGRESS',
      payload: {
        progress: getNodeRange(preset, 'characters')[0],
        message: '正在生成角色...',
      },
    });

    const result = await wizardStreamApi.generateCharactersStream(
      {
        project_id: projectId,
        count: 5,
        world_context: worldBuilding
          ? {
              time_period: worldBuilding.time_period || '',
              location: worldBuilding.location || '',
              atmosphere: worldBuilding.atmosphere || '',
              rules: worldBuilding.rules || '',
            }
          : undefined,
        theme: data.theme,
        genre: data.genre.join('、'),
        enable_mcp: mcpEnabled,
        selected_plugins: mcpPlugins,
        // V3.2-B：后端读项目挂载列表（上一步刚被自动挂上）；此处继续透传以便后端有显式选择优先级
        ..._r8Payload(refPackSettings),
      },
      {
        onProgress: (message, progress) => {
          if (!isRunActive(runId)) return;
          dispatch({
            type: 'GEN_PROGRESS',
            payload: {
              progress: mapProgress(preset, 'characters', progress),
              message,
            },
          });
        },
        onResult: (response) => {
          if (!isRunActive(runId)) return;
          setArtifacts((current) => ({
            ...current,
            characters: (response as { characters?: Character[] }).characters || [],
          }));
          dispatch({ type: 'GEN_STEP_UPDATE', payload: { characters: 'completed' } });
        },
        onError: (error) => {
          if (!isRunActive(runId)) return;
          dispatch({ type: 'GEN_STEP_UPDATE', payload: { characters: 'error' } });
          throw new Error(error);
        },
      },
    );

    return (result as { characters?: Character[] }).characters || [];
  }, [dispatch, dispatchIfActive, isRunActive, mcpEnabled, mcpPlugins, refPackSettings]);

  const runOutline = useCallback(async (
    projectId: string,
    data: WizardData,
    preset: StageProgressPreset,
    runId: number,
  ) => {
    dispatchIfActive(runId, { type: 'GEN_STEP_UPDATE', payload: { outline: 'processing' } });
    dispatchIfActive(runId, {
      type: 'GEN_PROGRESS',
      payload: {
        progress: getNodeRange(preset, 'outline')[0],
        message: '正在生成故事大纲...',
      },
    });

    const response = await wizardStreamApi.generateCompleteOutlineStream(
      {
        project_id: projectId,
        chapter_count: 30,
        narrative_perspective: data.narrative_perspective,
        target_words: 100000,
        enable_mcp: mcpEnabled,
        selected_plugins: mcpPlugins,
        // V3.2-B：透传灵感入口选好的拆书参数
        ..._r8Payload(refPackSettings),
      },
      {
        onProgress: (message, progress) => {
          if (!isRunActive(runId)) return;
          dispatch({
            type: 'GEN_PROGRESS',
            payload: {
              progress: mapProgress(preset, 'outline', progress),
              message,
            },
          });
        },
        onResult: (result) => {
          if (!isRunActive(runId)) return;
          const typed = result as GenerateOutlineResponse;
          const outline = getOutlineFromResponse(typed);
          setArtifacts((current) => ({
            ...current,
            outline,
          }));
          dispatch({ type: 'GEN_STEP_UPDATE', payload: { outline: 'completed' } });
        },
        onError: (error) => {
          if (!isRunActive(runId)) return;
          dispatch({ type: 'GEN_STEP_UPDATE', payload: { outline: 'error' } });
          throw new Error(error);
        },
      },
    );

    return getOutlineFromResponse(response as GenerateOutlineResponse);
  }, [dispatch, dispatchIfActive, isRunActive, mcpEnabled, mcpPlugins, refPackSettings]);

  const runVolumes = useCallback(async (
    projectId: string,
    preset: StageProgressPreset,
    runId: number,
  ) => {
    dispatchIfActive(runId, { type: 'GEN_STEP_UPDATE', payload: { volumes: 'processing' } });
    dispatchIfActive(runId, {
      type: 'GEN_PROGRESS',
      payload: {
        progress: getNodeRange(preset, 'volumes')[0],
        message: '正在生成卷纲...',
      },
    });

    const response = await wizardStreamApi.generateVolumesStream(
      {
        project_id: projectId,
        chapter_count: DEFAULT_CHAPTER_COUNT,
      },
      {
        onProgress: (message, progress) => {
          if (!isRunActive(runId)) return;
          dispatch({
            type: 'GEN_PROGRESS',
            payload: {
              progress: mapProgress(preset, 'volumes', progress),
              message,
            },
          });
        },
        onResult: (result) => {
          if (!isRunActive(runId)) return;
          setArtifacts((current) => ({ ...current, volumes: result as WizardVolumesResponse }));
          dispatch({ type: 'GEN_STEP_UPDATE', payload: { volumes: 'completed' } });
        },
        onError: (error) => {
          if (!isRunActive(runId)) return;
          dispatch({ type: 'GEN_STEP_UPDATE', payload: { volumes: 'error' } });
          throw new Error(error);
        },
      },
    );

    return response as WizardVolumesResponse;
  }, [dispatch, dispatchIfActive, isRunActive]);

  const runFromNode = useCallback(async (
    startNode: GenerationNodeKey,
    data: WizardData,
    runId: number,
    existingProjectId?: string,
  ) => {
    const preset = NODE_PROGRESS_PRESETS[startNode];
    const initialStatus = INITIAL_NODE_STATUS[startNode];

    setRunningNode(startNode);
    dispatchIfActive(runId, { type: 'GEN_START', payload: { title: data.title } });
    dispatchIfActive(runId, { type: 'GEN_STEP_UPDATE', payload: initialStatus });

    if (startNode === 'worldBuilding') {
      setArtifacts(EMPTY_ARTIFACTS);
    } else if (startNode === 'characters') {
      setArtifacts((current) => ({
        ...current,
        characters: [],
        outline: null,
        volumes: null,
      }));
    } else if (startNode === 'outline') {
      setArtifacts((current) => ({
        ...current,
        outline: null,
        volumes: null,
      }));
    } else {
      setArtifacts((current) => ({
        ...current,
        volumes: null,
      }));
    }

    try {
      let projectId = existingProjectId || '';
      let worldBuilding = startNode === 'worldBuilding' ? null : artifacts.worldBuilding;

      if (startNode === 'worldBuilding') {
        worldBuilding = await runWorldBuilding(data, preset, runId, existingProjectId);
        if (!isRunActive(runId)) return;
        projectId = worldBuilding?.project_id || projectId;

        if (existingProjectId) {
          await cleanupDownstreamData(projectId, getNodeRange(preset, 'characters')[0] - 8, runId);
          if (!isRunActive(runId)) return;
          dispatch({ type: 'GEN_STEP_UPDATE', payload: { characters: 'pending', outline: 'pending', volumes: 'pending' } });
          setArtifacts((current) => ({
            ...current,
            characters: [],
            outline: null,
            volumes: null,
          }));
        }
      }

      if (!projectId) {
        throw new Error('项目创建失败');
      }

      if (startNode === 'characters') {
        await cleanupDownstreamData(projectId, Math.max(getNodeRange(preset, 'characters')[0], 0), runId);
        if (!isRunActive(runId)) return;
        dispatch({ type: 'GEN_STEP_UPDATE', payload: { characters: 'pending', outline: 'pending', volumes: 'pending' } });
      }

      if (startNode === 'worldBuilding' || startNode === 'characters') {
        await runCharacters(projectId, data, preset, worldBuilding, runId);
        if (!isRunActive(runId)) return;
      }

      if (startNode === 'outline' || startNode === 'volumes') {
        // 重跑总纲 / 卷纲：后端分卷时保留已有章纲的卷、替换其余草稿卷，不必先清理
        dispatch({ type: 'GEN_STEP_UPDATE', payload: { volumes: 'pending' } });
      }

      if (startNode !== 'volumes') {
        await runOutline(projectId, data, preset, runId);
        if (!isRunActive(runId)) return;
      }

      await runVolumes(projectId, preset, runId);
      if (!isRunActive(runId)) return;

      dispatch({ type: 'GEN_COMPLETE' });
      toast.success(startNode === 'worldBuilding' && !existingProjectId ? '项目创建成功！' : '已从当前节点重新生成');
    } catch (error) {
      if (!isRunActive(runId)) return;
      const apiError = error as ApiError;
      const message = apiError.response?.data?.detail || apiError.message || '未知错误';
      toast.error(`创建项目失败：${message}`);
      dispatch({ type: 'GEN_ERROR', payload: message });
    } finally {
      if (isRunActive(runId)) {
        setRunningNode(null);
      }
    }
  }, [artifacts.worldBuilding, cleanupDownstreamData, dispatch, dispatchIfActive, isRunActive, runCharacters, runOutline, runVolumes, runWorldBuilding]);

  const startGeneration = useCallback(async (data: WizardData) => {
    const runId = createRunId();
    await runFromNode('worldBuilding', data, runId);
  }, [createRunId, runFromNode]);

  const regenerateFrom = useCallback(async (
    startNode: GenerationNodeKey,
    data: WizardData,
    projectId: string,
  ) => {
    const runId = createRunId();
    await runFromNode(startNode, data, runId, projectId);
  }, [createRunId, runFromNode]);

  return {
    artifacts,
    runningNode,
    startGeneration,
    regenerateFrom,
    cancelGeneration,
    resetArtifacts,
  };
}
