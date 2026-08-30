"""历史截断（spec §8.1）。

固定值，不开放配置：累计 token 超过 **4000**，或轮数超过 **10 轮**（一问一答计
一轮）即停止累加；截断后若首轮被丢弃，改为保留最后一轮以保证上下文连贯。
"""

import pytest

from app.domain.chat.history import (
    MAX_HISTORY_ROUNDS,
    MAX_HISTORY_TOKENS,
    estimate_tokens,
    truncate_history,
)


def _rounds(count: int, chars: int = 40) -> list[dict]:
    """构造 count 轮「一问一答」；每轮 token 数 = chars // 4 * 2。"""
    out: list[dict] = []
    for i in range(count):
        out.append({"role": "user", "content": f"问{i}" + "。" * (chars - 2)})
        out.append({"role": "assistant", "content": f"答{i}" + "。" * (chars - 2)})
    return out


def test_limits_match_spec():
    assert MAX_HISTORY_TOKENS == 4000
    assert MAX_HISTORY_ROUNDS == 10


def test_token_estimate_is_char_count_over_four():
    """与 Mock 的估算用量同口径（CONTEXT.md「估算用量」）—— 不引入 tiktoken。"""
    assert estimate_tokens("a" * 400) == 100


def test_empty_history_stays_empty():
    assert truncate_history([]) == []


def test_short_history_is_kept_entirely():
    history = _rounds(3)
    assert truncate_history(history) == history


def test_more_than_ten_rounds_are_truncated():
    history = _rounds(20)
    kept = truncate_history(history)
    assert len(kept) == MAX_HISTORY_ROUNDS * 2
    assert kept[0]["content"].startswith("问10")


def test_token_budget_truncates_before_the_round_limit():
    """每轮 2000 token：第三轮起累计超过 4000，故只保留最近两轮。"""
    history = _rounds(3, chars=4000)
    kept = truncate_history(history)
    assert len(kept) == 4
    assert kept[0]["content"].startswith("问1")


def test_oversized_last_round_is_kept_as_a_fallback():
    """spec §8.1：截断后若首轮被丢弃，改为保留最后一轮。

    最近一轮本身就超过 4000 token 时，按预算一条都留不下 —— 此时必须兜底保留
    最后一轮，否则模型会完全失去上下文，而「上下文不连贯」比「上下文偏长」糟。
    """
    history = _rounds(1, chars=40000)
    kept = truncate_history(history)
    assert len(kept) == 2
    assert kept[0]["role"] == "user" and kept[1]["role"] == "assistant"


def test_orphan_user_message_still_forms_a_round():
    """学生连发两条消息（assistant 还没回）时，不能把配对的轮次算错。"""
    history = _rounds(2) + [{"role": "user", "content": "孤立的一问"}]
    kept = truncate_history(history)
    assert kept[-1]["content"] == "孤立的一问"


def test_output_preserves_chronological_order():
    """倒序累加是为了挑最近的，输出必须恢复时间顺序 —— 否则 prompt 会自问自答。"""
    kept = truncate_history(_rounds(15))
    roles = [m["role"] for m in kept]
    assert roles == ["user", "assistant"] * (len(kept) // 2)
    assert kept[0]["content"].startswith("问5")


def test_input_is_not_mutated():
    history = _rounds(12)
    snapshot = list(history)
    truncate_history(history)
    assert history == snapshot


@pytest.mark.parametrize("rounds", [1, 5, 9, 10, 11, 30])
def test_result_never_exceeds_either_limit(rounds):
    kept = truncate_history(_rounds(rounds))
    assert len(kept) // 2 <= MAX_HISTORY_ROUNDS
    assert sum(estimate_tokens(m["content"]) for m in kept) <= MAX_HISTORY_TOKENS or len(kept) == 2
