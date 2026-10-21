"""世界观上下文：生成流程读「世界设定」的唯一出口。

世界观分三层存，拼给 AI 也按这三层来：
- 总述：project.world_rules 单字段（「世界设定」页作者写的整段世界规则）
- 体系：world_rules 表（境界 / 装备 / 地图三类有层级的结构化系统，语义检索）
- 条目：setting_entries 表（术语 / 铁律 / 势力等零散设定，语义检索）

以前各生成入口自己手拼、口径不一：单人物生成只读总述，组织生成、向导角色、向导总纲都漏了设定条目。
现在都走 build_world_context，补一处全补齐。两路检索各自失败只记日志、不中断生成；
检索服务内部已上报 reference 事件，这里不重复报。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.project import Project

logger = get_logger(__name__)

RULE_LIMIT = 5
ENTRY_LIMIT = 6
UNSET = "未设定"


@dataclass(frozen=True)
class WorldContext:
    overview: str = ""  # project.world_rules 原文
    rules: str = ""  # 世界规则明细（WorldRuleService 已带「## 世界规则明细」标题）
    entries: str = ""  # 相关设定条目（setting_entry_service 已带「## 相关世界设定条目」标题）

    @property
    def detail(self) -> str:
        """检索到的明细（体系 + 条目），不含总述：给把总述单独放进提示词模板的入口。"""
        return "\n\n".join(p for p in (self.rules, self.entries) if p)

    @property
    def merged(self) -> str:
        """总述 + 明细合成一段：给整段塞进「世界规则」字段的入口；三层都空才是「未设定」。"""
        return "\n\n".join(p for p in (self.overview.strip(), self.detail) if p) or UNSET


def world_query(project: Project, *clues: str) -> str:
    """检索用的查询文本：主题 + 类型 + 各入口自己的线索（章纲 / 组织类型 / 「人物 势力」等）。"""
    return " ".join(p.strip() for p in (project.theme or "", project.genre or "", *clues) if p and p.strip())


async def build_world_context(
    db: AsyncSession, project: Project, query: str, *,
    rule_limit: int = RULE_LIMIT, entry_limit: int = ENTRY_LIMIT, scene: str = "世界观",
) -> WorldContext:
    from app.services import setting_entry_service  # 延迟导入：两个检索服务都会拉起向量运行时
    from app.services.world_rule_service import world_rule_service

    rules = entries = ""
    try:
        rules = await world_rule_service.generate_rules_summary_with_search(db, project.id, query, limit=rule_limit) or ""
    except Exception as exc:  # noqa: BLE001 - 检索只是增强
        logger.warning("⚠️ [%s] 加载世界规则失败: %s", scene, exc)
    try:
        entries = await setting_entry_service.generate_summary_with_search(db, project.id, query, limit=entry_limit) or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("⚠️ [%s] 加载世界设定条目失败: %s", scene, exc)
    return WorldContext(overview=project.world_rules or "", rules=rules, entries=entries)
