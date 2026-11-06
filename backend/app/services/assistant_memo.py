"""共创室 · 作品备忘：作者的长期偏好、拍板了的约定、要避开的写法。

- 每轮开跑都放进上下文（成员接手时也带上），开新对话不丢——前情摘要只管一段对话，备忘管整本书
- 作者在面板里写 / 改 / 删；团队听到长期偏好时用 remember 记一条（run_id 记下是哪一轮，撤销本轮时一并删掉）
- 一条一句话；同样的话不重复记；条数和总字数有上限，装进上下文时超了就只带最近的
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantMemo
from app.services.assistant_persistence import write_verified

ITEM_LIMIT = 200
MAX_ITEMS = 60
PROMPT_LIMIT = 3000


class MemoError(ValueError):
    """备忘写不进去（空的 / 太多条 / 不存在）：消息直接给作者或模型看。"""


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _clean(content: str) -> str:
    text = " ".join(str(content or "").split())
    if not text:
        raise MemoError("备忘内容不能为空")
    return text[:ITEM_LIMIT]


async def list_memos(db: AsyncSession, project_id: str) -> list[AssistantMemo]:
    return list((await db.execute(
        select(AssistantMemo).where(AssistantMemo.project_id == project_id).order_by(AssistantMemo.created_at)
        .execution_options(populate_existing=True)
    )).scalars().all())


def memo_view(memo: AssistantMemo) -> dict:
    return {"id": memo.id, "content": memo.content, "source": memo.source, "member_id": memo.member_id,
            "run_id": memo.run_id, "created_at": memo.created_at.isoformat() if memo.created_at else None}


async def add_memo(db: AsyncSession, project_id: str, content: str, *, source: str = "author",
                   member_id: Optional[str] = None, run_id: Optional[str] = None) -> tuple[AssistantMemo, bool]:
    """记一条；同样的话已经有了就返回那条（created=False）。提交后读回核对（所有会话共用一个 SQLite 连接）。"""
    text = _clean(content)
    rows = await list_memos(db, project_id)
    same = next((m for m in rows if _norm(m.content) == _norm(text)), None)
    if same is not None:
        return same, False
    if len(rows) >= MAX_ITEMS:
        raise MemoError(f"作品备忘已经有 {MAX_ITEMS} 条了：先在备忘里删掉过时的再记")
    memo_id = str(uuid.uuid4())

    async def write() -> None:
        if await db.get(AssistantMemo, memo_id) is None:
            db.add(AssistantMemo(id=memo_id, project_id=project_id, content=text, source=source, member_id=member_id,
                                 run_id=run_id))

    async def verify() -> bool:
        db.expire_all()
        return bool(await db.scalar(select(AssistantMemo.id).where(AssistantMemo.id == memo_id)))

    await write_verified(db, write, verify, "作品备忘")
    return await db.get(AssistantMemo, memo_id), True


async def _memo(db: AsyncSession, project_id: str, memo_id: str) -> AssistantMemo:
    memo = await db.get(AssistantMemo, memo_id)
    if memo is None or memo.project_id != project_id:
        raise MemoError("这条备忘不存在（可能已经删了）")
    return memo


async def update_memo(db: AsyncSession, project_id: str, memo_id: str, content: str) -> AssistantMemo:
    memo = await _memo(db, project_id, memo_id)
    memo.content = _clean(content)
    await db.commit()
    return memo


async def delete_memo(db: AsyncSession, project_id: str, memo_id: str) -> None:
    await db.delete(await _memo(db, project_id, memo_id))
    await db.commit()


def memo_text(rows: list[AssistantMemo]) -> str:
    """装进上下文的备忘：一条一行；超了总字数就只带最近的（作者写的和团队记的一视同仁，按时间）。"""
    lines: list[str] = []
    used = 0
    for memo in reversed(rows):
        line = f"- {memo.content}"
        if used + len(line) > PROMPT_LIMIT:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(reversed(lines))
