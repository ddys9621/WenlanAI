"""世界地图：作者标注的平面沙盘（坐标 0–100 百分比，不是经纬度）。底图由前端按 seed + 地形提示程序化绘制。"""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db_base import Base
import uuid


class WorldMap(Base):
    __tablename__ = "world_maps"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    seed = Column(Integer, nullable=False, comment="程序化底图随机种子")
    style = Column(String(30), nullable=False, default="paper-atlas")
    terrain_json = Column(Text, nullable=True, comment="地形提示：海岸方向 / 山脉 / 河流 / 区域名")
    candidate_json = Column(Text, nullable=True, comment="AI 生成、尚未采用的布局候选")
    revision = Column(Integer, nullable=False, default=0, comment="保存版本号（布局保存做乐观锁）")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class WorldMapLocation(Base):
    __tablename__ = "world_map_locations"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_world_map_location_name"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    x = Column(Float, nullable=True, comment="0–100；空 = 未定位")
    y = Column(Float, nullable=True)
    kind = Column(String(20), nullable=False, default="other")
    region = Column(String(100), nullable=True)
    description = Column(Text, nullable=True, comment="地点档案")
    source_names = Column(Text, nullable=True, comment="作者绑定的原文地点（JSON 列表，精确匹配）")
    origin = Column(String(10), nullable=False, default="author", comment="author / ai / rule")
    rule_id = Column(String(36), ForeignKey("world_rules.id", ondelete="SET NULL"), nullable=True, index=True,
                     comment="对应的世界规则「地图位置」；空 = 还没登记到世界规则")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
