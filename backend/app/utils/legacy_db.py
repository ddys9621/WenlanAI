"""2.0 不兼容 1.x 的数据库：启动时发现旧库就停下并说明怎么做。

不在旧库上建表 / 改表，旧数据原样留着：作者重新装回 1.x 还能接着写；要用 2.0 就换一个空的数据目录。
桌面版在启动画面显示这段说明（start_app.check_database_connection），服务端版写进 /health/ready。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

# 1.x 才有的表（剧情线 / 桥段）；没有这些表但章纲缺 volume_id 的也是 1.x 的库
LEGACY_TABLES = frozenset({"plot_lines", "plot_bridges", "chapter_outline_plot_line_links", "plot_card_plot_line_links"})

LEGACY_DB_MESSAGE = (
    "检测到 1.x 版本的数据库（data\\mumuai.db）。文澜 AI 2.0 不兼容旧版数据，为保护你的数据已停止启动，旧库没有被改动。"
    "要继续写旧书，请重新安装 1.x 版本；要使用 2.0，请先把 data 文件夹整个备份到别处，"
    "再删除或改名其中的 mumuai.db 后重新打开（会新建一个空库，旧项目不会带过来）。"
)


def legacy_schema_reason(conn: Connection) -> Optional[str]:
    """同步连接上检查（配合 AsyncConnection.run_sync）：是 1.x 的库返回说明文字，否则 None。"""
    insp = inspect(conn)
    tables = set(insp.get_table_names())
    if tables & LEGACY_TABLES:
        return LEGACY_DB_MESSAGE
    if "chapter_outlines" in tables and "volume_id" not in {c["name"] for c in insp.get_columns("chapter_outlines")}:
        return LEGACY_DB_MESSAGE
    return None
