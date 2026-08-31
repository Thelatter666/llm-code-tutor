"""40 题习题种子的回归网（spec §11 P5 行，P5 Task 13）。

三件事必须被机器守住：

1. **配比与覆盖**（题型 10/6/8/8/8、难度 8/10/12/7/3、12 个标签每个 ≥2 题）——
   这是「薄弱知识点画像 + 定向推荐」能闭环的前提，退化了功能就名存实亡；
2. **幂等**（uuid5 确定性主键 + 存在即跳过）—— 去掉存在性检查即翻倍，变异测试目标；
3. **coding 题可解性** —— 用**真** `SubprocessCodeExecutor` 逐用例跑参考答案。
   Fake 执行器只能证明接线，证明不了「这道题真能做出来」，而参考答案错了会
   直接把学生教错，这是题库最不可接受的缺陷。
"""

import re
import uuid
from collections import Counter

import pytest
from sqlalchemy import func, select

from app.domain.exercise.judging import (
    EXERCISE_TYPES,
    SOURCE_SEED,
    STATUS_PUBLISHED,
    TYPE_CODING,
)
from app.domain.exercise.shapes import check_exercise_shape
from app.infrastructure.adapters.execution.subprocess_executor import (
    SubprocessCodeExecutor,
)
from app.infrastructure.persistence.models import Exercise, ModelConfig, User
from seeds import seed as seed_all
from seeds.exercises import (
    DIFFICULTY_QUOTAS,
    EXERCISES,
    KNOWLEDGE_TAGS,
    TYPE_QUOTAS,
    exercise_id_for,
    seed_exercises,
)

# 执行器黑名单里的这些写法会让参考答案直接被判定 blocked，永远跑不到比对
FORBIDDEN_IN_SOLUTION = (
    "os.system",
    "subprocess",
    "socket",
    "shutil.rmtree",
    "__import__",
    "eval(",
    "exec(",
    "open(",
)

CODING_ITEMS = [item for item in EXERCISES if item["type"] == TYPE_CODING]


# ---------------------------------------------------------------- 条数与形态


def test_exercise_count_and_quotas():
    assert len(EXERCISES) == 40
    assert Counter(item["type"] for item in EXERCISES) == Counter(TYPE_QUOTAS)
    assert Counter(item["difficulty"] for item in EXERCISES) == Counter(DIFFICULTY_QUOTAS)
    for level in range(1, 6):
        assert any(item["difficulty"] == level for item in EXERCISES), f"难度 {level} 不能为空"
    assert {item["type"] for item in EXERCISES} == set(EXERCISE_TYPES)


def test_every_item_is_shape_valid():
    """五题型的形态契约（契约定稿 7）逐条过领域规则。"""
    for item in EXERCISES:
        problems = check_exercise_shape(
            type=item["type"],
            options=item.get("options"),
            answer=item.get("answer"),
            test_cases=item.get("test_cases"),
        )
        assert not problems, (item["slug"], problems)


def test_choice_and_multi_answer_keys_are_real_options():
    for item in EXERCISES:
        if item["type"] not in ("choice", "multi"):
            continue
        keys = set(item["options"])
        answers = [item["answer"]] if item["type"] == "choice" else item["answer"]
        assert set(answers) <= keys, item["slug"]
        if item["type"] == "multi":
            assert len(answers) >= 2, f"{item['slug']}：多选题正确答案至少 2 个键"
            assert len(answers) < len(keys), f"{item['slug']}：多选题不得全对"
            assert answers == sorted(answers), "种子内 multi 答案按字母序存储（契约定稿 7）"


def test_blank_answers_have_a_single_unambiguous_shape():
    """填空判分是 strip + casefold 全等：答案不得含内部空格歧义或多写法。"""
    for item in EXERCISES:
        if item["type"] != "blank":
            continue
        answer = item["answer"]
        assert answer == answer.strip() and answer, item["slug"]
        assert "\n" not in answer, item["slug"]


def test_blank_answers_are_not_printed_in_their_own_stems():
    """填空题答案以**独立 token** 出现在题干里 = 这道题不测量任何东西（抄题干即得 100）。

    种子初稿真出过这个缺陷（py-blank-01 的题干印着 `type(3.5)`），故固化成回归网。
    判定必须按 token 边界：py-blank-03 的答案 `cde` 是题干代码串 `"abcdefgh"` 的子串，
    但那不构成泄露 —— 裸 `in` 会把它误报。单字符答案跳过（误报成本高于收益）。
    """
    for item in EXERCISES:
        if item["type"] != "blank":
            continue
        answer = item["answer"]
        if len(answer) < 2 or not answer.isascii():
            continue
        # 前后不是字母/数字/下划线才算独立出现（type( → 命中；abcdefgh 里的 cde → 不命中）
        leaked = re.search(rf"(?<![A-Za-z0-9_]){re.escape(answer)}(?![A-Za-z0-9_])", item["stem"])
        assert leaked is None, (item["slug"], answer, item["stem"])


def test_knowledge_tags_are_within_the_closed_vocabulary_and_covered():
    counts = Counter()
    for item in EXERCISES:
        tags = item["knowledge_tags"]
        assert 1 <= len(tags) <= 2, item["slug"]
        assert set(tags) <= set(KNOWLEDGE_TAGS), (item["slug"], tags)
        counts.update(tags)
    thin = [tag for tag in KNOWLEDGE_TAGS if counts[tag] < 2]
    assert not thin, f"下列标签不足 2 题，画像与推荐无法闭环：{thin}"


def test_explanations_are_present():
    for item in EXERCISES:
        assert item["explanation"].strip(), item["slug"]


def test_visible_text_uses_the_ubiquitous_language():
    """M-5 教训：用户可见文案禁「题目」「试题」「错题」（术语表）。"""
    banned = ("题目", "试题", "错题")
    for item in EXERCISES:
        haystack = item["stem"] + " " + item["explanation"] + " " + " ".join(
            str(value) for value in (item.get("options") or {}).values()
        )
        for word in banned:
            assert word not in haystack, (item["slug"], word)


def test_slugs_are_unique_and_keys_are_derived_from_them():
    slugs = [item["slug"] for item in EXERCISES]
    assert len(set(slugs)) == 40
    for slug in slugs:
        derived = exercise_id_for(slug)
        assert derived == exercise_id_for(slug), "uuid5 必须稳定"
        assert derived == str(uuid.uuid5(uuid.NAMESPACE_URL, f"llm-code-tutor:exercise:{slug}"))


# ---------------------------------------------------------------- coding 自校验


@pytest.mark.parametrize(
    "item", CODING_ITEMS, ids=[item["slug"] for item in CODING_ITEMS]
)
def test_coding_reference_solution_passes_all_cases(item):
    """真执行器实测：参考答案必须通过该习题的**全部**用例。

    这里刻意不用 FakeExecutor —— 它按 source 内容模拟输出，只能证明编排接线，
    证明不了参考实现真能算出期望结果。
    """
    executor = SubprocessCodeExecutor()
    language = item["test_cases"]["language"]
    solution = item["answer"]["solution"]
    for word in FORBIDDEN_IN_SOLUTION:
        assert word not in solution, f"{item['slug']}：参考答案含黑名单写法 {word}"

    failures = []
    for index, case in enumerate(item["test_cases"]["cases"]):
        result = executor.execute(
            language=language, source=solution, stdin=case.get("stdin", "")
        )
        matched = result.stdout.strip() == case["expected_stdout"].strip()
        if result.status != "accepted" or not matched:
            failures.append(
                {
                    "case": index,
                    "status": result.status,
                    "stdin": case.get("stdin", ""),
                    "expected": case["expected_stdout"],
                    "actual": result.stdout,
                    "stderr": result.stderr[:200],
                }
            )
    assert not failures, f"{item['slug']} 参考答案未通过用例：{failures}"


def test_every_coding_exercise_has_at_least_two_cases():
    assert len(CODING_ITEMS) == TYPE_QUOTAS[TYPE_CODING]
    for item in CODING_ITEMS:
        assert len(item["test_cases"]["cases"]) >= 2, item["slug"]


# ---------------------------------------------------------------- 入库与幂等


@pytest.mark.asyncio
async def test_seed_exercises_writes_forty_published_seed_rows(session):
    created = await seed_exercises(session)
    await session.flush()

    rows = list((await session.execute(select(Exercise))).scalars().all())
    assert created == 40
    assert len(rows) == 40
    assert {row.source for row in rows} == {SOURCE_SEED}
    assert {row.status for row in rows} == {STATUS_PUBLISHED}
    assert {row.id for row in rows} == {exercise_id_for(item["slug"]) for item in EXERCISES}


@pytest.mark.asyncio
async def test_seed_exercises_is_idempotent(session):
    """连跑两次仍是 40 条且 id 集合不变（变异测试目标：去掉存在性检查即翻倍）。"""
    first = await seed_exercises(session)
    await session.commit()
    ids_after_first = {
        row.id for row in (await session.execute(select(Exercise))).scalars().all()
    }

    second = await seed_exercises(session)
    await session.commit()
    rows = list((await session.execute(select(Exercise))).scalars().all())

    assert (first, second) == (40, 0)
    assert len(rows) == 40
    assert {row.id for row in rows} == ids_after_first


@pytest.mark.asyncio
async def test_seed_exercises_does_not_overwrite_edits(session):
    """幂等是「跳过」而不是「重置」：管理员改过的题干必须活过第二次 make seed。"""
    await seed_exercises(session)
    await session.commit()
    row_id = exercise_id_for("py-choice-01")
    row = await session.get(Exercise, row_id)
    row.stem = "管理员改过的题干"
    await session.commit()

    assert await seed_exercises(session) == 0
    await session.commit()
    again = await session.get(Exercise, row_id)
    assert again.stem == "管理员改过的题干"


@pytest.mark.asyncio
async def test_total_seed_entry_creates_one_admin_one_config_and_forty_exercises(session):
    """迁移后总入口语义：`seed()` 一次 → User=1、ModelConfig=1、Exercise=40。"""
    await seed_all(session)
    await session.commit()

    counts = {
        "users": (await session.execute(select(func.count()).select_from(User))).scalar_one(),
        "configs": (
            await session.execute(select(func.count()).select_from(ModelConfig))
        ).scalar_one(),
        "exercises": (
            await session.execute(select(func.count()).select_from(Exercise))
        ).scalar_one(),
    }
    assert counts == {"users": 1, "configs": 1, "exercises": 40}
