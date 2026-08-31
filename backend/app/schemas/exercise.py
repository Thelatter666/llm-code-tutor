"""exercise / mistake 端点出入参（spec §6.2 exercise 与 mistake 行）。

Task 1 先落基础模型；跨题型写入校验（options/answer 键匹配、coding 必带
test_cases）与 admin CRUD 模型在对应任务补全。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.exercise.judging import EXERCISE_TYPES

STEM_MAX = 2000
EXPLANATION_MAX = 4000
OPTION_MAX = 500


class ExerciseIn(BaseModel):
    """习题写入入参；`difficulty` 1-5 与题型枚举在此拒绝（spec §5）。"""

    type: str = Field(pattern=f"^({'|'.join(EXERCISE_TYPES)})$")
    stem: str = Field(min_length=1, max_length=STEM_MAX)
    options: dict[str, str] | None = None
    answer: Any = None
    test_cases: dict | None = None
    explanation: str = Field(default="", max_length=EXPLANATION_MAX)
    knowledge_tags: list[str] = Field(default_factory=list)
    difficulty: int = Field(ge=1, le=5)
    status: str = Field(default="draft", pattern="^(draft|published)$")


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
