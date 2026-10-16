"""章节分析记录（plot_analysis）。

叙事事实结算进账本表（承诺 / 连续性信号 / 时间轴 / 因果 / 关系 / 已知信息），摘要与章末状态进 chapter_digests；
这里只留：分析时的正文指纹（判过期）、正文标注（钩子 / 伏笔 / 关键转折的原文引句）、出场人物变化、地点。
旧库的 plot_analysis 还有评分 / 建议等列：都是可空列，ORM 不再读写。旧版 story_memories 表不再有模型
（启动时摘要已拷进 chapter_digests），留在旧库里无害。
"""
import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String
from sqlalchemy.sql import func

from app.db_base import Base


class PlotAnalysis(Base):
    __tablename__ = "plot_analysis"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # 正文标注：[{title, note, quote, importance}]（quote 是原文引句，读取时按当前正文重新定位）
    hooks = Column(JSON, comment="钩子标注")
    foreshadows = Column(JSON, comment="伏笔标注")
    plot_points = Column(JSON, comment="关键转折标注")
    character_states = Column(JSON, comment="出场人物与本章变化: [{character_name, state_after}]")
    scenes = Column(JSON, comment="本章地点: [{location}]")

    content_hash = Column(String(64), nullable=True, comment="分析时的正文指纹")
    created_at = Column(DateTime, server_default=func.now(), comment="分析时间")

    def __repr__(self):
        return f"<PlotAnalysis(chapter_id={self.chapter_id[:8]})>"

    def annotation_items(self) -> list[dict]:
        """三类标注合成一个列表（兼容旧版结构：keyword / content / strength）。"""
        items: list[dict] = []
        for kind, rows in (("hook", self.hooks), ("foreshadow", self.foreshadows), ("plot_point", self.plot_points)):
            for index, row in enumerate(rows if isinstance(rows, list) else []):
                if not isinstance(row, dict):
                    continue
                quote = str(row.get("quote") or row.get("keyword") or "").strip()
                note = str(row.get("note") or row.get("content") or row.get("impact") or "").strip()
                title = str(row.get("title") or note[:12] or quote[:10]).strip()
                importance = row.get("importance")
                if importance is None and row.get("strength") is not None:
                    try:
                        importance = float(row["strength"]) / 10.0
                    except (TypeError, ValueError):
                        importance = None
                try:
                    importance = max(0.0, min(1.0, float(importance if importance is not None else 0.6)))
                except (TypeError, ValueError):
                    importance = 0.6
                items.append({"id": f"{self.chapter_id}:{kind}:{index}", "type": kind, "title": title, "note": note,
                              "quote": quote, "importance": importance})
        return items

    def to_dict(self):
        return {
            "id": self.id,
            "chapter_id": self.chapter_id,
            "annotations": self.annotation_items(),
            "character_states": self.character_states or [],
            "locations": [s.get("location") for s in (self.scenes or []) if isinstance(s, dict) and s.get("location")],
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
