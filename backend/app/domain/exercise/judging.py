"""习题判题的纯规则（spec §5.1 四路 + CONTEXT.md「判分 Judging」）。

本模块零 IO：判题规则可以脱离数据库单测（spec §10 领域层）。
常量供 `infrastructure/persistence/models.py` 反向引用（与
`domain/knowledge/status.py` 同模式）。

判题四路（spec §5.1，语义照写死）：

- choice / blank：后端比对 answer 即时判分，0 或 100
- multi：全对 100 且正确；漏选（所选为正确答案的真子集）50 分且**错误**；
  含错选 0 分且错误；**空作答按未作答处理 0 分**（裁定 8：「漏选」的语义是
  「选了部分」，∅ 虽是数学意义上的真子集，不答不得 50）
- coding：按通过比例给分（执行编排在服务层，这里只做从用例结果到分数的
  纯换算）；15s 预算中止后未跑用例不计通过但计入分母
- short：转 AI 评分（spec §5.1 路 4），prompt 与解析在
  `domain/exercise/short_scoring.py`

四路的错题归集统一规则：`is_correct == false` 即入错题本（spec §5.1；
归集动作在服务层，本模块只产判定）。
"""

from dataclasses import dataclass, field

# --- 题型（spec §5 Exercise.type，五种齐备） ---
TYPE_CHOICE = "choice"
TYPE_MULTI = "multi"
TYPE_BLANK = "blank"
TYPE_SHORT = "short"
TYPE_CODING = "coding"
EXERCISE_TYPES = (TYPE_CHOICE, TYPE_MULTI, TYPE_BLANK, TYPE_SHORT, TYPE_CODING)

# --- 来源（spec §5 Exercise.source） ---
SOURCE_SEED = "seed"
SOURCE_ADMIN = "admin"
SOURCE_AI = "ai"
EXERCISE_SOURCES = (SOURCE_SEED, SOURCE_ADMIN, SOURCE_AI)

# --- 状态（spec §5 Exercise.status）：学生端只暴露 published ---
STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
EXERCISE_STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED)

# --- 判分档位（spec §5.1） ---
SCORE_FULL = 100
SCORE_MULTI_PARTIAL = 50
SCORE_ZERO = 0

# judge_detail.method 的封闭取值（契约定稿 8）
METHOD_DIRECT = "direct"
METHOD_EXECUTED = "executed"


@dataclass(frozen=True)
class JudgeOutcome:
    """一次判分的结论：分数、是否正确与 judge_detail。"""

    score: int
    is_correct: bool
    detail: dict = field(default_factory=dict)


def _direct_detail(passed: bool) -> dict:
    return {"method": METHOD_DIRECT, "passed": passed}


def judge_choice(correct: str, selected: object) -> JudgeOutcome:
    passed = isinstance(selected, str) and selected == correct
    score = SCORE_FULL if passed else SCORE_ZERO
    return JudgeOutcome(score, passed, _direct_detail(passed))


def judge_blank(correct: str, submitted: object) -> JudgeOutcome:
    """比对规则：去首尾空白 + casefold 忽略大小写（契约定稿 7）。"""
    if not isinstance(submitted, str):
        return JudgeOutcome(SCORE_ZERO, False, _direct_detail(False))
    passed = submitted.strip().casefold() == correct.strip().casefold()
    score = SCORE_FULL if passed else SCORE_ZERO
    return JudgeOutcome(score, passed, _direct_detail(passed))


def judge_multi(correct: list[str], selected: object) -> JudgeOutcome:
    """全对 100 / 真子集（漏选）50 / 含错选或空作答 0；漏选按错误处理。"""
    chosen = [s for s in (selected or []) if isinstance(s, str)]
    correct_set = set(correct)
    chosen_set = set(chosen)

    missing = sorted(correct_set - chosen_set)
    wrong = sorted(chosen_set - correct_set)

    if not chosen_set:
        # 空作答：未作答而不是漏选（裁定 8）
        return JudgeOutcome(SCORE_ZERO, False, {"method": METHOD_DIRECT, "missing": sorted(correct_set), "wrong": []})
    if wrong:
        return JudgeOutcome(SCORE_ZERO, False, {"method": METHOD_DIRECT, "missing": missing, "wrong": wrong})
    if chosen_set < correct_set:
        # 漏选：所选为正确答案的真子集 → 50 分且 is_correct=False（spec §5.1）
        return JudgeOutcome(SCORE_MULTI_PARTIAL, False, {"method": METHOD_DIRECT, "missing": missing, "wrong": []})
    return JudgeOutcome(SCORE_FULL, True, {"method": METHOD_DIRECT, "missing": [], "wrong": []})


def judge_coding(
    *, passed: int, total: int, budget_exceeded: bool, cases: list[dict]
) -> JudgeOutcome:
    """从用例结果换算分数：通过比例取整；未全部通过即错误（spec §5.1 路 3）。

    `cases` 是服务层逐用例执行后填好的 judge_detail.cases，这里原样带回。
    """
    if total <= 0:
        return JudgeOutcome(
            SCORE_ZERO,
            False,
            {"method": METHOD_EXECUTED, "budget_exceeded": budget_exceeded, "cases": cases},
        )
    score = round(passed / total * SCORE_FULL)
    return JudgeOutcome(
        score,
        passed == total,
        {
            "method": METHOD_EXECUTED,
            "budget_exceeded": budget_exceeded,
            "cases": cases,
        },
    )
