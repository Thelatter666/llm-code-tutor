"""Mock 讲解模板与评改问题串（spec §8.4，纯领域层）。

spec §8.4：Mock 模式下 `ai_report` 由 `static_report` 模板化生成 —— 不发起
大模型调用，产出 Markdown（前端经消毒组件渲染，见 P3 前端 Task）。真提供方
的输入由 `build_review_question` 构造：静态摘要 + 完整源码，交给
PromptAssembler 按 `code_review` 模板装配（CONTEXT.md「AI 报告」：大模型基于
静态报告与源码生成讲解）。
"""

from app.domain.code.analysis import LANGUAGE_PYTHON, StaticReport

# 圈复杂度超过该值时，模板给出「拆分函数」建议
COMPLEXITY_SPLIT_THRESHOLD = 10


def render_mock_review(report: StaticReport) -> str:
    """把 StaticReport 模板化为 Markdown 讲解（spec §8.4 的 Mock 模式行为）。"""
    out: list[str] = [
        "## 静态解析结果",
        "",
        f"- 语言：{report.language}；共 {report.lines.total} 行"
        f"（代码 {report.lines.code} / 注释 {report.lines.comment} / 空行 {report.lines.blank}）",
    ]
    if report.functions or report.classes:
        worst = (
            f"最高 {report.complexity.max}（`{report.complexity.worst}`）"
            if report.complexity.worst
            else ""
        )
        out.append(
            f"- 函数 {len(report.functions)} 个，类 {len(report.classes)} 个；"
            f"平均圈复杂度 {report.complexity.average}，{worst}"
        )
    out.append("")

    if report.syntax_error is not None:
        out.extend(
            [
                "## 语法错误",
                "",
                f"第 {report.syntax_error.line} 行：{report.syntax_error.message}。",
                "",
                "请先修复语法错误再重新解析 —— 语法不通过时无法给出可靠的结构分析。",
            ]
        )
        return "\n".join(out)

    out.append("## 发现的问题")
    out.append("")
    issues: list[str] = []
    for v in report.issues.unused_variables:
        issues.append(
            f"{len(issues) + 1}. **未使用变量** `{v.name}`（第 {v.line} 行）："
            "赋值后从未读取，建议删除或补上后续逻辑。"
        )
    for b in report.issues.bare_excepts:
        if report.language == LANGUAGE_PYTHON:
            issues.append(
                f"{len(issues) + 1}. **裸 except**（第 {b.line} 行）：会连"
                " `KeyboardInterrupt` 一起吞掉，请改为捕获具体异常，例如"
                " `except ValueError as e:`。"
            )
        else:
            issues.append(
                f"{len(issues) + 1}. **空 catch 块**（第 {b.line} 行）：异常被静默吞掉，"
                "请至少记录日志，或确认后向上抛出。"
            )
    if issues:
        out.extend(issues)
    else:
        out.append("未发现未使用变量、裸 except / 空 catch 等明显问题。")
    out.append("")

    out.extend(["## 改进建议", ""])
    if report.complexity.max > COMPLEXITY_SPLIT_THRESHOLD:
        worst = report.complexity.worst or "复杂度最高的函数"
        out.append(
            f"- `{worst}` 的圈复杂度达到 {report.complexity.max}，"
            "建议按步骤拆分成小函数，让每一步都可单独测试。"
        )
    elif not issues:
        out.append("- 结构清晰。可以继续补上单元测试，或让我针对某个函数逐行讲解。")
    else:
        out.append("- 先处理上面列出的问题，再考虑整体结构与命名。")
    out.append("")
    out.append("（本讲解由静态报告模板化生成 —— Mock 模式，未调用大模型。）")
    return "\n".join(out)


def build_review_question(language: str, source: str, report: StaticReport) -> str:
    """构造评改问题串：静态摘要 + 完整源码。供 PromptAssembler 装配。"""
    summary: list[str] = [
        f"- 行数：共 {report.lines.total} 行（代码 {report.lines.code}）",
        f"- 函数 {len(report.functions)} 个 / 类 {len(report.classes)} 个；"
        f"平均圈复杂度 {report.complexity.average}，最高 {report.complexity.max}"
        + (f"（{report.complexity.worst}）" if report.complexity.worst else ""),
    ]
    if report.issues.unused_variables:
        names = "、".join(f"`{v.name}`（第 {v.line} 行）" for v in report.issues.unused_variables)
        summary.append(f"- 未使用变量：{names}")
    if report.issues.bare_excepts:
        where = "、".join(f"第 {b.line} 行" for b in report.issues.bare_excepts)
        kind = "裸 except" if language == LANGUAGE_PYTHON else "空 catch 块"
        summary.append(f"- {kind}：{where}")
    if report.syntax_error is not None:
        summary.append(
            f"- 语法错误：第 {report.syntax_error.line} 行 {report.syntax_error.message}"
        )

    return (
        f"请评改下面这份 {language} 代码，指出问题、解释原因并给出改进方向；"
        "输出请使用 Markdown，关键修改片段用代码块给出。\n\n"
        "静态解析结果（供参考，请结合源码判断）：\n"
        + "\n".join(summary)
        + "\n\n源码：\n"
        + f"```{language}\n{source}\n```"
    )
