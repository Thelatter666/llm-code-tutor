"""CodeService 测试（spec §8.4 §9 ADR-0005）。

覆盖：source_hash 复用（按 user 隔离）、固定 review_my_code 豁免意图、
Mock 模式模板化（不发起 LLM 调用）、真提供方流式收集与用量逐字取自流末
Usage、提供方失败的模板降级、阻塞卸载与审计。
"""

from dataclasses import asdict

import pytest
from sqlalchemy import select

import app.services.code_service as code_service_module
from app.core.crypto import encrypt_api_key
from app.domain.code.analysis import LANGUAGE_PYTHON, analyze, source_hash
from app.domain.code.review import render_mock_review
from app.infrastructure.llm_runtime import FALLBACK_TO_MOCK
from app.infrastructure.persistence.models import AuditLog, CodeAnalysis
from app.infrastructure.registry import get_or_create_singleton
from app.infrastructure.ports.llm import TextDelta, Usage
from app.services.code_service import CodeService
from tests.fakes import FakeLLM, fake_llm_runtime

SRC = "def area(radius):\n    return radius * 3.14\n"


class FixedUsageLLM(FakeLLM):
    """流末给出与文本长度**无关**的用量，证伪「用量按文本长度现算」。"""

    async def stream(self, messages, params, *, cancel=None):
        self.messages.append(list(messages))
        for ch in self.reply:
            if cancel is not None and cancel.is_set():
                break
            yield TextDelta(ch)
        yield Usage(prompt_tokens=1111, completion_tokens=2222, total_tokens=3333, estimated=False)


async def _enable_real_provider(session) -> None:
    """把单例配置切成「openai_compat + 有 Key」：服务层据此走真提供方路径。"""
    cfg = await get_or_create_singleton(session)
    cfg.provider = "openai_compat"
    cfg.api_key_encrypted = encrypt_api_key("sk-test")
    cfg.revision += 1
    await session.flush()


async def _count_rows(session) -> int:
    rows = (await session.execute(select(CodeAnalysis))).scalars().all()
    return len(rows)


@pytest.mark.asyncio
async def test_first_analysis_persists_static_report(session):
    svc = CodeService(session)
    row, reused = await svc.analyze(
        user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r1"
    )

    assert reused is False
    assert row.static_report == asdict(analyze(LANGUAGE_PYTHON, SRC))
    assert row.source_hash == source_hash(LANGUAGE_PYTHON, SRC)
    assert await session.get(CodeAnalysis, row.id) is not None
    assert await _count_rows(session) == 1


@pytest.mark.asyncio
async def test_same_hash_is_reused_without_recompute_or_llm(session, monkeypatch):
    calls: list[tuple[str, str]] = []
    real_analyze = code_service_module.analyze

    def spy(language, source):
        calls.append((language, source))
        return real_analyze(language, source)

    monkeypatch.setattr(code_service_module, "analyze", spy)
    llm = FakeLLM(reply="不应被调用")
    svc = CodeService(session, llm=fake_llm_runtime(llm))

    row1, reused1 = await svc.analyze(
        user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r1"
    )
    row2, reused2 = await svc.analyze(
        user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r2"
    )

    assert (reused1, reused2) == (False, True)
    assert row1.id == row2.id
    assert len(calls) == 1, "命中 source_hash 后不得重复解析"
    assert llm.messages == [], "复用路径不发起任何 LLM 调用"
    assert await _count_rows(session) == 1


@pytest.mark.asyncio
async def test_same_source_from_different_user_is_not_reused(session):
    svc = CodeService(session)
    await svc.analyze(user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r1")
    row2, reused = await svc.analyze(
        user_id="u2", language=LANGUAGE_PYTHON, source=SRC, request_id="r2"
    )

    assert reused is False
    assert row2.user_id == "u2"
    assert await _count_rows(session) == 2


@pytest.mark.asyncio
async def test_intent_is_always_review_my_code_even_in_strict_mode(session):
    """ADR-0005：/code/analyze 固定豁免意图，是显式契约，绝不按内容推断。"""
    await _enable_real_provider(session)
    cfg = await get_or_create_singleton(session)
    cfg.anti_plagiarism_mode = "strict"
    await session.flush()

    llm = FakeLLM(reply="讲解")
    svc = CodeService(session, llm=fake_llm_runtime(llm))
    await svc.analyze(
        user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r1"
    )

    system = llm.messages[0][0]
    assert "【防抄袭档位：本次豁免】" in system.content
    for mode in ("strict", "guided", "loose"):
        assert f"【防抄袭档位：{mode}】" not in system.content
    # 问题串携带静态摘要与完整源码（CONTEXT.md：AI 报告基于静态报告与源码）
    user = llm.messages[0][-1]
    assert "```python" in user.content
    assert SRC in user.content


@pytest.mark.asyncio
async def test_mock_mode_templates_ai_report_without_llm_call(session):
    llm = FakeLLM(reply="不应被调用")
    svc = CodeService(session, llm=fake_llm_runtime(llm))
    row, _ = await svc.analyze(
        user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r1"
    )

    ai = row.ai_report
    assert llm.messages == []
    assert ai["content"] == render_mock_review(analyze(LANGUAGE_PYTHON, SRC))
    assert ai["provider"] == "mock"
    assert ai["usage_estimated"] is True
    assert ai["token_usage"]["completion_tokens"] == len(ai["content"]) // 4
    assert ai["degraded"] is False
    assert ai["fallback_reason"] is None


@pytest.mark.asyncio
async def test_real_provider_streams_and_usage_is_verbatim_from_stream_tail(session):
    """拍板决策 5：token_usage 必须来自流末 Usage 元素。"""
    await _enable_real_provider(session)
    llm = FixedUsageLLM(reply="流式讲解")
    svc = CodeService(session, llm=fake_llm_runtime(llm))
    row, _ = await svc.analyze(
        user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r1"
    )

    ai = row.ai_report
    assert ai["content"] == "流式讲解"
    assert ai["token_usage"] == {
        "prompt_tokens": 1111,
        "completion_tokens": 2222,
        "total_tokens": 3333,
    }
    assert ai["usage_estimated"] is False
    assert ai["degraded"] is False
    assert ai["fallback_reason"] is None


@pytest.mark.asyncio
async def test_provider_failure_degrades_to_template_visibly(session):
    """spec §9：首选失败降级到 Mock；此处按 §8.4 直接落到模板并显式标记。"""
    await _enable_real_provider(session)
    svc = CodeService(session, llm=fake_llm_runtime(FakeLLM(reply="x", fail=True)))
    row, _ = await svc.analyze(
        user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r1"
    )

    ai = row.ai_report
    assert ai["content"] == render_mock_review(analyze(LANGUAGE_PYTHON, SRC))
    assert ai["provider"] == "mock"
    assert ai["degraded"] is True
    assert ai["fallback_reason"] == FALLBACK_TO_MOCK
    assert ai["usage_estimated"] is True


@pytest.mark.asyncio
async def test_static_analysis_is_offloaded_to_threadpool(session, monkeypatch):
    """ADR-0002：ast 解析是同步阻塞调用，必须经 run_in_threadpool 卸载。"""
    calls: list[str] = []
    real = code_service_module.run_in_threadpool

    async def spy(func, *args, **kwargs):
        calls.append(getattr(func, "__name__", str(func)))
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(code_service_module, "run_in_threadpool", spy)
    svc = CodeService(session)
    await svc.analyze(
        user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r1"
    )
    assert calls == ["analyze"]


@pytest.mark.asyncio
async def test_audit_log_written_for_both_fresh_and_reused_analysis(session):
    svc = CodeService(session)
    row, _ = await svc.analyze(
        user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r1"
    )
    await svc.analyze(user_id="u1", language=LANGUAGE_PYTHON, source=SRC, request_id="r2")

    logs = (
        await session.execute(select(AuditLog).where(AuditLog.action == "code_analyze"))
    ).scalars().all()
    assert len(logs) == 2
    assert logs[0].target_id == row.id
    assert logs[0].detail["reused"] is False
    assert logs[1].detail["reused"] is True
    assert logs[1].request_id == "r2"
