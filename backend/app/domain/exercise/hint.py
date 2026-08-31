"""习题辅导（hint）的问题串构建与模板选择（spec §6.2 / §7.1 / §7.2，零 IO）。

**为什么两种意图的问题串内容不同**（契约定稿 3 + ADR-0005）：

- `seek_answer`（「获取思路」）**受防抄袭档位约束**，所以问题串里**不得**出现参考
  答案与解析。档位是提示词层的软约束 —— 一旦模型不听话把实现吐出来，泄题的就是
  这条串本身；不给它答案，是最便宜的硬保证。
- `review_my_code`（「批改我的作答」）**豁免档位**：学生已经写出作答，给出改进
  版本与参考答案不构成抄袭（spec §7.1 豁免表）。此时参考答案、解析与学生作答都要
  给，模型才能定位错误根因。

**RAG 检索 query 取 `stem + knowledge_tags`，不含学生作答**（spec §7.2）：把错误
答案带进检索会污染相似度，同一知识点在两个入口的答案质量会差一档。

模板选择：`seek_answer` → `exercise_hint.j2`（引导式提示）、`review_my_code` →
`mistake_review.j2`（归因讲解）。两者均已在 `PromptAssembler.TEMPLATES` 注册，
本批不改模板文件。底线由 `_floor.j2` 无条件注入 —— 免的是档位，不是底线。
"""

from app.domain.chat.policy import REVIEW_MY_CODE, SEEK_ANSWER
from app.domain.exercise.judging import (
    TYPE_BLANK,
    TYPE_CHOICE,
    TYPE_CODING,
    TYPE_MULTI,
    TYPE_SHORT,
)

# 模板名是 `PromptAssembler.TEMPLATES` 的子集（装配器侧再校验一次）
TEMPLATE_HINT = "exercise_hint"
TEMPLATE_MISTAKE_REVIEW = "mistake_review"

TEMPLATES_BY_INTENT = {
    SEEK_ANSWER: TEMPLATE_HINT,
    REVIEW_MY_CODE: TEMPLATE_MISTAKE_REVIEW,
}

# 题型对用户可见的中文措辞（术语表：习题=Exercise，题型不是实体名，可直译）
TYPE_LABELS = {
    TYPE_CHOICE: "单选题",
    TYPE_MULTI: "多选题",
    TYPE_BLANK: "填空题",
    TYPE_SHORT: "简答题",
    TYPE_CODING: "编程题",
}

# 只有这两种题型的选项需要随题干一起给出
_TYPES_WITH_OPTIONS = (TYPE_CHOICE, TYPE_MULTI)


def template_for(intent: str) -> str:
    """该意图使用的提示词主模板。

    `judging` 是内部判分意图，不对 HTTP 开放也不走装配器（见
    `domain/exercise/short_scoring.py`），因此这里没有它的模板 —— 误传即报错，
    不静默回退到 `exercise_hint`，否则豁免语义会被悄悄替换。
    """
    try:
        return TEMPLATES_BY_INTENT[intent]
    except KeyError as exc:
        raise ValueError(f"该意图没有对应的习题辅导模板：{intent}") from exc


def build_retrieval_query(*, stem: str, knowledge_tags: list[str] | None = None) -> str:
    """RAG query = 题干 + 知识点标签，**不含学生作答**（spec §7.2）。"""
    tags = [tag for tag in (knowledge_tags or []) if tag]
    return " ".join([stem.strip()] + tags).strip()


def render_answer(answer: object) -> str:
    """把各题型的 answer 形态渲染成可读文本（契约定稿 7 的形态在此收口）。

    - choice `"B"` / blank / short 字符串：原样
    - multi `["A","C"]`：`A、C`
    - coding 学生作答 `{"source": 源码}` 与题库参考答案 `{"language", "solution"}`：
      取源码本体（键优先 source，其次 solution）
    """
    if answer is None:
        return ""
    if isinstance(answer, str):
        return answer
    if isinstance(answer, list):
        return "、".join(str(item) for item in answer)
    if isinstance(answer, dict):
        for key in ("source", "solution"):
            value = answer.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    return str(answer)


def is_student_answer(answer: object) -> bool:
    """该值是否是**学生形态**的作答（与 `submit` 的 answer 同形，契约定稿 7）。

    刻意不等于「`render_answer` 非空」：参考答案的形态 `{"language","solution"}`
    也能渲染出文本，但它不是学生作答 —— 若 hint 收它，就会出现「同一份 body 能问
    批改、提交判分却必然 4220」的契约分裂（学生以为答了，实际判不了）。
    数字/布尔等标量同理：没有哪种题型的作答长这样。
    """
    if isinstance(answer, str):
        return bool(answer.strip())
    if isinstance(answer, list):
        return any(isinstance(item, str) and item.strip() for item in answer)
    if isinstance(answer, dict):
        # 学生编程题只交 source；带 solution 的是题库参考答案，不接受
        source = answer.get("source")
        return isinstance(source, str) and bool(source.strip())
    return False


def build_hint_question(
    *,
    intent: str,
    exercise_type: str,
    stem: str,
    options: dict | None = None,
    knowledge_tags: list[str] | None = None,
    reference_answer: object = None,
    explanation: str | None = None,
    student_answer: object = None,
) -> str:
    """组装发给模型的习题上下文问题串。

    `seek_answer` 只含题干、选项与知识点标签；`review_my_code` 额外含参考答案、
    解析与学生作答 —— 差异就是这两种意图的契约边界。
    """
    sections = [
        f"【题型】{TYPE_LABELS.get(exercise_type, exercise_type)}",
        f"【题干】{stem.strip()}",
    ]
    if exercise_type in _TYPES_WITH_OPTIONS and options:
        lines = "\n".join(f"{key}. {options[key]}" for key in sorted(options))
        sections.append(f"【选项】\n{lines}")
    tags = [tag for tag in (knowledge_tags or []) if tag]
    if tags:
        sections.append("【知识点】" + "、".join(tags))

    if intent == REVIEW_MY_CODE:
        sections.append(f"【参考答案】{render_answer(reference_answer) or '（无）'}")
        sections.append(f"【解析】{(explanation or '').strip() or '（无）'}")
        sections.append(f"【我的作答】{render_answer(student_answer) or '（未作答）'}")

    return "\n\n".join(sections)
