"""错题本用例编排（spec §8.5 / §6.2 mistake 行，CONTEXT.md「错题本」）。

`record_result` 是判题归集的唯一入口；查询侧供 `/mistakes*` 端点：

- `list_entries`：条目列表（可按 mastered 过滤），附习题摘要
- `profile`：按 knowledge_tags 聚合 SUM(wrong_count)，排除已掌握
  （CONTEXT.md「薄弱知识点 WeakKnowledgePoint」：实时聚合，无独立表；
  JSON 列无法 SQL 聚合，声明规模下 Python 层聚合成本可忽略——spec §3.2 权衡 3）
- `recommendations`：top-3 薄弱 tag → 选题（排除已掌握）→ 难度升序 →
  不足 limit 按难度递增补足并标注 filled_by=random（CONTEXT.md「随机补足」；
  Exercise 无课程维度，「同课程随机题」取全部 published 池——契约定稿 12）
- `reset_mastered`：手动重置掌握度（裁定 2）：mastered=false、mastered_at=null、
  **consecutive_correct=0**；wrong_count 与 last_wrong_* 保留

**错题条目只收错误**：从未答错的正确提交不建条目 —— 「无条目则创建」在
spec §8.5 里说的是错误分支。已存在的条目在答对时也要推进
（`consecutive_correct += 1`），否则永远到不了「连续 2 次」。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.domain.exercise.judging import STATUS_PUBLISHED
from app.domain.exercise.mastery import MasteryState, apply_answer
from app.infrastructure.persistence.models import Exercise, MistakeBookEntry

# 填充项标注（CONTEXT.md「随机补足 RandomFill」）
FILLED_BY_PROFILE = "profile"
FILLED_BY_RANDOM = "random"

# 定向推荐取前 3 个薄弱知识点（spec §8.5）
WEAK_TAG_TOP = 3


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

    # ------------------------------------------------------------ 查询侧

    async def list_entries(
        self, user_id: str, *, mastered: bool | None = None
    ) -> list[tuple[MistakeBookEntry, Exercise]]:
        """条目列表，附习题摘要；`mastered=None` 表示不过滤（spec §6.2 `?mastered=`）。"""
        stmt = select(MistakeBookEntry).where(MistakeBookEntry.user_id == user_id)
        if mastered is not None:
            stmt = stmt.where(MistakeBookEntry.mastered == mastered)
        stmt = stmt.order_by(MistakeBookEntry.last_wrong_at.desc(), MistakeBookEntry.id)
        entries = list((await self._session.execute(stmt)).scalars().all())
        exercises = await self._exercises_of(entries)
        return [(entry, exercises[entry.exercise_id]) for entry in entries if entry.exercise_id in exercises]

    async def profile(self, user_id: str) -> list[dict]:
        """薄弱知识点画像：按 tag 聚合未掌握条目的 wrong_count，降序（spec §8.5）。"""
        entries = await self._session.execute(
            select(MistakeBookEntry).where(
                MistakeBookEntry.user_id == user_id,
                MistakeBookEntry.mastered == False,
            )
        )
        rows = list(entries.scalars().all())
        exercises = await self._exercises_of(rows)

        sums: dict[str, int] = {}
        for entry in rows:
            exercise = exercises.get(entry.exercise_id)
            if exercise is None:
                continue
            for tag in exercise.knowledge_tags or []:
                sums[tag] = sums.get(tag, 0) + entry.wrong_count
        ordered = sorted(sums.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"knowledge_tag": tag, "wrong_count": count} for tag, count in ordered]

    async def recommendations(self, user_id: str, *, limit: int = 5) -> dict:
        """定向推荐（spec §8.5）：top-3 薄弱 tag → 选题（排除已掌握）→ 难度升序。

        不足 limit 时按难度递增补足 published 随机题并标注
        `filled_by=random`（CONTEXT.md「随机补足」，标注必须可见）。补足
        选取按 (difficulty, id) 确定性升序 —— 演示规模下可复现优先于真随机。
        """
        published = list(
            (
                await self._session.execute(
                    select(Exercise)
                    .where(Exercise.status == STATUS_PUBLISHED)
                    .order_by(Exercise.difficulty, Exercise.created_at, Exercise.id)
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in published}
        mastered_ids = {
            entry.exercise_id
            for entry in (
                await self._session.execute(
                    select(MistakeBookEntry).where(
                        MistakeBookEntry.user_id == user_id,
                        MistakeBookEntry.mastered == True,
                    )
                )
            ).scalars()
            if entry.exercise_id in by_id
        }
        available = [row for row in published if row.id not in mastered_ids]

        weak_tags = [p["knowledge_tag"] for p in (await self.profile(user_id))[:WEAK_TAG_TOP]]
        weak_tag_set = set(weak_tags)

        items: list[dict] = []
        picked_ids: set[str] = set()
        for row in available:  # 已按难度升序
            if len(items) >= limit:
                break
            if weak_tag_set & set(row.knowledge_tags or []):
                items.append({"exercise": row, "filled_by": FILLED_BY_PROFILE})
                picked_ids.add(row.id)

        for row in available:  # RandomFill：与画像无关的补足，同样排除已掌握
            if len(items) >= limit:
                break
            if row.id in picked_ids:
                continue
            items.append({"exercise": row, "filled_by": FILLED_BY_RANDOM})
            picked_ids.add(row.id)

        return {"items": items, "weak_tags": weak_tags}

    async def reset_mastered(self, user_id: str, entry_id: str) -> MistakeBookEntry:
        """手动重置掌握度（裁定 2）：开启新一轮练习周期。

        `consecutive_correct` 一并清零 —— 跨周期的旧连对不应计入新一轮的
        「连续」；`wrong_count` 与 `last_wrong_*` 是历史，保留。非本人条目
        与不存在一律 `4040`（不泄露存在性）。
        """
        entry = await self._session.get(MistakeBookEntry, entry_id)
        if entry is None or entry.user_id != user_id:
            raise ApiError(4040, "错题条目不存在")
        entry.mastered = False
        entry.mastered_at = None
        entry.consecutive_correct = 0
        await self._session.flush()
        return entry

    # ------------------------------------------------------------ 内部辅助

    async def _exercises_of(self, entries: list[MistakeBookEntry]) -> dict[str, Exercise]:
        ids = {entry.exercise_id for entry in entries}
        if not ids:
            return {}
        rows = (
            await self._session.execute(select(Exercise).where(Exercise.id.in_(ids)))
        ).scalars().all()
        return {row.id: row for row in rows}
