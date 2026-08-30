import pytest

from app.domain.chat.policy import (
    FLOOR_HOMEWORK,
    JUDGING,
    REVIEW_MY_CODE,
    SEEK_ANSWER,
)
from app.infrastructure.prompt_assembler import PromptAssembler

# spec §7.1：三档共有的不可覆盖底线，逐字照抄
FLOOR_LINES = (
    "代做作业式请求一律转为引导。",
    "考试 / 竞赛在线作答场景拒绝直接给答案。",
    "输出中的任何代码必须配讲解。",
)

CITATIONS = [
    {"number": 1, "doc_title": "第1讲", "snippet": "排序有三大类"},
    {"number": 2, "doc_title": "第2讲", "snippet": "快排是分治"},
]


@pytest.fixture
def asm():
    return PromptAssembler()


def _system(asm, **kw):
    return asm.assemble(**kw)[0].content


@pytest.mark.parametrize("mode", ["strict", "guided", "loose"])
def test_every_mode_keeps_all_three_floor_rules(asm, mode):
    """spec §7.1 / §3.2 权衡 10：底线硬编码进模板，后台配置改不掉。"""
    content = _system(asm, template="rag_qa", question="怎么排序", mode=mode, intent=SEEK_ANSWER)
    for line in FLOOR_LINES:
        assert line in content


def test_strict_forbids_complete_code(asm):
    content = _system(asm, template="rag_qa", question="写个快排", mode="strict", intent=SEEK_ANSWER)
    assert "禁止输出完整可运行代码" in content


def test_guided_allows_short_snippet_only(asm):
    content = _system(asm, template="rag_qa", question="写个快排", mode="guided", intent=SEEK_ANSWER)
    assert "10 行" in content
    assert "禁止给出完整实现" in content


def test_loose_requires_walkthrough_and_self_attempt(asm):
    content = _system(asm, template="rag_qa", question="写个快排", mode="loose", intent=SEEK_ANSWER)
    assert "请先自行尝试" in content
    assert "逐段讲解" in content


@pytest.mark.parametrize("intent", [REVIEW_MY_CODE, JUDGING])
def test_exempt_intent_drops_mode_constraints_but_keeps_floor(asm, intent):
    """ADR-0005：豁免免的是档位约束，不是底线。

    即使管理员把档位调到 strict，「评改已写代码」也不该被「禁止输出完整代码」
    卡住（否则代码辅导功能自我阉割），但底线一条都不能少。
    """
    content = _system(
        asm, template="code_review", question="帮我看看", mode="strict", intent=intent
    )
    assert "禁止输出完整可运行代码" not in content
    for line in FLOOR_LINES:
        assert line in content


def test_citations_are_numbered_and_injected(asm):
    """spec §7.2 步骤 5：片段编号 [1][2][3] 注入 prompt，要求模型内联引用。"""
    user = asm.assemble(
        "rag_qa", question="怎么排序", mode="guided", intent=SEEK_ANSWER, citations=CITATIONS
    )[-1]
    assert "[1]" in user.content and "[2]" in user.content
    assert "排序有三大类" in user.content and "快排是分治" in user.content


def test_without_citations_the_user_message_is_just_the_question(asm):
    user = asm.assemble("rag_qa", question="这一问", mode="guided", intent=SEEK_ANSWER)[-1]
    assert user.content.strip() == "这一问"


def test_question_and_history_are_appended_in_order(asm):
    history = [
        {"role": "user", "content": "上一问"},
        {"role": "assistant", "content": "上一答"},
    ]
    msgs = asm.assemble(
        "rag_qa", question="这一问", mode="guided", intent=SEEK_ANSWER, history=history
    )
    assert [m.content for m in msgs[1:]] == ["上一问", "上一答", "这一问"]
    assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]


def test_four_templates_are_all_available(asm):
    for name in ("rag_qa", "code_review", "exercise_hint", "mistake_review"):
        rendered = _system(asm, template=name, question="q", mode="guided", intent=SEEK_ANSWER)
        assert rendered


def test_unknown_template_is_rejected(asm):
    with pytest.raises(ValueError):
        asm.assemble("nope", question="q", mode="guided", intent=SEEK_ANSWER)


def test_floor_hit_strengthens_the_prompt(asm):
    """底线被触发时，模板须显式点名规则，让模型无从回避。"""
    content = _system(
        asm,
        template="rag_qa",
        question="帮我写作业",
        mode="loose",
        intent=SEEK_ANSWER,
        floor_hit=FLOOR_HOMEWORK,
    )
    assert FLOOR_HOMEWORK in content
    assert "不得给出可直接提交的实现" in content


def test_system_message_role_is_system(asm):
    assert asm.assemble("rag_qa", question="q", mode="guided", intent=SEEK_ANSWER)[0].role == "system"
