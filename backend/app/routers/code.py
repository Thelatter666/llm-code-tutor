"""代码解析与辅导端点（spec §6.2 code 行）。

`POST /code/analyze`：静态解析 + AI 讲解，**固定 `review_my_code` 意图**
（ADR-0005：豁免是显式契约，端点就是那个显式入口）。

CodeSession / CodeRun 的 CRUD 归 P4（在线编辑器批次），本路由不涉及。
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import CurrentRidDep, SessionDep, get_current_user
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.schemas.code import CodeAnalysisOut, CodeAnalyzeIn
from app.services.code_service import CodeService

router = APIRouter(prefix="/api/v1/code", tags=["code"])

UserDep = Annotated[User, Depends(get_current_user)]


@router.post("/analyze")
async def analyze_code(
    body: CodeAnalyzeIn, session: SessionDep, rid: CurrentRidDep, user: UserDep
):
    """评改已写代码：静态报告 + AI 讲解。

    `source_hash` 命中该用户历史则复用（`reused=true`），不重复解析与生成。
    """
    row, reused = await CodeService(session).analyze(
        user_id=user.id, language=body.language, source=body.source, request_id=rid
    )
    await session.commit()
    return ok(
        CodeAnalysisOut(
            analysis_id=row.id,
            language=row.language,
            static_report=row.static_report,
            ai_report=row.ai_report,
            reused=reused,
        ).model_dump(),
        request_id=rid,
    )
