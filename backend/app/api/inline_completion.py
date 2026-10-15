"""行内补全接口：编辑器停笔时按光标前后正文给一小段灰色建议（SSE；直连流式、不进后台任务，浏览器断开即停）。

事件：suggestion{text=截至目前的完整建议}… → result{text} → done；失败只发 error（前端静默提示，不打断码字）。
"""
import anyio
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chapter_versions import load_owned_chapter
from app.api.settings import get_user_ai_service
from app.database import get_db
from app.logger import get_logger
from app.schemas.inline_completion import InlineCompletionRequest
from app.services.ai_service import AIService
from app.services.inline_completion_service import build_completion_prompt, load_completion_context, stream_completion
from app.utils.sse_response import SSEResponse, create_sse_response

router = APIRouter(prefix="/chapters", tags=["行内补全"])
logger = get_logger(__name__)
ERROR_CHARS = 200


@router.post("/{chapter_id}/inline-completion", summary="行内补全：按光标前后正文给一小段建议（SSE）")
async def inline_completion(
    chapter_id: str,
    body: InlineCompletionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service),
):
    chapter = await load_owned_chapter(db, chapter_id, request)
    ctx = await load_completion_context(db, chapter, prefix=body.prefix, suffix=body.suffix)
    prompt = build_completion_prompt(chapter=chapter, prefix=body.prefix, suffix=body.suffix, length=body.length, ctx=ctx)
    # 补全要快：本次请求一律不开思考；「补全模型」为空时传 None = 跟随（项目覆盖后的）主模型
    user_ai_service.reasoning_enabled = False
    model = getattr(user_ai_service, "completion_model", None) or None

    async def events():
        text = ""
        try:
            async for text in stream_completion(
                user_ai_service, prompt=prompt, prefix=body.prefix, length=body.length, model=model,
            ):
                yield SSEResponse.format_sse({"type": "suggestion", "text": text})
            yield await SSEResponse.send_result({"text": text})
            yield await SSEResponse.send_done()
        except Exception as exc:  # noqa: BLE001 - 补全失败只提示，不打断码字
            logger.warning(f"行内补全失败（第 {chapter.chapter_number} 章）: {exc}")
            yield await SSEResponse.send_error(str(exc)[:ERROR_CHARS] or "补全失败")
        finally:
            # 每次补全都新建了 AI 客户端：用完即关（浏览器断开时本协程已被取消，屏蔽取消才能关完）
            close = getattr(user_ai_service, "close", None)
            if close is not None:
                with anyio.CancelScope(shield=True):
                    await close()

    return create_sse_response(events())
