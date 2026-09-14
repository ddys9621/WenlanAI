"""Auto migration utilities to keep DB schema in sync on startup."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.logger import get_logger

logger = get_logger(__name__)


async def column_exists(conn, table: str, column: str) -> bool:
    result = await conn.execute(
        text(f"PRAGMA table_info({table})")
    )
    rows = result.fetchall()
    return any(row.name == column for row in rows)


async def apply_sql(conn, statements: Iterable[str]):
    for stmt in statements:
        logger.info("📄 Executing migration SQL: %s", stmt.split("\n", 1)[0])
        await conn.execute(text(stmt))


async def ensure_chapter_outline_columns(engine: AsyncEngine):
    """Ensure chapter_outline_id columns exist on chapters and plot_cards."""
    async with engine.begin() as conn:
        # chapters table
        if not await column_exists(conn, "chapters", "chapter_outline_id"):
            logger.info("🔧 Adding chapters.chapter_outline_id column")
            await apply_sql(conn, [
                """ALTER TABLE chapters
                ADD COLUMN chapter_outline_id VARCHAR(36) NULL""",
                """CREATE INDEX IF NOT EXISTS idx_chapters_chapter_outline_id
                ON chapters (chapter_outline_id)""",
            ])
            try:
                await conn.execute(text(
                    """ALTER TABLE chapters
                    ADD CONSTRAINT fk_chapters_chapter_outline
                    FOREIGN KEY (chapter_outline_id)
                    REFERENCES chapter_outlines (id)
                    ON DELETE SET NULL"""
                ))
            except Exception:
                pass  # SQLite does not support ADD CONSTRAINT in ALTER TABLE
        else:
            logger.info("✅ chapters.chapter_outline_id already exists")

        # plot_cards table
        if not await column_exists(conn, "plot_cards", "chapter_outline_id"):
            logger.info("🔧 Adding plot_cards.chapter_outline_id column")
            await apply_sql(conn, [
                """ALTER TABLE plot_cards
                ADD COLUMN chapter_outline_id VARCHAR(36) NULL""",
                """CREATE INDEX IF NOT EXISTS idx_plot_cards_chapter_outline_id
                ON plot_cards (chapter_outline_id)""",
            ])
            try:
                await conn.execute(text(
                    """ALTER TABLE plot_cards
                    ADD CONSTRAINT fk_plot_cards_chapter_outline
                    FOREIGN KEY (chapter_outline_id)
                    REFERENCES chapter_outlines (id)
                    ON DELETE SET NULL"""
                ))
            except Exception:
                pass  # SQLite does not support ADD CONSTRAINT in ALTER TABLE
        else:
            logger.info("✅ plot_cards.chapter_outline_id already exists")


async def ensure_story_outline_columns(engine: AsyncEngine):
    """Ensure new columns exist on story_outlines table."""
    async with engine.begin() as conn:
        if not await column_exists(conn, "story_outlines", "status"):
            logger.info("🔧 Adding story_outlines.status column")
            await apply_sql(conn, [
                """ALTER TABLE story_outlines
                ADD COLUMN status VARCHAR(20) DEFAULT 'published'""",
                """UPDATE story_outlines
                SET status = 'published'
                WHERE status IS NULL""",
            ])
        else:
            logger.info("✅ story_outlines.status already exists")

        if not await column_exists(conn, "story_outlines", "editor_id"):
            logger.info("🔧 Adding story_outlines.editor_id column")
            await apply_sql(conn, [
                """ALTER TABLE story_outlines
                ADD COLUMN editor_id VARCHAR(36)""",
            ])
        else:
            logger.info("✅ story_outlines.editor_id already exists")



async def ensure_plot_line_link_columns(engine: AsyncEngine):
    """Ensure new columns exist on chapter_outline_plot_line_links table."""
    async with engine.begin() as conn:
        if not await column_exists(conn, "chapter_outline_plot_line_links", "timeline_coverage"):
            logger.info("🔧 Adding chapter_outline_plot_line_links.timeline_coverage column")
            await apply_sql(conn, [
                """ALTER TABLE chapter_outline_plot_line_links
                ADD COLUMN timeline_coverage TEXT""",
            ])
        else:
            logger.info("✅ chapter_outline_plot_line_links.timeline_coverage already exists")


async def ensure_plot_line_columns(engine: AsyncEngine):
    """Ensure new columns exist on plot_lines table."""
    async with engine.begin() as conn:
        if not await column_exists(conn, "plot_lines", "estimated_chapters"):
            logger.info("🔧 Adding plot_lines.estimated_chapters column")
            await apply_sql(conn, [
                """ALTER TABLE plot_lines
                ADD COLUMN estimated_chapters INTEGER""",
            ])
            try:
                await conn.execute(text(
                    """COMMENT ON COLUMN plot_lines.estimated_chapters IS '预计章节数：完成这条剧情线预计需要的章节数量'"""
                ))
            except Exception:
                pass  # SQLite does not support COMMENT ON COLUMN
            # 为已有数据设置默认值
            logger.info("🔧 Setting default values for existing plot_lines")
            await apply_sql(conn, [
                """UPDATE plot_lines
                SET estimated_chapters = CASE
                    WHEN line_type = 'main' THEN 40
                    WHEN line_type = 'sub' THEN 15
                    ELSE 8
                END
                WHERE estimated_chapters IS NULL""",
            ])
        else:
            logger.info("✅ plot_lines.estimated_chapters already exists")


async def ensure_chapter_outline_scene_pov_columns(engine: AsyncEngine):
    """Ensure scene and pov columns exist on chapter_outlines table (专业网文版升级)."""
    async with engine.begin() as conn:
        # scene 字段
        if not await column_exists(conn, "chapter_outlines", "scene"):
            logger.info("🔧 Adding chapter_outlines.scene column (专业网文版)")
            await apply_sql(conn, [
                """ALTER TABLE chapter_outlines
                ADD COLUMN scene VARCHAR(200)""",
            ])
            try:
                await conn.execute(text(
                    """COMMENT ON COLUMN chapter_outlines.scene IS '场景地点，如拳击场→后台'"""
                ))
            except Exception:
                pass  # SQLite does not support COMMENT ON COLUMN
        else:
            logger.info("✅ chapter_outlines.scene already exists")

        # pov 字段
        if not await column_exists(conn, "chapter_outlines", "pov"):
            logger.info("🔧 Adding chapter_outlines.pov column (专业网文版)")
            await apply_sql(conn, [
                """ALTER TABLE chapter_outlines
                ADD COLUMN pov VARCHAR(100)""",
            ])
            try:
                await conn.execute(text(
                    """COMMENT ON COLUMN chapter_outlines.pov IS '视角角色名'"""
                ))
            except Exception:
                pass  # SQLite does not support COMMENT ON COLUMN
        else:
            logger.info("✅ chapter_outlines.pov already exists")


async def ensure_plot_cards_scene_columns(engine: AsyncEngine):
    """Ensure scene generation columns exist on plot_cards table (场景级创作循环)."""
    async with engine.begin() as conn:
        # generation_status 字段
        if not await column_exists(conn, "plot_cards", "generation_status"):
            logger.info("🔧 Adding plot_cards.generation_status column (场景级创作)")
            await apply_sql(conn, [
                """ALTER TABLE plot_cards
                ADD COLUMN generation_status VARCHAR(20) DEFAULT 'pending'""",
            ])
        else:
            logger.info("✅ plot_cards.generation_status already exists")

        # generated_content 字段
        if not await column_exists(conn, "plot_cards", "generated_content"):
            logger.info("🔧 Adding plot_cards.generated_content column (场景级创作)")
            await apply_sql(conn, [
                """ALTER TABLE plot_cards
                ADD COLUMN generated_content TEXT""",
            ])
        else:
            logger.info("✅ plot_cards.generated_content already exists")

        # word_count_target 字段
        if not await column_exists(conn, "plot_cards", "word_count_target"):
            logger.info("🔧 Adding plot_cards.word_count_target column (场景级创作)")
            await apply_sql(conn, [
                """ALTER TABLE plot_cards
                ADD COLUMN word_count_target INTEGER DEFAULT 500""",
            ])
        else:
            logger.info("✅ plot_cards.word_count_target already exists")

        # word_count_actual 字段
        if not await column_exists(conn, "plot_cards", "word_count_actual"):
            logger.info("🔧 Adding plot_cards.word_count_actual column (场景级创作)")
            await apply_sql(conn, [
                """ALTER TABLE plot_cards
                ADD COLUMN word_count_actual INTEGER DEFAULT 0""",
            ])
        else:
            logger.info("✅ plot_cards.word_count_actual already exists")

        # generation_order 字段
        if not await column_exists(conn, "plot_cards", "generation_order"):
            logger.info("🔧 Adding plot_cards.generation_order column (场景级创作)")
            await apply_sql(conn, [
                """ALTER TABLE plot_cards
                ADD COLUMN generation_order INTEGER DEFAULT 0""",
            ])
        else:
            logger.info("✅ plot_cards.generation_order already exists")


async def ensure_book_dissect_v2_columns(engine: AsyncEngine):
    """Ensure V2 columns exist on book_dissect_tasks table.

    V2 字段：
    - version (int, default=1)
    - extraction_phase (varchar 50)
    - chapters_total / chapters_extracted / chapters_failed (int, default=0)
    - sampling_mode (varchar 20, default='all')
    - sampling_param (int, default=1)
    """
    v2_columns = [
        ("version", "INTEGER DEFAULT 1"),
        ("extraction_phase", "VARCHAR(50)"),
        ("chapters_total", "INTEGER DEFAULT 0"),
        ("chapters_extracted", "INTEGER DEFAULT 0"),
        ("chapters_failed", "INTEGER DEFAULT 0"),
        ("sampling_mode", "VARCHAR(20) DEFAULT 'all'"),
        ("sampling_param", "INTEGER DEFAULT 1"),
    ]

    async with engine.begin() as conn:
        for col_name, col_def in v2_columns:
            if not await column_exists(conn, "book_dissect_tasks", col_name):
                logger.info("🔧 Adding book_dissect_tasks.%s column (V2)", col_name)
                await apply_sql(conn, [
                    f"ALTER TABLE book_dissect_tasks ADD COLUMN {col_name} {col_def}",
                ])
            else:
                logger.info("✅ book_dissect_tasks.%s already exists", col_name)

        # 既有任务统一标记为 V1（version=1 是默认值，但显式刷一次确保正确）
        await apply_sql(conn, [
            "UPDATE book_dissect_tasks SET version = 1 WHERE version IS NULL",
        ])


async def ensure_book_dissect_v31_columns(engine: AsyncEngine):
    """Ensure V3.1 columns exist on book_dissect_tasks table.

    V3.1 字段：
    - extraction_engine (varchar 20, default='auto')
      路由策略：auto(由 LongContextRouter 决定) / chunked(强制逐章) / long_context(强制一次性)
    """
    v31_columns = [
        ("extraction_engine", "VARCHAR(20) DEFAULT 'auto'"),
    ]

    async with engine.begin() as conn:
        for col_name, col_def in v31_columns:
            if not await column_exists(conn, "book_dissect_tasks", col_name):
                logger.info("🔧 Adding book_dissect_tasks.%s column (V3.1)", col_name)
                await apply_sql(conn, [
                    f"ALTER TABLE book_dissect_tasks ADD COLUMN {col_name} {col_def}",
                ])
            else:
                logger.info("✅ book_dissect_tasks.%s already exists", col_name)


async def ensure_book_dissect_batch_columns(engine: AsyncEngine):
    """Ensure 分批抽取 columns exist on book_dissect_tasks table.

    - chapters_per_request (int, default=0)：每次 LLM 请求抽取的章节数，0 = 自动规划
    - chapter_limit (int, default=0)：只抽取前 N 章，0 = 全部
    """
    batch_columns = [
        ("chapters_per_request", "INTEGER DEFAULT 0"),
        ("chapter_limit", "INTEGER DEFAULT 0"),
    ]

    async with engine.begin() as conn:
        for col_name, col_def in batch_columns:
            if not await column_exists(conn, "book_dissect_tasks", col_name):
                logger.info("🔧 Adding book_dissect_tasks.%s column (分批抽取)", col_name)
                await apply_sql(conn, [
                    f"ALTER TABLE book_dissect_tasks ADD COLUMN {col_name} {col_def}",
                ])
            else:
                logger.info("✅ book_dissect_tasks.%s already exists", col_name)


async def ensure_reference_pack_v32_columns(engine: AsyncEngine):
    """Ensure V3.2 columns exist on reference_packs table.

    V3.2 字段（synopsis 复活 + V3.2-P2 模式三维度）：
    - synopsis_json (TEXT, NULL) Tab6 故事类型骨架（Story Bible）
    - entities_json / relations_json / events_json (TEXT, NULL) V3.2-P2 聚合模式三维度
      见 @/agent-docs/features/dissect_to_creation_pipeline.md §A.6 / §A.7
    """
    v32_columns = [
        ("synopsis_json", "TEXT NULL"),
        # V3.2-P2：聚合模式三维度（不调 LLM，从 V2 表纯统计聚合产出）
        ("entities_json", "TEXT NULL"),
        ("relations_json", "TEXT NULL"),
        ("events_json", "TEXT NULL"),
    ]

    async with engine.begin() as conn:
        for col_name, col_def in v32_columns:
            if not await column_exists(conn, "reference_packs", col_name):
                logger.info("🔧 Adding reference_packs.%s column (V3.2)", col_name)
                await apply_sql(conn, [
                    f"ALTER TABLE reference_packs ADD COLUMN {col_name} {col_def}",
                ])
            else:
                logger.info("✅ reference_packs.%s already exists", col_name)


async def ensure_project_generation_prompt_column(engine: AsyncEngine):
    """Ensure project-level generation prompt adjustment exists."""
    async with engine.begin() as conn:
        if not await column_exists(conn, "projects", "generation_prompt"):
            logger.info("🔧 Adding projects.generation_prompt column")
            await apply_sql(conn, [
                """ALTER TABLE projects
                ADD COLUMN generation_prompt TEXT""",
            ])
        else:
            logger.info("✅ projects.generation_prompt already exists")


async def ensure_project_bridge_planning_column(engine: AsyncEngine):
    """Ensure F3 projects.enable_bridge_planning column exists (T2.1 prereq).

    场景：旧 DB 升级到引入桥段规划阶段（step 3.5）的版本。默认 True，
    确保新拆书向导自动进入桥段规划；用户可在前端关闭以走传统线性章纲路径。
    """
    async with engine.begin() as conn:
        if not await column_exists(conn, "projects", "enable_bridge_planning"):
            logger.info("🔧 Adding projects.enable_bridge_planning column (F3/T2.1)")
            await apply_sql(conn, [
                """ALTER TABLE projects
                ADD COLUMN enable_bridge_planning BOOLEAN NOT NULL DEFAULT 1""",
            ])
        else:
            logger.info("✅ projects.enable_bridge_planning already exists")


async def ensure_plot_bridge_beat_columns(engine: AsyncEngine):
    """Ensure V4.1 K2 分层契合字段在 plot_bridges 表存在（方案 C 前置）。

    新增 3 列：
    - beat_index INTEGER NULL  所属节点 index（对应 PlotLine.timeline_data.beats[].index）
    - beat_coverage_start REAL NULL  本桥段覆盖该节点的起始进度（0.0-1.0）
    - beat_coverage_end   REAL NULL  本桥段覆盖该节点的结束进度（0.0-1.0）

    场景：旧 DB 升级到引入「桥段按主线节点分配」的版本。所有列都允许 NULL，
    free 模式（不绑节点）旧桥段记录无影响。
    """
    beat_columns = [
        ("beat_index", "INTEGER"),
        ("beat_coverage_start", "REAL"),
        ("beat_coverage_end", "REAL"),
    ]
    async with engine.begin() as conn:
        for col_name, col_def in beat_columns:
            if not await column_exists(conn, "plot_bridges", col_name):
                logger.info("🔧 Adding plot_bridges.%s column (V4.1 方案 C)", col_name)
                await apply_sql(conn, [
                    f"ALTER TABLE plot_bridges ADD COLUMN {col_name} {col_def}",
                ])
            else:
                logger.info("✅ plot_bridges.%s already exists", col_name)


async def ensure_plot_bridge_secondary_beats_column(engine: AsyncEngine):
    """Ensure plot_bridges.secondary_beats exists（工程化桥段流水线：副线任务挂载）。"""
    async with engine.begin() as conn:
        if not await column_exists(conn, "plot_bridges", "secondary_beats"):
            logger.info("🔧 Adding plot_bridges.secondary_beats column (工程化桥段流水线)")
            await apply_sql(conn, [
                "ALTER TABLE plot_bridges ADD COLUMN secondary_beats TEXT",
            ])
        else:
            logger.info("✅ plot_bridges.secondary_beats already exists")


async def ensure_plot_bridge_generation_meta_column(engine: AsyncEngine):
    """Ensure plot_bridges.generation_meta exists（桥段填充 provenance，nullable TEXT）。"""
    async with engine.begin() as conn:
        if not await column_exists(conn, "plot_bridges", "generation_meta"):
            logger.info("🔧 Adding plot_bridges.generation_meta column (桥段填充溯源)")
            await apply_sql(conn, [
                "ALTER TABLE plot_bridges ADD COLUMN generation_meta TEXT",
            ])
        else:
            logger.info("✅ plot_bridges.generation_meta already exists")


async def ensure_project_c3_hook_style_column(engine: AsyncEngine):
    """Ensure projects.c3_hook_style exists（C3 兑现章末尾：none 不留钩子 / soft 半钩；默认 none 保持现状）。"""
    async with engine.begin() as conn:
        if not await column_exists(conn, "projects", "c3_hook_style"):
            logger.info("🔧 Adding projects.c3_hook_style column (C3 章末风格开关)")
            await apply_sql(conn, [
                "ALTER TABLE projects ADD COLUMN c3_hook_style VARCHAR(20) DEFAULT 'none'",
            ])
        else:
            logger.info("✅ projects.c3_hook_style already exists")


async def ensure_plot_bridge_payoff_type_column(engine: AsyncEngine):
    """Ensure plot_bridges.payoff_type exists（兑现方式枚举，nullable VARCHAR(40)；账本按类型统计避免长线套路重复）。"""
    async with engine.begin() as conn:
        if not await column_exists(conn, "plot_bridges", "payoff_type"):
            logger.info("🔧 Adding plot_bridges.payoff_type column (兑现方式枚举)")
            await apply_sql(conn, [
                "ALTER TABLE plot_bridges ADD COLUMN payoff_type VARCHAR(40)",
            ])
        else:
            logger.info("✅ plot_bridges.payoff_type already exists")


async def ensure_character_aliases_column(engine: AsyncEngine):
    """Ensure characters.aliases exists（角色曾用名，改名时自动追加旧名）。

    场景：旧 DB 升级到「角色改名级联 + 曾用名兜底匹配」的版本。nullable TEXT，零数据迁移风险。
    """
    async with engine.begin() as conn:
        if not await column_exists(conn, "characters", "aliases"):
            logger.info("🔧 Adding characters.aliases column (角色曾用名)")
            await apply_sql(conn, [
                """ALTER TABLE characters
                ADD COLUMN aliases TEXT""",
            ])
        else:
            logger.info("✅ characters.aliases already exists")


async def ensure_users_email_column(engine: AsyncEngine):
    """Ensure users.email exists（邮箱注册用户的登录标识，nullable + 唯一索引）。

    场景：旧 DB 升级到「Linux.do / 邮箱登录后台开关」版本。SQLite 唯一索引允许多个 NULL，
    老用户（本地 / 管理员创建 / Linux.do）email 为空互不冲突。
    """
    async with engine.begin() as conn:
        if not await column_exists(conn, "users", "email"):
            logger.info("🔧 Adding users.email column (邮箱注册用户)")
            await apply_sql(conn, [
                "ALTER TABLE users ADD COLUMN email VARCHAR(200)",
            ])
        else:
            logger.info("✅ users.email already exists")
        await apply_sql(conn, [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (email)",
        ])


REFERENCE_PACK_V4_COLUMNS: tuple[tuple[str, str], ...] = (
    ("bridges_json", "TEXT"),
    ("character_archive_json", "TEXT"),
    *(
        (f"{dim}_{tier}", "TEXT")
        for dim in ("methodology", "style", "structure", "archetypes", "worldbuilding", "synopsis", "bridges", "character_archive")
        for tier in ("light", "medium", "deep")
    ),
)

CHAPTER_OUTLINE_BRIDGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("bridge_id", "VARCHAR(36)"),
    ("bridge_position", "VARCHAR(20)"),
    ("position_constraints", "TEXT"),
)


async def _ensure_columns(engine: AsyncEngine, table: str, columns: tuple[tuple[str, str], ...], tag: str):
    async with engine.begin() as conn:
        for col_name, col_def in columns:
            if not await column_exists(conn, table, col_name):
                logger.info("🔧 Adding %s.%s column (%s)", table, col_name, tag)
                await apply_sql(conn, [f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"])


async def ensure_reference_pack_v4_columns(engine: AsyncEngine):
    """V4 P0-5：reference_packs 的 2 个 V4.1 维度 JSON + 24 个 K5 三档预压缩列（原 v4_phase0 手工脚本）。"""
    await _ensure_columns(engine, "reference_packs", REFERENCE_PACK_V4_COLUMNS, "V4 P0-5")


REFERENCE_PACK_V5_COLUMNS: tuple[tuple[str, str], ...] = (
    ("pipeline_version", "INTEGER NOT NULL DEFAULT 2"),
)


async def ensure_book_dissect_v5_columns(engine: AsyncEngine):
    """拆书 V5：reference_packs.pipeline_version（老包保持 2，新包写 5）。story_arcs 新表由 create_all 建。"""
    await _ensure_columns(engine, "reference_packs", REFERENCE_PACK_V5_COLUMNS, "拆书 V5")


async def ensure_chapter_outline_bridge_columns(engine: AsyncEngine):
    """V4 P2-1：chapter_outlines 的桥段三列（原 v4_phase2 手工脚本；plot_bridges 表由 create_all 建）。"""
    await _ensure_columns(engine, "chapter_outlines", CHAPTER_OUTLINE_BRIDGE_COLUMNS, "V4 P2-1")


PROJECT_ID_INDEX_TABLES: tuple[str, ...] = (
    "chapters", "chapter_outlines", "plot_lines", "plot_cards", "characters",
    "story_outlines", "generation_history", "writing_styles", "project_default_styles",
)


async def ensure_settings_reasoning_columns(engine: AsyncEngine):
    """Ensure thinking/reasoning columns exist on settings table（思考强度全局设置）。

    新增 3 列（旧库升级，均带默认值/可空，零数据迁移风险）：
    - reasoning_enabled BOOLEAN NOT NULL DEFAULT 0  是否启用思考/推理
    - reasoning_effort  VARCHAR(20) DEFAULT 'medium' 统一档位 / OpenAI reasoning_effort
    - thinking_budget_tokens INTEGER NULL           Anthropic budget_tokens（空=按档位自动）
    """
    reasoning_columns = [
        ("reasoning_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
        ("reasoning_effort", "VARCHAR(20) DEFAULT 'medium'"),
        ("thinking_budget_tokens", "INTEGER"),
    ]
    async with engine.begin() as conn:
        for col_name, col_def in reasoning_columns:
            if not await column_exists(conn, "settings", col_name):
                logger.info("🔧 Adding settings.%s column (思考强度)", col_name)
                await apply_sql(conn, [
                    f"ALTER TABLE settings ADD COLUMN {col_name} {col_def}",
                ])
            else:
                logger.info("✅ settings.%s already exists", col_name)


async def ensure_settings_sampling_columns(engine: AsyncEngine):
    """Ensure sampling diversity columns exist on settings table（降低 AI 味 / 困惑度检测）。

    新增 3 列（旧库升级，均带默认值，零数据迁移风险）：
    - top_p             REAL DEFAULT 0.95  核采样
    - frequency_penalty REAL DEFAULT 0.3   频率惩罚（抑制重复用词）
    - presence_penalty  REAL DEFAULT 0.3   存在惩罚（鼓励新词/话题）
    """
    sampling_columns = [
        ("top_p", "REAL DEFAULT 0.95"),
        ("frequency_penalty", "REAL DEFAULT 0.3"),
        ("presence_penalty", "REAL DEFAULT 0.3"),
    ]
    async with engine.begin() as conn:
        for col_name, col_def in sampling_columns:
            if not await column_exists(conn, "settings", col_name):
                logger.info("🔧 Adding settings.%s column (采样多样性)", col_name)
                await apply_sql(conn, [
                    f"ALTER TABLE settings ADD COLUMN {col_name} {col_def}",
                ])
            else:
                logger.info("✅ settings.%s already exists", col_name)


async def ensure_project_id_indexes(engine: AsyncEngine):
    """热表 project_id 索引：几乎所有查询都按 project_id 过滤，旧库此前全表扫描。

    索引名与 SQLAlchemy `index=True` 的默认命名（ix_<table>_<column>）一致，新库 create_all 已建，此处 IF NOT EXISTS 幂等。
    """
    async with engine.begin() as conn:
        for table in PROJECT_ID_INDEX_TABLES:
            await conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_project_id ON {table} (project_id)"))


async def run_auto_migrations(engine: AsyncEngine):
    try:
        await ensure_users_email_column(engine)  # 登录方式后台开关：邮箱注册用户
        await ensure_chapter_outline_columns(engine)
        await ensure_story_outline_columns(engine)
        await ensure_plot_line_link_columns(engine)
        await ensure_plot_line_columns(engine)
        await ensure_chapter_outline_scene_pov_columns(engine)  # 专业网文版字段
        await ensure_plot_cards_scene_columns(engine)  # 场景级创作循环字段
        await ensure_book_dissect_v2_columns(engine)  # 拆书 V2 字段
        await ensure_book_dissect_v31_columns(engine)  # 拆书 V3.1 字段
        await ensure_book_dissect_batch_columns(engine)  # 拆书分批抽取：每批章数 / 截取前 N 章
        await ensure_reference_pack_v32_columns(engine)  # 拆书 V3.2 synopsis 复活
        await ensure_reference_pack_v4_columns(engine)  # V4 P0-5：维度 JSON + 三档预压缩列
        await ensure_book_dissect_v5_columns(engine)  # 拆书 V5：pipeline_version
        await ensure_project_generation_prompt_column(engine)
        await ensure_project_bridge_planning_column(engine)  # F3：桥段规划开关（T2.1 前置）
        await ensure_chapter_outline_bridge_columns(engine)  # V4 P2-1：章纲桥段三列
        await ensure_plot_bridge_beat_columns(engine)  # V4.1 方案 C：桥段绑定剧情线节点
        await ensure_plot_bridge_secondary_beats_column(engine)  # 工程化桥段流水线：副线任务
        await ensure_plot_bridge_generation_meta_column(engine)  # 桥段填充溯源
        await ensure_plot_bridge_payoff_type_column(engine)  # 兑现方式枚举（账本全书统计）
        await ensure_project_c3_hook_style_column(engine)  # C3 章末风格开关（默认不留钩子）
        await ensure_character_aliases_column(engine)  # 角色曾用名（改名级联兜底）
        await ensure_settings_reasoning_columns(engine)  # 思考强度全局设置字段
        await ensure_settings_sampling_columns(engine)  # 采样多样性字段（降低 AI 味）
        await ensure_project_id_indexes(engine)  # 热表 project_id 索引（旧库补建）
        logger.info("✅ Auto migrations finished")
    except Exception as exc:
        logger.error("❌ Auto migrations failed: %s", exc, exc_info=True)
        # Do not stop startup, but surface the error to logs
