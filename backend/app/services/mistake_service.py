"""错题本用例编排（spec §8.5 / §6.2 mistake 行，CONTEXT.md「错题本」）。

Task 6 先落 `record_result`（判题归集的唯一入口），查询侧（条目 / 画像 /
推荐 / 重置掌握）在 Task 8 扩展。

**错题条目只收错误**：从未答错的正确提交不建条目 —— 「无条目则创建」在
spec §8.5 里说的是错误分支。已存在的条目在答对时也要推进
（`consecutive_correct += 1`），否则永远到不了「连续 2 次」。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exercise.mastery import MasteryState, apply_answer
from app.infrastructure.persistence.models import Exercise, MistakeBookEntry


class MistakeBookService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def record_result(
        self,
        *,
        user_id: str,
        exercise: Exercise,
        is_correct: bool,
        wrong_answer: object = None,
        now: datetime,
    ) -> MistakeBookEntry | None:
        """按本次作答正误推进 (user, exercise) 的错题条目；无错误历史且答对返回 None。

        状态机规则在 `domain/exercise/mastery.py`（零 IO），本方法只做行映射。
        """
        entry = (
            await self._session.execute(
                select(MistakeBookEntry).where(
                    MistakeBookEntry.user_id == user_id,
                    MistakeBookEntry.exercise_id == exercise.id,
                )
            )
        ).scalar_one_or_none()

        if entry is None:
            if is_correct:
                return None
            entry = MistakeBookEntry(user_id=user_id, exercise_id=exercise.id)
            self._session.add(entry)

        state = apply_answer(
            # 新构造（未 flush）的行列值是 None（SQLAlchemy 的 default 在 flush
            # 时才应用），先归一化再进状态机
            MasteryState(
                wrong_count=entry.wrong_count or 0,
                consecutive_correct=entry.consecutive_correct or 0,
                mastered=bool(entry.mastered),
                mastered_at=entry.mastered_at,
                last_wrong_answer=entry.last_wrong_answer,
                last_wrong_at=entry.last_wrong_at,
            ),
            is_correct=is_correct,
            wrong_answer=wrong_answer,
            now=now,
        )
        entry.wrong_count = state.wrong_count
        entry.consecutive_correct = state.consecutive_correct
        entry.mastered = state.mastered
        entry.mastered_at = state.mastered_at
        entry.last_wrong_answer = state.last_wrong_answer
        entry.last_wrong_at = state.last_wrong_at
        await self._session.flush()
        return entry
