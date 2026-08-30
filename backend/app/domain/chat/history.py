"""历史截断规则（spec §8.1，零 IO）。

按时间倒序累加最近轮次，累计 token 超过 **4000**、或轮数超过 **10 轮**（一问一答
计一轮）即停止累加；截断后若首轮被丢弃，改为保留最后一轮以保证上下文连贯。

**这两个值是固定值，不开放配置。** 它们是 prompt 预算的一部分，与模型的上下文
窗口强相关；开放配置会让「同一份知识库在不同配置下召回率不同」这类问题更难排查，
而演示场景下没有调优需求。

**token 估算口径**与 Mock 的估算用量一致：`len(content) // 4`（CONTEXT.md「估算
用量」）。不引入 tiktoken —— spec §8.2 已论证中文 token 密度与英文相差 2–3 倍，
用 tokenizer 计量会让预算在不同语言下不可比。
"""

MAX_HISTORY_TOKENS = 4000
MAX_HISTORY_ROUNDS = 10

# 一问一答：一轮以 user 消息开始，跟随其后的 assistant 消息归入同一轮
_ROUND_START = "user"


def estimate_tokens(text: str) -> int:
    """估算用量 EstimatedUsage 的同口径估算（len//4）。"""
    return len(text) // 4


def truncate_history(
    messages: list[dict],
    *,
    max_tokens: int = MAX_HISTORY_TOKENS,
    max_rounds: int = MAX_HISTORY_ROUNDS,
) -> list[dict]:
    """返回截断后的历史，**保持原始时间顺序**。

    输入是 `[{"role": ..., "content": ...}, ...]` 字典列表 —— 领域层不碰 ORM
    对象，服务层负责把 `Message` 行转成字典。
    """
    rounds = _to_rounds(messages)
    if not rounds:
        return []

    kept: list[list[dict]] = []
    used = 0
    for round_messages in reversed(rounds):
        if len(kept) >= max_rounds:
            break
        cost = sum(estimate_tokens(m["content"]) for m in round_messages)
        if used + cost > max_tokens:
            break
        kept.append(round_messages)
        used += cost

    if not kept:
        # spec §8.1：首轮（含最近一轮）都进不了预算时，兜底保留最后一轮。
        # 宁可上下文偏长，也不要完全没有上下文 —— 后者会让模型误以为是新话题。
        kept = [rounds[-1]]

    ordered = list(reversed(kept))
    return [m for round_messages in ordered for m in round_messages]


def _to_rounds(messages: list[dict]) -> list[list[dict]]:
    """按「一问一答」切轮；user 消息开启新一轮，孤立的 assistant 并入当前轮。"""
    rounds: list[list[dict]] = []
    for message in messages:
        if message["role"] == _ROUND_START or not rounds:
            rounds.append([message])
        else:
            rounds[-1].append(message)
    return rounds
