"""exercise / mistake 端点出入参（spec §6.2 exercise 与 mistake 行）。

Task 1 落基础模型；mistake 视图在 Task 9 补；跨题型写入校验（options/answer 键
匹配、coding 必带 test_cases）与 admin CRUD 模型在 Task 11 补全。
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.chat.policy import REVIEW_MY_CODE
from app.domain.exercise.hint import render_answer
from app.domain.exercise.judging import EXERCISE_TYPES
from app.domain.exercise.shapes import check_exercise_shape

STEM_MAX = 2000
EXPLANATION_MAX = 4000
OPTION_MAX = 500

_TYPE_PATTERN = f"^({'|'.join(EXERCISE_TYPES)})$"
_STATUS_PATTERN = "^(draft|published)$"


class ExerciseIn(BaseModel):
    """习题写入入参；`difficulty` 1-5 与题型枚举在此拒绝（spec §5）。

    跨题型形状校验（契约定稿 7）：choice/multi 必带 options 且答案键 ⊆ options，
    coding 必带 `test_cases.language` + 非空 cases。规则本体在领域层
    `domain/exercise/shapes.py`，种子（Task 13）复用同一份。
    """

    type: str = Field(pattern=_TYPE_PATTERN)
    stem: str = Field(min_length=1, max_length=STEM_MAX)
    options: dict[str, str] | None = None
    answer: Any = None
    test_cases: dict | None = None
    explanation: str = Field(default="", max_length=EXPLANATION_MAX)
    knowledge_tags: list[str] = Field(default_factory=list)
    difficulty: int = Field(ge=1, le=5)
    status: str = Field(default="draft", pattern=_STATUS_PATTERN)

    @model_validator(mode="after")
    def _cross_type_shape(self) -> "ExerciseIn":
        problems = check_exercise_shape(
            type=self.type,
            options=self.options,
            answer=self.answer,
            test_cases=self.test_cases,
        )
        if problems:
            raise ValueError("；".join(problems))
        return self


class ExercisePatch(BaseModel):
    """admin 更新入参：全部字段可选，**schema 外字段（含 `source`）一律 422**。

    `extra="forbid"` 是裁定 1 的修订：静默忽略未知字段属「看起来成功、实际没生效」
    的静默型失败。`source` 刻意不在字段表里 —— 它记录习题来历（seed/admin/ai），
    改它等于伪造历史。

    跨题型一致性由服务层在**合并后**校验（只改 answer 时也要与库里的 options 配套），
    这里不重复校验：合并前的局部字段无法判断形状。
    """

    model_config = ConfigDict(extra="forbid")

    type: str | None = Field(default=None, pattern=_TYPE_PATTERN)
    stem: str | None = Field(default=None, min_length=1, max_length=STEM_MAX)
    options: dict[str, str] | None = None
    answer: Any = None
    test_cases: dict | None = None
    explanation: str | None = Field(default=None, max_length=EXPLANATION_MAX)
    knowledge_tags: list[str] | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    status: str | None = Field(default=None, pattern=_STATUS_PATTERN)

    @model_validator(mode="after")
    def _requires_something_to_change(self) -> "ExercisePatch":
        if not self.model_fields_set:
            raise ValueError("PATCH 至少需要一个待更新字段")
        return self


class ExerciseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    stem: str
    options: dict | None = None
    answer: Any = None
    test_cases: dict | None = None
    explanation: str = ""
    knowledge_tags: list[str] = []
    difficulty: int
    source: str
    status: str
    created_by: str | None = None
    created_at: datetime


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    exercise_id: str
    answer: Any = None
    is_correct: bool | None = None
    score: int
    judge_detail: dict | None = None
    feedback: str | None = None
    attempt_no: int
    created_at: datetime


# ---------------------------------------------------------------- 学生端视图

class ExerciseListItem(BaseModel):
    """列表项：不含 answer / explanation / test_cases（提交前不得泄题）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    stem: str
    options: dict | None = None
    difficulty: int
    knowledge_tags: list[str] = []


class ExerciseDetail(BaseModel):
    """详情：列表项字段 + coding 题的执行语言；同样不泄题。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    stem: str
    options: dict | None = None
    difficulty: int
    knowledge_tags: list[str] = []
    language: str | None = None


class SubmitIn(BaseModel):
    answer: Any = None


class HintIn(BaseModel):
    """hint 请求体（契约定稿 3）：`{intent, answer?}`。

    `intent` 是**显式契约而非推断**（ADR-0005）：只接受两种学生可见意图，`judging`
    是内部判分意图、不对 HTTP 开放 —— 它落在 `Literal` 之外，传入即 422。
    `answer` 与 submit 同形；`review_my_code` 必填，否则「批改我的作答」无物可批改。
    """

    intent: Literal["seek_answer", "review_my_code"]
    answer: Any = None

    @model_validator(mode="after")
    def _review_requires_answer(self) -> "HintIn":
        if self.intent == REVIEW_MY_CODE and not render_answer(self.answer).strip():
            raise ValueError("批改我的作答需要同时提交当前作答内容 answer")
        return self


class SubmitOut(BaseModel):
    """判分结果：提交后揭示正确答案与解析（spec §5.1 前端展示需求）。

    `ai_scored` 是前端「AI 参考评分」标识的开关；配合 judge_detail.judge_mode
    区分 model / mock_heuristic 两种标注（降级必须可见）。
    """

    submission_id: str
    exercise_id: str
    answer: Any = None
    is_correct: bool | None = None
    score: int
    judge_detail: dict | None = None
    feedback: str | None = None
    attempt_no: int
    created_at: datetime
    correct_answer: Any = None
    explanation: str = ""
    ai_scored: bool = False


# ---------------------------------------------------------------- 错题本视图

class MistakeEntryOut(BaseModel):
    """错题条目 + 习题摘要（spec §6.2 mistake 行）。

    嵌套的 `exercise` 复用 `ExerciseListItem` —— 学生视图不含 answer /
    explanation / test_cases，错题本列表因此天然不泄题。
    """

    id: str
    exercise_id: str
    wrong_count: int
    consecutive_correct: int
    last_wrong_answer: Any = None
    last_wrong_at: datetime | None = None
    mastered: bool
    mastered_at: datetime | None = None
    exercise: ExerciseListItem


class WeakKnowledgePointOut(BaseModel):
    """薄弱知识点（CONTEXT.md「WeakKnowledgePoint」）：实时聚合，无独立表。"""

    knowledge_tag: str
    wrong_count: int


class RecommendationItemOut(BaseModel):
    """推荐项；`filled_by` 区分画像推荐与随机补足，标注必须可见（spec §8.5）。"""

    exercise: ExerciseListItem
    filled_by: str


class RecommendationsOut(BaseModel):
    items: list[RecommendationItemOut]
    weak_tags: list[str] = []
