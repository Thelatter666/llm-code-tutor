"""code 端点出入参（spec §6.2 code 行）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.code.analysis import ANALYSIS_LANGUAGES
from app.domain.code.execution import RUN_LANGUAGES

# 源码上限沿用 /code/analyze（spec §8.4 未另定，两处保持一致）
SOURCE_MAX = 20000
# stdin 不落 LLM、也不进哈希，只喂给子进程；给一个比源码宽松得多的上限
STDIN_MAX = 200000


class CodeAnalyzeIn(BaseModel):
    language: str = Field(pattern=f"^({'|'.join(ANALYSIS_LANGUAGES)})$")
    source: str = Field(min_length=1, max_length=SOURCE_MAX)


class CodeAnalysisOut(BaseModel):
    """spec §6.2 的最小集为 {static_report, ai_report, analysis_id}；
    `reused` 是增量字段 —— 前端据此提示「与上次分析相同，已复用历史结果」。"""

    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    language: str
    static_report: dict
    ai_report: dict | None = None
    reused: bool = False


# ---------------------------------------------------------------- 代码运行（P4）

class CodeRunIn(BaseModel):
    """spec §6.2：`POST /code/run {language, source, stdin}`。"""

    language: str = Field(pattern=f"^({'|'.join(RUN_LANGUAGES)})$")
    source: str = Field(min_length=1, max_length=SOURCE_MAX)
    stdin: str = Field(default="", max_length=STDIN_MAX)


class CodeRunOut(BaseModel):
    """spec §6.2 的七字段。`run_id` 指向落库的 `CodeRun` 行。"""

    model_config = ConfigDict(from_attributes=True)

    run_id: str
    status: str
    stdout: str
    stderr: str
    exit_code: int | None = None
    duration_ms: int
    limit_detail: dict | None = None


class CodeSessionIn(BaseModel):
    language: str = Field(pattern=f"^({'|'.join(RUN_LANGUAGES)})$")
    title: str = Field(default="未命名会话", max_length=100)
    source_code: str = Field(default="", max_length=SOURCE_MAX)


class CodeSessionPatch(BaseModel):
    """三个字段都可独立更新；`None` 表示「不改」，与「改成空串」区分。"""

    language: str | None = Field(default=None, pattern=f"^({'|'.join(RUN_LANGUAGES)})$")
    title: str | None = Field(default=None, max_length=100)
    source_code: str | None = Field(default=None, max_length=SOURCE_MAX)


class CodeSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    language: str
    title: str
    source_code: str
    updated_at: datetime


class CodeRunHistoryItem(BaseModel):
    """历史列表不含 stdout 全文以外的东西，但**含** limit_detail —— 学生回看
    「上次为什么被杀」需要它。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    language: str
    source_code: str
    status: str
    stdout: str
    stderr: str
    exit_code: int | None = None
    duration_ms: int
    limit_detail: dict | None = None
    created_at: datetime
