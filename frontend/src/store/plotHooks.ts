/**
 * 剧情相关的状态管理 hooks
 */
import { useCallback } from 'react';
import { toast } from 'sonner';
import { useStore } from './index';
import { plotCardApi, volumeApi, chapterOutlineApi } from '../services/api';
import type {
  PlotCardCreate,
  PlotCardUpdate,
  PlotCardReorderRequest,
  VolumeFields,
  ChapterOutlineCreate,
  ChapterOutlineUpdate,
  ChapterOutlineReorderRequest,
  ChapterOutlineBatchCreateRequest,
  // PaginationResponse
} from '../types';

// 剧情卡片状态管理
export function usePlotCardSync() {
  const {
    plotCards,
    setPlotCards,
    addPlotCard,
    updatePlotCard,
    removePlotCard,
  } = useStore();

  // 刷新剧情卡片列表
  const refreshPlotCards = useCallback(async (projectId: string, params?: {
    skip?: number;
    limit?: number;
    card_type?: string;
    chapter_outline_id?: string;
  }) => {
    try {
      const response = await plotCardApi.getPlotCards(projectId, params);
      setPlotCards(response.items);
      return response;
    } catch (error) {
      console.error('获取剧情卡片失败:', error);
      toast.error('获取剧情卡片失败');
      throw error;
    }
  }, [setPlotCards]);

  // 创建剧情卡片
  const createPlotCard = useCallback(async (data: PlotCardCreate) => {
    try {
      const newCard = await plotCardApi.createPlotCard(data);
      addPlotCard(newCard);
      toast.success('剧情卡片创建成功');
      return newCard;
    } catch (error) {
      console.error('创建剧情卡片失败:', error);
      toast.error('创建剧情卡片失败');
      throw error;
    }
  }, [addPlotCard]);

  // 更新剧情卡片
  const updatePlotCardData = useCallback(async (cardId: string, data: PlotCardUpdate) => {
    try {
      const updatedCard = await plotCardApi.updatePlotCard(cardId, data);
      updatePlotCard(updatedCard);
      toast.success('剧情卡片更新成功');
      return updatedCard;
    } catch (error) {
      console.error('更新剧情卡片失败:', error);
      toast.error('更新剧情卡片失败');
      throw error;
    }
  }, [updatePlotCard]);

  // 删除剧情卡片
  const deletePlotCard = useCallback(async (cardId: string) => {
    try {
      await plotCardApi.deletePlotCard(cardId);
      removePlotCard(cardId);
      toast.success('剧情卡片删除成功');
    } catch (error) {
      console.error('删除剧情卡片失败:', error);
      toast.error('删除剧情卡片失败');
      throw error;
    }
  }, [removePlotCard]);

  // 重排序剧情卡片
  const reorderPlotCards = useCallback(async (data: PlotCardReorderRequest) => {
    try {
      await plotCardApi.reorderPlotCards(data);
      toast.success('剧情卡片排序更新成功');
    } catch (error) {
      console.error('重排序剧情卡片失败:', error);
      toast.error('重排序剧情卡片失败');
      throw error;
    }
  }, []);

  // 获取卡片类型统计
  const getCardTypes = useCallback(async (projectId: string) => {
    try {
      const response = await plotCardApi.getCardTypes(projectId);
      return response.types;
    } catch (error) {
      console.error('获取卡片类型失败:', error);
      throw error;
    }
  }, []);

  return {
    plotCards,
    refreshPlotCards,
    createPlotCard,
    updatePlotCard: updatePlotCardData,
    deletePlotCard,
    reorderPlotCards,
    getCardTypes,
  };
}

// 卷纲状态管理（总纲 → 卷纲 → 章纲；三个 AI 生成走 volumeApi 的后台任务 + SSE，在页面里调用）
export function useVolumeSync() {
  const { volumes, setVolumes, updateVolume, removeVolume } = useStore();

  const refreshVolumes = useCallback(async (projectId: string) => {
    try {
      const response = await volumeApi.list(projectId);
      setVolumes(response.items);
      return response;
    } catch (error) {
      console.error('获取卷纲失败:', error);
      toast.error('获取卷纲失败');
      throw error;
    }
  }, [setVolumes]);

  const saveVolume = useCallback(async (volumeId: string, data: VolumeFields) => {
    const saved = await volumeApi.update(volumeId, data);
    updateVolume(saved);
    return saved;
  }, [updateVolume]);

  const confirmVolume = useCallback(async (volumeId: string) => {
    const saved = await volumeApi.confirm(volumeId);
    updateVolume(saved);
    return saved;
  }, [updateVolume]);

  const deleteVolume = useCallback(async (volumeId: string) => {
    await volumeApi.remove(volumeId);
    removeVolume(volumeId);
  }, [removeVolume]);

  return { volumes, refreshVolumes, saveVolume, confirmVolume, deleteVolume };
}

// 章纲状态管理
export function useChapterOutlineSync() {
  const {
    chapterOutlines,
    setChapterOutlines,
    addChapterOutline,
    updateChapterOutline,
    removeChapterOutline,
  } = useStore();

  // 刷新章纲列表
  const refreshChapterOutlines = useCallback(async (projectId: string, params?: {
    skip?: number;
    limit?: number;
    volume_id?: string;
  }) => {
    try {
      const response = await chapterOutlineApi.getChapterOutlines(projectId, params);
      setChapterOutlines(response.items);
      return response;
    } catch (error) {
      console.error('获取章纲失败:', error);
      toast.error('获取章纲失败');
      throw error;
    }
  }, [setChapterOutlines]);

  // 创建章纲
  const createChapterOutline = useCallback(async (data: ChapterOutlineCreate) => {
    try {
      const newOutline = await chapterOutlineApi.createChapterOutline(data);
      addChapterOutline(newOutline);
      toast.success('章纲创建成功');
      return newOutline;
    } catch (error) {
      console.error('创建章纲失败:', error);
      toast.error('创建章纲失败');
      throw error;
    }
  }, [addChapterOutline]);

  // 更新章纲
  const updateChapterOutlineData = useCallback(async (outlineId: string, data: ChapterOutlineUpdate) => {
    try {
      const updatedOutline = await chapterOutlineApi.updateChapterOutline(outlineId, data);
      updateChapterOutline(updatedOutline);
      toast.success('章纲更新成功');
      return updatedOutline;
    } catch (error) {
      console.error('更新章纲失败:', error);
      toast.error('更新章纲失败');
      throw error;
    }
  }, [updateChapterOutline]);

  // 删除章纲
  const deleteChapterOutline = useCallback(async (outlineId: string) => {
    try {
      await chapterOutlineApi.deleteChapterOutline(outlineId);
      removeChapterOutline(outlineId);
      toast.success('章纲删除成功');
    } catch (error) {
      console.error('删除章纲失败:', error);
      toast.error('删除章纲失败');
      throw error;
    }
  }, [removeChapterOutline]);

  // 重排序章纲
  const reorderChapterOutlines = useCallback(async (data: ChapterOutlineReorderRequest) => {
    try {
      await chapterOutlineApi.reorderChapterOutlines(data);
      toast.success('章纲排序更新成功');
    } catch (error) {
      console.error('重排序章纲失败:', error);
      toast.error('重排序章纲失败');
      throw error;
    }
  }, []);

  // 批量创建章纲
  const batchCreateChapterOutlines = useCallback(async (data: ChapterOutlineBatchCreateRequest) => {
    try {
      const newOutlines = await chapterOutlineApi.batchCreateChapterOutlines(data);
      newOutlines.forEach(outline => addChapterOutline(outline));
      toast.success(`成功创建 ${newOutlines.length} 个章纲`);
      return newOutlines;
    } catch (error) {
      console.error('批量创建章纲失败:', error);
      toast.error('批量创建章纲失败');
      throw error;
    }
  }, [addChapterOutline]);

  return {
    chapterOutlines,
    refreshChapterOutlines,
    createChapterOutline,
    updateChapterOutline: updateChapterOutlineData,
    deleteChapterOutline,
    reorderChapterOutlines,
    batchCreateChapterOutlines,
  };
}
