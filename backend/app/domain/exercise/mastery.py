"""掌握度状态机（spec §8.5，CONTEXT.md「掌握度 Mastery」）。

**已掌握必须可回滚**（spec §8.5 原文）：若错误时不重置 `mastered`，学生把某题
练到「已掌握」后再答错，该条目将永久停留在 `mastered=true` 并被错题本默认
过滤排除——「错题驱动学习」退化为单向门。语义取最直白的一档：掌握了又做错，
就是没掌握。

本模块零 IO：服务层把 `MistakeBookEntry` 行映射成 `MasteryState`，调用
`apply_answer` 后把返回值写回。纯函数不做原地修改，便于脱离数据库单测。
"""

from dataclasses import dataclass
from datetime import datetime

# 连续 2 次答对即视为已掌握（spec §8.5 / 已裁定决策）
MASTERY_THRESHOLD = 2


@dataclass
class MasteryState:
    """`MistakeBookEntry` 的状态投影（不含主键与 user/exercise 归属）。"""

    wrong_count: int = 0
    consecutive_correct: int = 0
    mastered: bool = False
    mastered_at: datetime | None = None
    last_wrong_answer: object = None
    last_wrong_at: datetime | None = None


def apply_answer(
    state: MasteryState | None,
    *,
    is_correct: bool,
    wrong_answer: object = None,
    now: datetime,
) -> MasteryState:
    """按本次作答正误推进状态机，返回新状态；`state=None` 表示无条目（创建）。

    - 正确：`consecutive_correct += 1`；达到 `MASTERY_THRESHOLD` 置
      `mastered=true`、`mastered_at=now`。已掌握后答对不重置掌握时间。
    - 错误：`wrong_count += 1`、`consecutive_correct = 0`、`mastered=false`、
      `mastered_at=null`（回滚是硬要求），写 `last_wrong_answer` 与
      `last_wrong_at`。
    """
    base = state or MasteryState()
    nxt = MasteryState(**base.__dict__)

    if is_correct:
        nxt.consecutive_correct += 1
        if not nxt.mastered and nxt.consecutive_correct >= MASTERY_THRESHOLD:
            nxt.mastered = True
            nxt.mastered_at = now
        return nxt

    nxt.wrong_count += 1
    nxt.consecutive_correct = 0
    nxt.mastered = False
    nxt.mastered_at = None
    nxt.last_wrong_answer = wrong_answer
    nxt.last_wrong_at = now
    return nxt
