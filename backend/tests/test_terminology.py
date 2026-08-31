"""M-5 术语锁：CodeSession 的用户可见文案零「草稿」（CONTEXT.md 禁词纪律）。

边界（清理批次裁定 R3）：禁词限定于 CodeSession 实体；Exercise.status 的
「草稿」发布态标签是另一实体，不在本锁范围。标识符（create_draft 等）不动。

C4 变异击杀前提：把「未命名会话」改回「未命名草稿」或恢复「草稿不存在」
message，本组用例必须失败。
"""

import inspect
from pathlib import Path

import pytest

from app.core.errors import ApiError
from app.infrastructure.persistence.models import CodeSession
from app.schemas.code import CodeSessionIn
from app.services.code_service import CodeService

ROOT = Path(__file__).resolve().parents[2]

# 默认标题三层一致：models 列默认 / schema 字段默认 / 服务层参数默认
def test_default_title_is_named_conversation():
    col_default = CodeSession.__table__.columns["title"].default.arg
    assert col_default == "未命名会话"
    assert CodeSessionIn.model_fields["title"].default == "未命名会话"
    sig = inspect.signature(CodeService.create_draft)
    assert sig.parameters["title"].default == "未命名会话"


# 用户可见文案的源头文件不得再出现「草稿」（models.py 的禁词说明除外）
GUARDED_FILES = [
    "backend/app/services/code_service.py",
    "backend/app/routers/code.py",
    "backend/app/schemas/code.py",
    "frontend/src/views/student/CodeEditorView.vue",
    "frontend/src/api/code.ts",
    "frontend/src/components/CodeEditor.vue",
    "frontend/src/views/student/CodeReviewView.vue",
]


def test_no_draft_word_in_user_facing_sources():
    for rel in GUARDED_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "草稿" not in text, f"{rel} 仍含禁词「草稿」"


async def test_missing_session_message_uses_conversation_term(session):
    with pytest.raises(ApiError) as exc:
        await CodeService(session).update_draft(
            user_id="u1", draft_id="nonexistent", title="x"
        )
    assert exc.value.code == 4040
    assert exc.value.message == "代码会话不存在"
