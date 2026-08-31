"""MistakeBookService 查询侧（spec §8.5 / §6.2 mistake 行，P5 Task 8）。

RandomFill 标注可见与「重置掌握 = consecutive_correct 清零」是变异测试目标。
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.errors import ApiError
from app.domain.exercise.judging import STATUS_PUBLISHED
from app.infrastructure.persistence.models import Exercise, MistakeBookEntry
from app.services.mistake_service import MistakeBookService

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


async def _add_exercise(session, **over) -> Exercise:
    fields: dict = {
        "type": "choice",
        "stem": "习题",
        "options": {"A": "1", "B": "2"},
        "answer": "A",
        "knowledge_tags": ["变量与赋值"],
        "difficulty": 1,
        "source": "seed",
        "status": STATUS_PUBLISHED,
    }
    fields.update(over)
    row = Exercise(**fields)
    session.add(row)
    await session.flush()
    return row


async def _entries(session, user_id: str) -> list[MistakeBookEntry]:
    rows = await session.execute(
        select(MistakeBookEntry).where(MistakeBookEntry.user_id == user_id)
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_record_result_full_cycle_with_rollback(session):
    """错误建条目 → 连对两次掌握 → 再错回滚（服务层端到端，spec §8.5）。"""
    ex = await _add_exercise(session)
    svc = MistakeBookService(session)

    await svc.record_result(user_id="u-1", exercise=ex, is_correct=False, wrong_answer="B", now=NOW)
    await svc.record_result(user_id="u-1", exercise=ex, is_correct=True, wrong_answer=None, now=NOW)
    await svc.record_result(user_id="u-1", exercise=ex, is_correct=True, wrong_answer=None, now=NOW)

    entry = (await _entries(session, "u-1"))[0]
    assert entry.mastered is True
    assert entry.mastered_at is not None
    assert entry.consecutive_correct == 2

    await svc.record_result(user_id="u-1", exercise=ex, is_correct=False, wrong_answer="C", now=NOW)
    assert entry.mastered is False
    assert entry.mastered_at is None
    assert entry.wrong_count == 2
    assert entry.last_wrong_answer == "C"


@pytest.mark.asyncio
async def test_list_entries_filters_by_mastered(session):
    ex = await _add_exercise(session)
    ex2 = await _add_exercise(session, stem="已掌握题", knowledge_tags=["循环"])
    svc = MistakeBookService(session)

    await svc.record_result(user_id="u-1", exercise=ex, is_correct=False, wrong_answer="B", now=NOW)
    await svc.record_result(user_id="u-1", exercise=ex2, is_correct=False, wrong_answer="B", now=NOW)
    await svc.record_result(user_id="u-1", exercise=ex2, is_correct=True, wrong_answer=None, now=NOW)
    await svc.record_result(user_id="u-1", exercise=ex2, is_correct=True, wrong_answer=None, now=NOW)

    all_pairs = await svc.list_entries("u-1")
    assert len(all_pairs) == 2

    unmastered = await svc.list_entries("u-1", mastered=False)
    assert [e.id for e, _ in unmastered] == [(await _entries(session, "u-1"))[0].id]

    mastered = await svc.list_entries("u-1", mastered=True)
    assert len(mastered) == 1
    assert mastered[0][0].mastered is True
    assert mastered[0][1].stem == "已掌握题", "条目必须带习题摘要"


@pytest.mark.asyncio
async def test_profile_aggregates_wrong_count_and_excludes_mastered(session):
    e1 = await _add_exercise(session, knowledge_tags=["变量与赋值", "数据类型"])
    e2 = await _add_exercise(session, stem="循环题", knowledge_tags=["循环"], difficulty=2)
    e3 = await _add_exercise(session, stem="已掌握", knowledge_tags=["循环"])
    svc = MistakeBookService(session)

    for _ in range(3):
        await svc.record_result(user_id="u-1", exercise=e1, is_correct=False, wrong_answer="x", now=NOW)
    await svc.record_result(user_id="u-1", exercise=e2, is_correct=False, wrong_answer="x", now=NOW)
    # e3 答错两次后连对两次 → 已掌握，聚合必须排除
    for _ in range(2):
        await svc.record_result(user_id="u-1", exercise=e3, is_correct=False, wrong_answer="x", now=NOW)
    for _ in range(2):
        await svc.record_result(user_id="u-1", exercise=e3, is_correct=True, wrong_answer=None, now=NOW)

    profile = await svc.profile("u-1")
    by_tag = {p["knowledge_tag"]: p["wrong_count"] for p in profile}
    assert by_tag["变量与赋值"] == 3
    assert by_tag["数据类型"] == 3
    assert by_tag["循环"] == 1, "已掌握条目不计入画像"
    assert profile[0]["wrong_count"] >= profile[-1]["wrong_count"], "按 wrong_count 降序"


@pytest.mark.asyncio
async def test_recommendations_ranked_by_weak_tags_then_difficulty(session):
    """薄弱 tag 命中的题入选且难度升序；薄弱集之外的习题不入画像推荐。"""
    weak = await _add_exercise(session, knowledge_tags=["循环"], difficulty=3)
    weak_easy = await _add_exercise(
        session, stem="循环-易", knowledge_tags=["循环", "列表"], difficulty=1
    )
    strong = await _add_exercise(session, stem="变量题", knowledge_tags=["变量与赋值"])
    svc = MistakeBookService(session)

    await svc.record_result(user_id="u-1", exercise=weak, is_correct=False, wrong_answer="x", now=NOW)
    await svc.record_result(user_id="u-1", exercise=weak_easy, is_correct=False, wrong_answer="x", now=NOW)
    # strong 从未答错：其 tag「变量与赋值」不进薄弱集

    result = await svc.recommendations("u-1", limit=2)
    assert set(result["weak_tags"]) == {"循环", "列表"}
    items = result["items"]
    assert len(items) == 2
    picked_ids = [item["exercise"].id for item in items]
    assert strong.id not in picked_ids, "薄弱 tag 未命中的题不进画像推荐"
    assert [item["filled_by"] for item in items] == ["profile", "profile"]
    assert picked_ids == [weak_easy.id, weak.id], "薄弱命中集内难度升序（1 → 3）"


@pytest.mark.asyncio
async def test_recommendations_random_fill_is_marked(session):
    """不足 limit 按难度递增补足并标注 filled_by=random（CONTEXT.md 随机补足）。"""
    weak = await _add_exercise(session, knowledge_tags=["循环"], difficulty=2)
    filler_hard = await _add_exercise(
        session, stem="随机补-难", knowledge_tags=["字符串"], difficulty=4
    )
    filler_easy = await _add_exercise(
        session, stem="随机补-易", knowledge_tags=["函数"], difficulty=1
    )
    svc = MistakeBookService(session)
    await svc.record_result(user_id="u-1", exercise=weak, is_correct=False, wrong_answer="x", now=NOW)

    result = await svc.recommendations("u-1", limit=3)
    items = result["items"]
    assert len(items) == 3
    assert [item["filled_by"] for item in items] == ["profile", "random", "random"]
    # 随机补足按难度递增：1 → 4
    assert [item["exercise"].difficulty for item in items[1:]] == [1, 4]
    assert {filler_easy.id, filler_hard.id} == {i["exercise"].id for i in items[1:]}


@pytest.mark.asyncio
async def test_recommendations_without_mistakes_all_random(session):
    await _add_exercise(session)
    await _add_exercise(session, stem="第二题", knowledge_tags=["循环"], difficulty=2)
    svc = MistakeBookService(session)

    result = await svc.recommendations("u-1", limit=2)
    assert result["weak_tags"] == []
    assert all(item["filled_by"] == "random" for item in result["items"])
    assert len(result["items"]) == 2


@pytest.mark.asyncio
async def test_recommendations_exclude_mastered_exercises(session):
    ex = await _add_exercise(session)
    other = await _add_exercise(session, stem="另一题", knowledge_tags=["循环"], difficulty=2)
    svc = MistakeBookService(session)
    # ex：错一次 + 连对两次 → 已掌握
    await svc.record_result(user_id="u-1", exercise=ex, is_correct=False, wrong_answer="x", now=NOW)
    for _ in range(2):
        await svc.record_result(user_id="u-1", exercise=ex, is_correct=True, wrong_answer=None, now=NOW)

    result = await svc.recommendations("u-1", limit=5)
    picked = {item["exercise"].id for item in result["items"]}
    assert ex.id not in picked, "推荐排除已掌握"
    assert other.id in picked


@pytest.mark.asyncio
async def test_reset_mastered_clears_streak_keeps_history(session):
    """裁定 2：重置 = mastered=false、mastered_at=null、consecutive_correct=0；
    wrong_count 与 last_wrong_* 保留（历史不可篡改）。"""
    ex = await _add_exercise(session)
    svc = MistakeBookService(session)
    await svc.record_result(user_id="u-1", exercise=ex, is_correct=False, wrong_answer="错答", now=NOW)
    for _ in range(2):
        await svc.record_result(user_id="u-1", exercise=ex, is_correct=True, wrong_answer=None, now=NOW)
    entry = (await _entries(session, "u-1"))[0]
    assert entry.mastered is True

    reset = await svc.reset_mastered("u-1", entry.id)

    assert reset.mastered is False
    assert reset.mastered_at is None
    assert reset.consecutive_correct == 0
    assert reset.wrong_count == 1
    assert reset.last_wrong_answer == "错答"
    assert reset.last_wrong_at is not None


@pytest.mark.asyncio
async def test_reset_mastered_requires_ownership(session):
    ex = await _add_exercise(session)
    svc = MistakeBookService(session)
    await svc.record_result(user_id="u-1", exercise=ex, is_correct=False, wrong_answer="x", now=NOW)
    entry = (await _entries(session, "u-1"))[0]

    with pytest.raises(ApiError) as exc:
        await svc.reset_mastered("u-2", entry.id)
    assert exc.value.code == 4040, "非本人条目 4040，不泄露存在性"

    with pytest.raises(ApiError) as exc:
        await svc.reset_mastered("u-1", "no-such-entry")
    assert exc.value.code == 4040
