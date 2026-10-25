"""世界设定条目：术语 / 铁律 / 势力 / 通用规则等结构化世界观，分条存、每条独立容量，生成时语义检索注入。

与 world_rule（境界 / 装备 / 地图三类结构化系统）互补：这张表放不属于那三类的通用世界设定，
不再把它们全堆进 project.world_rules 单字段撑爆 20000 字上限。
"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.sql import func
from app.db_base import Base
import uuid

# 分类的合法取值与中文标签（字段白名单 / 新建候选 / setting_entry_service 共用）
SETTING_CATEGORY_LABELS = {"term": "术语", "law": "铁律", "faction": "势力", "rule": "规则", "other": "其他"}
SETTING_CATEGORIES = tuple(SETTING_CATEGORY_LABELS)


class SettingEntry(Base):
    """世界设定条目表"""
    __tablename__ = "setting_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)

    # 分类（自由字符串，给几个建议值）：term 术语 / law 铁律 / faction 势力 / rule 规则 / other 其他
    category = Column(String(50), nullable=False, default="other", index=True, comment="设定分类")
    title = Column(String(200), nullable=False, comment="条目名称")
    summary = Column(Text, comment="一句话简述（界面与 prompt 摘要用）")
    content = Column(Text, comment="详细设定（长文本）")
    order_index = Column(Integer, default=0, comment="排序序号")

    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<SettingEntry(id={self.id}, project_id={self.project_id}, category={self.category}, title={self.title})>"
