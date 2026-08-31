"""code 域端点（spec §6.2 code 行）。

- `POST /code/analyze`：静态解析 + AI 讲解，固定 `review_my_code` 意图
  （ADR-0005：豁免是显式契约，端点就是那个显式入口）
- `POST /code/run`：受限执行（P4，spec §8.3）
- `/code/sessions`：编辑器代码会话 CRUD（P4）
- `GET /code/runs`：运行历史（P4）

**路由不含业务逻辑**，只做参数校验与序列化；并发上限、落库、审计都在
`CodeService` 里。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentRidDep, SessionDep, get_current_user
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.schemas.code import (
    CodeAnalysisOut,
    CodeAnalyzeIn,
    CodeRunHistoryItem,
    CodeRunIn,
    CodeRunOut,
    CodeSessionIn,
    CodeSessionOut,
    CodeSessionPatch,
)
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


# ---------------------------------------------------------------- 代码运行（P4）

@router.post("/run")
async def run_code(
    body: CodeRunIn, session: SessionDep, rid: CurrentRidDep, user: UserDep
):
    """受限执行（spec §8.3 / §6.2）。

    并发满时抛 `4290` 并带 `retry_after`（由 `CodeService` → `execution_slot()` 判定，
    **不无限排队**）。命中黑名单时 `status=blocked` 且代码不执行 —— 注意它仍是
    HTTP 200：对学生的输入做出反应是正常业务结果，不是服务端故障。
    """
    row = await CodeService(session).run(
        user_id=user.id,
        language=body.language,
        source=body.source,
        stdin=body.stdin,
        request_id=rid,
    )
    await session.commit()
    return ok(
        CodeRunOut(
            run_id=row.id,
            status=row.status,
            stdout=row.stdout,
            stderr=row.stderr,
            exit_code=row.exit_code,
            duration_ms=row.duration_ms,
            limit_detail=row.limit_detail,
        ).model_dump(),
        request_id=rid,
    )


@router.get("/runs")
async def list_runs(
    session: SessionDep,
    rid: CurrentRidDep,
    user: UserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """运行历史，最近一次在最前（spec §6.2 的分页约定：`{items, total}`）。"""
    rows, total = await CodeService(session).list_runs(
        user_id=user.id, page=page, page_size=page_size
    )
    return ok(
        {
            "items": [CodeRunHistoryItem.model_validate(r).model_dump() for r in rows],
            "total": total,
        },
        request_id=rid,
    )


# ---------------------------------------------------------------- 代码会话（P4）

@router.get("/sessions")
async def list_sessions(session: SessionDep, rid: CurrentRidDep, user: UserDep):
    drafts = await CodeService(session).list_drafts(user_id=user.id)
    return ok(
        {"items": [CodeSessionOut.model_validate(d).model_dump() for d in drafts]},
        request_id=rid,
    )


@router.post("/sessions")
async def create_session(
    body: CodeSessionIn, session: SessionDep, rid: CurrentRidDep, user: UserDep
):
    draft = await CodeService(session).create_draft(
        user_id=user.id,
        language=body.language,
        title=body.title,
        source_code=body.source_code,
    )
    await session.commit()
    return ok(CodeSessionOut.model_validate(draft).model_dump(), request_id=rid)


@router.patch("/sessions/{draft_id}")
async def update_session(
    draft_id: str, body: CodeSessionPatch, session: SessionDep, rid: CurrentRidDep, user: UserDep
):
    """越权（代码会话属于别人或不存在）一律 `4040` —— 不泄露「存在但不属于你」。"""
    draft = await CodeService(session).update_draft(
        user_id=user.id,
        draft_id=draft_id,
        title=body.title,
        source_code=body.source_code,
        language=body.language,
    )
    await session.commit()
    return ok(CodeSessionOut.model_validate(draft).model_dump(), request_id=rid)


@router.delete("/sessions/{draft_id}")
async def delete_session(
    draft_id: str, session: SessionDep, rid: CurrentRidDep, user: UserDep
):
    """删代码会话**不删**运行历史 —— `CodeRun` 与 `CodeSession` 之间没有外键，
    一次运行的留痕不该因为会话被删而消失。"""
    await CodeService(session).delete_draft(user_id=user.id, draft_id=draft_id)
    await session.commit()
    return ok({"id": draft_id}, request_id=rid)
