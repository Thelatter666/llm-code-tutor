"""习题种子（spec §11 P5 行：约 40 题，覆盖 Python 基础知识点，五种题型齐备）。

**幂等口径（契约定稿 6）**：Exercise 没有自然键（题干会被改、题型不是标识），
所以用 **uuid5 确定性主键** —— `uuid5(NAMESPACE_URL, "llm-code-tutor:exercise:<slug>")`，
slug 在数据里显式给定。写入前按主键查存在即跳过，不覆盖：管理员在后台改过的习题
不会被 `make seed` 打回原形，这与 admin / ModelConfig 的「已存在则跳过」同一语义。
不为此在 spec §5 之外新增列 —— 幂等判定落在主键的确定性上。

**形状与可解性**：每条数据在写入前过 `domain/exercise.shapes` 的跨题型规则（脏数据
直接抛错、不静默入库）；coding 题的参考答案必须对其全部 `test_cases` 通过，由
`tests/test_seed_exercises.py` 用**真** `SubprocessCodeExecutor` 参数化实测 ——
那是种子可解性的唯一证据（总指挥交接 §9 审阅重点）。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exercise.judging import SOURCE_SEED, STATUS_PUBLISHED
from app.domain.exercise.shapes import check_exercise_shape
from app.infrastructure.persistence.models import Exercise

# slug 命名空间：urn 前缀 + slug 唯一决定主键，换前缀等于换整批 id（勿改）
SLUG_URN_PREFIX = "llm-code-tutor:exercise:"

# 种子数据（Task 13 填充：choice 10 / multi 6 / blank 8 / short 8 / coding 8）
EXERCISES: list[dict] = []


def exercise_id_for(slug: str) -> str:
    """slug → 确定性主键。同一 slug 在任何机器、任何一次运行都得到同一 id。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{SLUG_URN_PREFIX}{slug}"))


def seedable(rows: list[dict]) -> list[dict]:
    """校验每条数据的形状，返回原列表（脏数据抛 `ValueError` 并点名 slug）。"""
    for item in rows:
        problems = check_exercise_shape(
            type=item["type"],
            options=item.get("options"),
            answer=item.get("answer"),
            test_cases=item.get("test_cases"),
        )
        if problems:
            raise ValueError(f"习题种子 {item.get('slug')} 不合法：{'；'.join(problems)}")
    return rows


async def seed_exercises(session: AsyncSession) -> int:
    """写入尚不存在的习题种子；返回本次新建条数。"""
    created = 0
    for item in seedable(EXERCISES):
        row_id = exercise_id_for(item["slug"])
        if await session.get(Exercise, row_id) is not None:
            continue
        session.add(
            Exercise(
                id=row_id,
                type=item["type"],
                stem=item["stem"],
                options=item.get("options"),
                answer=item["answer"],
                test_cases=item.get("test_cases"),
                explanation=item.get("explanation", ""),
                knowledge_tags=item.get("knowledge_tags", []),
                difficulty=item["difficulty"],
                source=SOURCE_SEED,
                # 种子即发布：spec §11 要求 P5 交付可演示题库，无需后台再点一次发布
                status=STATUS_PUBLISHED,
            )
        )
        created += 1
    return created
