/**
 * 剧情相关的状态管理 hooks
 */
import { useCallback } from 'react';
import { toast } from 'sonner';
import { useStore } from './index';
import { plotCardApi, plotLineApi, chapterOutlineApi } from '../services/api';
import type {
  PlotCardCreate,
  PlotCardUpdate,
  PlotCardReorderRequest,
  PlotLineCreate,
  PlotLineUpdate,
  PlotLineReorderRequest,
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

// 剧情线状态管理
export function usePlotLineSync() {
  const {
    plotLines,
    setPlotLines,
    addPlotLine,
    updatePlotLine,
    removePlotLine,
  } = useStore();

  // 刷新剧情线列表
  const refreshPlotLines = useCallback(async (projectId: string, params?: {
    skip?: number;
    limit?: number;
    line_type?: string;
  }) => {
    try {
      const response = await plotLineApi.getPlotLines(projectId, params);
      setPlotLines(response.items);
      return response;
    } catch (error) {
      console.error('获取剧情线失败:', error);
      toast.error('获取剧情线失败');
      throw error;
    }
  }, [setPlotLines]);

  // 创建剧情线
  const createPlotLine = useCallback(async (data: PlotLineCreate) => {
    try {
      const newLine = await plotLineApi.createPlotLine(data);
      addPlotLine(newLine);
      toast.success('剧情线创建成功');
      return newLine;
    } catch (error) {
      console.error('创建剧情线失败:', error);
      toast.error('创建剧情线失败');
      throw error;
    }
  }, [addPlotLine]);

  // 更新剧情线
  const updatePlotLineData = useCallback(async (lineId: string, data: PlotLineUpdate) => {
    try {
      const updatedLine = await plotLineApi.updatePlotLine(lineId, data);
      updatePlotLine(updatedLine);
      toast.success('剧情线更新成功');
      return updatedLine;
    } catch (error) {
      console.error('更新剧情线失败:', error);
      toast.error('更新剧情线失败');
      throw error;
    }
  }, [updatePlotLine]);

  // 删除剧情线
  const deletePlotLine = useCallback(async (lineId: string) => {
    try {
      await plotLineApi.deletePlotLine(lineId);
      removePlotLine(lineId);
      toast.success('剧情线删除成功');
    } catch (error) {
      console.error('删除剧情线失败:', error);
      toast.error('删除剧情线失败');
      throw error;
    }
  }, [removePlotLine]);

  // 重排序剧情线
  const reorderPlotLines = useCallback(async (data: PlotLineReorderRequest) => {
    try {
      await plotLineApi.reorderPlotLines(data);
      toast.success('剧情线排序更新成功');
    } catch (error) {
      console.error('重排序剧情线失败:', error);
      toast.error('重排序剧情线失败');
      throw error;
    }
  }, []);

  // 获取剧情线类型统计
  const getLineTypes = useCallback(async (projectId: string) => {
    try {
      const response = await plotLineApi.getLineTypes(projectId);
      return response.types;
    } catch (error) {
      console.error('获取剧情线类型失败:', error);
      throw error;
    }
  }, []);

  // 向剧情线添加卡片
  const addCardsToLine = useCallback(async (lineId: string, cardIds: string[]) => {
    try {
      await plotLineApi.addCardsToLine(lineId, cardIds);
      toast.success('剧情卡片添加成功');
    } catch (error) {
      console.error('添加剧情卡片失败:', error);
      toast.error('添加剧情卡片失败');
      throw error;
    }
  }, []);

  // 从剧情线移除卡片
  const removeCardsFromLine = useCallback(async (lineId: string, cardIds: string[]) => {
    try {
      await plotLineApi.removeCardsFromLine(lineId, cardIds);
      toast.success('剧情卡片移除成功');
    } catch (error) {
      console.error('移除剧情卡片失败:', error);
      toast.error('移除剧情卡片失败');
      throw error;
    }
  }, []);

  return {
    plotLines,
    refreshPlotLines,
    createPlotLine,
    updatePlotLine: updatePlotLineData,
    deletePlotLine,
    reorderPlotLines,
    getLineTypes,
    addCardsToLine,
    removeCardsFromLine,
  };
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
    plot_line_id?: string;
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

  // 获取章纲统计信息
  const getChapterOutlineStatistics = useCallback(async (projectId: string) => {
    try {
      const response = await chapterOutlineApi.getChapterOutlineStatistics(projectId);
      return response;
    } catch (error) {
      console.error('获取章纲统计失败:', error);
      throw error;
    }
  }, []);

  return {
    chapterOutlines,
    refreshChapterOutlines,
    createChapterOutline,
    updateChapterOutline: updateChapterOutlineData,
    deleteChapterOutline,
    reorderChapterOutlines,
    batchCreateChapterOutlines,
    getChapterOutlineStatistics,
  };
}
