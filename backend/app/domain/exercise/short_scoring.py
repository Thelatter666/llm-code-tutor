"""简答题 AI 评分的领域规则（spec §5.1 路 4，CONTEXT.md「判分 Judging」）。

**为什么 prompt 不走 PromptAssembler**（契约定稿 5，已裁定）：四套主模板经
`_system.j2` 无条件注入防抄袭档位与底线内容，面向的是学生辅导输出；判分是
内部调用（Judging 意图完全豁免，spec §7.1），需要的是严格 JSON 输出契约。
system / user 两条消息由本模块构建，服务层包成 `ChatMessage`。

**Mock 口径（配置层判定，同 spec §8.4 对 /code/analyze 的处理）**：配置为
Mock 提供方时不发起 LLM 调用，用确定性启发式评分——学生作答与「参考答案 +
解析」的字符二元组重合度映射到 0-100。同一输入两次结果必然一致，可单测。

**硬规则**：`score < 60` 强制 `is_correct=false`（spec §5.1「得分 <60 视为
错误，计入错题本」）；模型给出的 is_correct 只在 ≥60 时被尊重。
"""

import json
import re
from typing import NamedTuple

# spec §5.1：得分 <60 视为错误
SHORT_PASS_SCORE = 60

SHORT_JUDGE_SYSTEM_PROMPT = """你是编程课程的判分助教，正在为简答题评分。这是系统内部判分调用，\
评分结果不会直接展示你的分析过程。

要求：
1. 对照参考答案与解析，评估学生作答是否覆盖了关键要点；
2. 只输出一个 JSON 对象，不要输出任何其他文字或代码围栏；
3. JSON 字段：score（0-100 整数）、is_correct（布尔，score>=60 为 true）、
   feedback（一句话中文点评，说明扣分原因）。
输出示例：{"score": 80, "is_correct": true, "feedback": "覆盖主要要点，步长说明有误"}"""


class MockShortVerdict(NamedTuple):
    """Mock 启发式评分结果（可按 `(score, is_correct, feedback)` 解包）。

    `judge_mode` 由服务层记录进 judge_detail。
    """

    score: int
    is_correct: bool
    feedback: str


class ShortJudgeParseError(ValueError):
    """模型输出不是合法的评分 JSON —— 服务层据此转 `5021`（不落库）。"""


def build_short_judge_user_prompt(
    stem: str, reference: str, explanation: str, student_answer: str
) -> str:
    """user 消息：题干 / 参考答案 / 解析 / 学生作答四要素（契约定稿 5）。"""
    return (
        "【题干】\n"
        f"{stem}\n\n"
        "【参考答案】\n"
        f"{reference or '（无）'}\n\n"
        "【解析】\n"
        f"{explanation or '（无）'}\n\n"
        "【学生作答】\n"
        f"{student_answer or '（未作答）'}"
    )


def mock_short_score(
    reference: str, explanation: str, student_answer: str
) -> MockShortVerdict:
    """确定性启发式：与「参考答案 + 解析」的字符二元组重合度 → 0-100。

    只在 Mock 配置下使用；其产出照常 `ai_scored=true` 落 judge_detail，
    但 `judge_mode=mock_heuristic`，前端据此展示「AI 参考评分（Mock 启发式）」
    ——降级必须可见（裁定 5）。
    """
    target = _bigrams(reference or explanation)
    submitted = _bigrams(student_answer)
    if not target:
        score = 0
    else:
        score = round(len(target & submitted) / len(target) * 100)
    score = max(0, min(100, score))
    is_correct = score >= SHORT_PASS_SCORE
    if is_correct:
        feedback = f"Mock 启发式评分：作答与参考答案重合度约 {score}%，仅供参考。"
    else:
        feedback = f"Mock 启发式评分：作答与参考答案重合度仅约 {score}%，未达通过线（{SHORT_PASS_SCORE}）。"
    return MockShortVerdict(score, is_correct, feedback)


def parse_judge_json(text: str) -> tuple[int, bool, str]:
    """解析模型评分输出 → `(score, is_correct, feedback)`。

    - 容忍 ```json 围栏与前后说明文字（真模型输出形态不可控）；
    - score 钳制到 0-100；
    - `score < 60` 强制 is_correct=False（spec §5.1 硬规则）。
    解析失败抛 `ShortJudgeParseError`，服务层转 `5021`。
    """
    payload = _loads_lenient(text)
    raw_score = payload.get("score")
    if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
        raise ShortJudgeParseError("评分 JSON 缺少数值型 score 字段")
    score = max(0, min(100, round(raw_score)))

    feedback = payload.get("feedback")
    if not isinstance(feedback, str):
        feedback = ""

    model_correct = payload.get("is_correct")
    is_correct = model_correct if isinstance(model_correct, bool) else score >= SHORT_PASS_SCORE
    if score < SHORT_PASS_SCORE:
        is_correct = False
    return score, is_correct, feedback


def _loads_lenient(text: str) -> dict:
    """先剥代码围栏，再取首个 `{` 到最后一个 `}` 之间的内容解析。"""
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    candidate = fence.group(1) if fence else text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ShortJudgeParseError("模型输出中找不到 JSON 对象")
    try:
        payload = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ShortJudgeParseError("评分输出不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise ShortJudgeParseError("评分输出不是 JSON 对象")
    return payload


def _bigrams(text: str) -> set[str]:
    """字符二元组集合；跳过空白，单字符退化为一元组。"""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return set()
    if len(chars) == 1:
        return {chars[0]}
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}
