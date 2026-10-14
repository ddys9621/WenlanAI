"""世界地图请求模型：坐标是 0–100 的平面百分比。"""
from typing import List, Optional

from pydantic import BaseModel, Field

LOCATION_KINDS = ("city", "town", "village", "sect", "palace", "mountain", "forest", "river", "lake", "sea",
                  "desert", "ruin", "pass", "island", "other")


class MarkerInput(BaseModel):
    id: Optional[str] = Field(None, description="已有地点 ID；不传按名字找，找不到就新建")
    name: str = Field(..., min_length=1, max_length=100)
    x: float = Field(..., ge=0, le=100)
    y: float = Field(..., ge=0, le=100)


class LayoutSaveRequest(BaseModel):
    expected_revision: int = Field(..., ge=0, description="读取时的版本号；不一致说明别处改过，拒绝覆盖")
    markers: List[MarkerInput] = Field(default_factory=list, max_length=2000)


class LocationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    x: Optional[float] = Field(None, ge=0, le=100)
    y: Optional[float] = Field(None, ge=0, le=100)
    kind: str = Field("other", max_length=20)
    region: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=4000)
    source_names: Optional[List[str]] = Field(None, max_length=256)


class LocationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    x: Optional[float] = Field(None, ge=0, le=100)
    y: Optional[float] = Field(None, ge=0, le=100)
    kind: Optional[str] = Field(None, max_length=20)
    region: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=4000)
    source_names: Optional[List[str]] = Field(None, max_length=256)
    clear_position: bool = Field(False, description="取消定位（放回未定位列表）")


class RegisterRulesRequest(BaseModel):
    location_ids: Optional[List[str]] = Field(None, max_length=2000, description="要登记的地点；不传 = 全部未登记的地点")


class CandidateAdoptRequest(BaseModel):
    replace_positions: bool = Field(False, description="同名地点也改成候选里的坐标（默认不挪动作者已放好的地点）")


class MapSettingsUpdate(BaseModel):
    seed: Optional[int] = Field(None, ge=0, le=2_147_483_647, description="换一张程序化底图")
    style: Optional[str] = Field(None, max_length=30)
