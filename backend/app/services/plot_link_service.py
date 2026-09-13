"""剧情关联服务"""
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models import PlotCard, PlotLine, PlotCardPlotLineLink
from app.logger import get_logger

logger = get_logger(__name__)


class PlotLinkService:
    """剧情关联服务类 - 统一管理所有关联操作"""
    
    @staticmethod
    async def add_cards_to_plot_line(
        db: AsyncSession,
        plot_line_id: str,
        card_ids: List[str]
    ) -> Dict[str, Any]:
        """将剧情卡片添加到剧情线"""
        
        # 验证剧情线存在
        line_result = await db.execute(select(PlotLine).where(PlotLine.id == plot_line_id))
        line = line_result.scalar_one_or_none()
        if not line:
            raise ValueError("剧情线不存在")
        
        # 验证卡片存在
        cards_result = await db.execute(
            select(PlotCard.id).where(PlotCard.id.in_(card_ids))
        )
        existing_card_ids = [card.id for card in cards_result.scalars().all()]
        
        if not existing_card_ids:
            return {"created_count": 0, "skipped_count": 0, "message": "没有找到有效的剧情卡片"}
        
        # 检查已存在的关联
        existing_links_result = await db.execute(
            select(PlotCardPlotLineLink.plot_card_id).where(
                PlotCardPlotLineLink.plot_line_id == plot_line_id,
                PlotCardPlotLineLink.plot_card_id.in_(existing_card_ids)
            )
        )
        existing_linked_ids = [link.plot_card_id for link in existing_links_result.scalars().all()]
        
        # 创建新关联
        new_card_ids = [card_id for card_id in existing_card_ids if card_id not in existing_linked_ids]
        created_count = 0
        
        for card_id in new_card_ids:
            link = PlotCardPlotLineLink(
                plot_card_id=card_id,
                plot_line_id=plot_line_id
            )
            db.add(link)
            created_count += 1
        
        await db.commit()
        
        logger.info(f"成功为剧情线 {plot_line_id} 添加 {created_count} 个剧情卡片关联")
        
        return {
            "created_count": created_count,
            "skipped_count": len(existing_linked_ids),
            "message": f"成功添加 {created_count} 个剧情卡片，跳过 {len(existing_linked_ids)} 个已存在的关联"
        }
    
    @staticmethod
    async def remove_cards_from_plot_line(
        db: AsyncSession,
        plot_line_id: str,
        card_ids: List[str]
    ) -> Dict[str, Any]:
        """从剧情线移除剧情卡片"""
        
        # 验证剧情线存在
        line_result = await db.execute(select(PlotLine).where(PlotLine.id == plot_line_id))
        line = line_result.scalar_one_or_none()
        if not line:
            raise ValueError("剧情线不存在")
        
        # 删除关联
        result = await db.execute(
            delete(PlotCardPlotLineLink).where(
                PlotCardPlotLineLink.plot_line_id == plot_line_id,
                PlotCardPlotLineLink.plot_card_id.in_(card_ids)
            )
        )
        
        removed_count = result.rowcount
        await db.commit()
        
        logger.info(f"成功从剧情线 {plot_line_id} 移除 {removed_count} 个剧情卡片关联")
        
        return {
            "removed_count": removed_count,
            "message": f"成功移除 {removed_count} 个剧情卡片关联"
        }
