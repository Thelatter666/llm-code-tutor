"""学生侧知识库只读端点（spec §6.2 knowledge 行）。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentRidDep, SessionDep, get_current_user
from app.core.responses import ok
from app.infrastructure.persistence.models import User
from app.schemas.common import ApiResponse
from app.schemas.knowledge import KnowledgeBaseOut, SearchOut
from app.services.knowledge_service import KnowledgeBaseService
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

UserDep = Annotated[User, Depends(get_current_user)]


@router.get("/bases", response_model=ApiResponse[Any])
async def list_bases(
    session: SessionDep,
    rid: CurrentRidDep,
    user: UserDep,
    course_code: str | None = None,
):
    """`course_code` 为空表示不限课程（spec §6.2）。"""
    bases = await KnowledgeBaseService(session).list_bases(course_code)
    return ok(
        [KnowledgeBaseOut.model_validate(b).model_dump() for b in bases], request_id=rid
    )


@router.get("/search", response_model=ApiResponse[Any])
async def search(
    session: SessionDep,
    rid: CurrentRidDep,
    query: Annotated[str, Query(min_length=1)],
    user: UserDep,
    kb_ids: Annotated[list[str] | None, Query()] = None,
    course_code: str | None = None,
    top_k: int | None = None,
):
    """spec §7.2 七步装配链路；KB 不存在 → 4040，未就绪 / 模型未加载 → 5032。"""
    result = await RetrievalService(session).search(
        query, kb_ids=kb_ids, course_code=course_code, top_k=top_k
    )
    return ok(SearchOut(**result.as_payload()).model_dump(), request_id=rid)
