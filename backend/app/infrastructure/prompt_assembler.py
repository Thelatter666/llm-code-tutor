"""提示词装配器（CONTEXT.md「提示词装配器 PromptAssembler」）。

组合防抄袭策略、RAG 上下文与 Jinja2 模板，产出最终 prompt。

**底线为什么在这里是「无开关」的**（spec §7.1 / §3.2 权衡 10）：
底线条文写在 `prompts/_floor.j2` 里，由 `_system.j2` **无条件 include**。装配器
只把 `floor_hit`（是否命中底线规则）作为渲染变量传进去，用于强化提示；
不存在任何能跳过该 include 的参数。若要绕过底线，必须改模板文件本身 ——
而模板是代码评审可见的静态资产，不是运行时配置。
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.domain.chat.policy import resolve_mode
from app.infrastructure.ports.llm import ChatMessage

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

_SYSTEM_TEMPLATE = "_system.j2"
_USER_TEMPLATE = "_user.j2"


def _default_env() -> Environment:
    # 模板产出的是 prompt 文本而非 HTML，不转义；autoescape 关闭以免中文与
    # 代码片段被转成实体
    return Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        autoescape=select_autoescape(default=False, default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )


class PromptAssembler:
    """把档位 / 底线 / 引用 / 历史装配成 `ChatMessage` 列表。"""

    TEMPLATES = ("rag_qa", "code_review", "exercise_hint", "mistake_review")

    def __init__(self, env: Environment | None = None) -> None:
        self._env = env or _default_env()

    def assemble(
        self,
        template: str,
        *,
        question: str,
        mode: str | None,
        intent: str,
        citations: list[dict] | None = None,
        history: list[dict] | None = None,
        floor_hit: str | None = None,
    ) -> list[ChatMessage]:
        """返回 `[system, *history, user]`。

        `mode` 传的是后台配置的档位；豁免意图会被 `resolve_mode` 解析为 `None`，
        此时模板走 exempt 分支 —— 免档位，不免底线（ADR-0005）。
        """
        if template not in self.TEMPLATES:
            raise ValueError(f"未知的提示词模板：{template}，可选 {self.TEMPLATES}")

        effective_mode = resolve_mode(intent, mode)
        system = self._env.get_template(_SYSTEM_TEMPLATE).render(
            body_template=f"{template}.j2",
            mode=effective_mode,
            exempt=effective_mode is None,
            floor_hit=floor_hit,
        )
        user = self._env.get_template(_USER_TEMPLATE).render(
            question=question, citations=citations or []
        )

        messages = [ChatMessage(role="system", content=system)]
        for item in history or []:
            messages.append(ChatMessage(role=item["role"], content=item["content"]))
        messages.append(ChatMessage(role="user", content=user))
        return messages
