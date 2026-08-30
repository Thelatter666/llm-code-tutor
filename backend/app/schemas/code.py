"""code 端点出入参（spec §6.2 code 行）。"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.code.analysis import ANALYSIS_LANGUAGES


class CodeAnalyzeIn(BaseModel):
    language: str = Field(pattern=f"^({'|'.join(ANALYSIS_LANGUAGES)})$")
    source: str = Field(min_length=1, max_length=20000)


class CodeAnalysisOut(BaseModel):
    """spec §6.2 的最小集为 {static_report, ai_report, analysis_id}；
    `reused` 是增量字段 —— 前端据此提示「与上次分析相同，已复用历史结果」。"""

    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    language: str
    static_report: dict
    ai_report: dict | None = None
    reused: bool = False
