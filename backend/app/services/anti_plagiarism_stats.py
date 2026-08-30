"""防抄袭效果度量（spec §7.4）。

**不做抄袭检测，只做拦截率度量**，使该功能点可量化。口径：

- 每次请求落一条 `role=user` 的 `Message`，带当次生效的 `anti_plagiarism_mode`
  与 `blocked_by_policy`（是否触发底线）
- 按档位分别统计「触发底线次数 / 总请求数」

**CONTEXT.md：拦截率是度量口径，不是检测能力。** 分子来自 `detect_floor_violation`
的确定性关键词规则，漏判与误判都可能存在；它衡量的是「有多少请求被底线规则
拦下」，不是「有多少学生在抄袭」。前端展示时不得改写成「抄袭检出数」。
"""

from sqlalchemy import Integer, cast, func, select

from app.domain.chat.policy import (
    ANTI_PLAGIARISM_MODES,
    ROLE_USER,
    SEEK_ANSWER,
)
from app.infrastructure.persistence.models import Message


class AntiPlagiarismStatsService:
    def __init__(self, session) -> None:
        self._session = session

    async def stats(self) -> dict:
        """返回各档位的拦截率与一个 overall 汇总。"""
        rows = await self._session.execute(
            select(
                Message.anti_plagiarism_mode,
                func.count(Message.id),
                func.coalesce(func.sum(cast(Message.blocked_by_policy, Integer)), 0),
            )
            .where(Message.role == ROLE_USER)
            .group_by(Message.anti_plagiarism_mode)
        )
        counts = {mode: [0, 0] for mode in ANTI_PLAGIARISM_MODES}
        overall = [0, 0]
        for mode, total, blocked in rows.all():
            overall[0] += total
            overall[1] += blocked
            if mode in counts:
                counts[mode] = [total, blocked]

        items = [_item(mode, *counts[mode]) for mode in ANTI_PLAGIARISM_MODES]
        return {
            "intent": SEEK_ANSWER,
            "items": items,
            "overall": _item("all", *overall),
        }


def _item(mode: str | None, total: int, blocked: int) -> dict:
    return {
        "mode": mode,
        "total": total,
        "blocked": blocked,
        # total 为 0 时不得除零
        "block_rate": round(blocked / total, 4) if total else 0.0,
    }
