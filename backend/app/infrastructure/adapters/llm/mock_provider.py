import asyncio
import re
from typing import AsyncIterator

from app.infrastructure.ports.llm import (
    ChatMessage,
    Completion,
    LLMChunk,
    LLMParams,
    TextDelta,
    Usage,
)

# 档位标记由 PromptAssembler 写入 system prompt（app/prompts/_anti_plagiarism.j2）。
# Mock 是装配链路的下游，**解析 prompt 而不是另接一个参数** —— 这样它模拟的正是
# 真实模型看到的东西，档位一旦没写进 prompt，Mock 的行为也会同步退化，
# 缺陷不会在 Mock 下被掩盖。
_MODE_MARKER = re.compile(r"【防抄袭档位：(strict|guided|loose)】")
_EXEMPT_MARKER = "【防抄袭档位：本次豁免】"
_FLOOR_MARKER = re.compile(r"【本次请求已触发底线：([a-z_]+)】")
_CITATION_LINE = re.compile(r"^\[(\d+)\] 来源：(.+)$", re.MULTILINE)

_MODE_SCRIPTS = {
    "strict": (
        "我不能给出完整可运行代码，只给思路拆解："
        "1) 先明确输入与输出；2) 拆解为最小可验证步骤；3) 逐步实现并测试。"
        "关键概念讲清楚之后，下面只给伪代码骨架：\n"
        "def solve(input):  # TODO：先自己填一步\n"
        "    pass           # TODO：再验证第二步"
    ),
    "guided": (
        "先讲思路：把问题拆成「输入 → 处理 → 输出」三段，逐段验证。"
        "下面给一个不超过 10 行的最小片段，只用来解释单个概念，不是完整实现：\n"
        "def step(items):\n"
        "    return [x for x in items if x]  # 只演示这一段的写法\n"
        "完整实现需要你自己补齐，卡住时把报错贴给我。"
    ),
    "loose": (
        "请先自行尝试，再对照下面的实现。\n"
        "def solve(items):\n"
        "    result = []\n"
        "    for item in items:\n"
        "        result.append(item)\n"
        "    return result\n"
        "逐段讲解：第 1 行定义函数签名；第 2 行准备结果容器；"
        "第 3–4 行遍历并处理每个元素；第 5 行返回。"
    ),
}

_FLOOR_SCRIPTS = {
    "homework_ghostwriting": (
        "这个请求属于代做作业，按防抄袭底线我不能给出可直接提交的实现。"
        "下面只给引导：先自己写出第一版，把报错或卡住的那一步告诉我，我陪你改。"
    ),
    "exam_in_progress": (
        "考试 / 竞赛在线作答场景，我不能直接给答案。"
        "考后我可以把这道题完整讲一遍，现在先给你思路提示。"
    ),
}


class MockLLMProvider:
    """无需 API Key 即可跑通全链路的提供方（spec §7.3）。

    **抽取式生成**：取命中片段的首句拼装话术，逐字流式吐出，并在流末发出估算
    用量（估算用量 EstimatedUsage）。

    **同样遵守防抄袭三档**：档位标记由 `PromptAssembler` 写进 system prompt，
    Mock 解析它 —— 于是三档在 Mock 下的输出也确实不同，`strict` 档输出固定的
    引导话术。若 Mock 无视档位，演示与联调时「防抄袭是否生效」将完全无法观察。

    本实例被所有请求共享，**不保存任何 per-request 状态**。
    """

    @property
    def name(self) -> str:
        return "mock"

    def _render(self, messages: list[ChatMessage]) -> str:
        system = next((m.content for m in messages if m.role == "system"), "")
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        topic = last_user.strip().splitlines()[-1] if last_user.strip() else "该问题"

        parts = ["[Mock 模式]"]

        floor = _FLOOR_MARKER.search(system)
        if floor:
            parts.append(_FLOOR_SCRIPTS.get(floor.group(1), "本次请求触发防抄袭底线，只能给引导。"))

        snippet = self._extract_snippet(last_user)
        if snippet:
            parts.append(f"依据知识库片段：{snippet}")

        exempt = _EXEMPT_MARKER in system
        mode = _MODE_MARKER.search(system)
        if exempt:
            parts.append("本次为评改已写代码 / 判分请求，豁免防抄袭档位约束，下面给出改进版本与讲解。")
        elif mode:
            parts.append(_MODE_SCRIPTS.get(mode.group(1), ""))
        else:
            # 装配链路没写档位标记（例如直接单测本类）：退回通用话术
            parts.append(
                f"关于「{topic[:40]}」，给出如下思路："
                "1) 先明确输入与输出；2) 拆解为最小可验证步骤；3) 逐步实现并测试。"
            )
        return "".join(parts)

    def _extract_snippet(self, user_message: str) -> str:
        """spec §7.3 抽取式生成：取首个命中片段的首句。"""
        match = _CITATION_LINE.search(user_message)
        if not match:
            return ""
        # 片段正文是「来源：」行的下一行
        lines = user_message.splitlines()
        for i, line in enumerate(lines):
            if line.startswith(match.group(0)):
                if i + 1 < len(lines) and lines[i + 1].strip():
                    return _first_sentence(lines[i + 1].strip())
        return ""

    def _usage(self, text: str, messages: list[ChatMessage]) -> Usage:
        prompt = sum(len(m.content) for m in messages) // 4
        completion = len(text) // 4
        return Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            estimated=True,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        params: LLMParams,
        *,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[LLMChunk]:
        text = self._render(messages)
        for ch in text:
            if cancel is not None and cancel.is_set():
                break
            yield TextDelta(ch)
            await asyncio.sleep(0)
        # 被中断时仍发出用量，保证调用方能拿到 done 所需的 usage
        yield self._usage(text, messages)

    async def complete(self, messages: list[ChatMessage], params: LLMParams) -> Completion:
        text = self._render(messages)
        return Completion(text=text, usage=self._usage(text, messages))


def _first_sentence(text: str) -> str:
    for sep in ("。", "！", "？", ". "):
        idx = text.find(sep)
        if idx > 0:
            return text[: idx + 1]
    return text[:80]
