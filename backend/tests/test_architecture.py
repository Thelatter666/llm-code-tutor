"""分层红线机械化：services 只依赖端口，不 import 具体适配器。

spec §4.2 硬约束 2（adapter 由 ProviderRegistry 依据 ModelConfig 解析）。
健康检查 H-3 的四处违规（indexing 直连 parse_document、model_config_service
直连三个 embedding 适配器）经清理批次收口后，本用例把「grep -rn
infrastructure.adapters app/services/ = 0」固化为测试 —— C1/C2 变异
（回退直连 / 常量回退）会把 import 重新引回来，本用例即死。
"""

import ast
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parents[1] / "app" / "services"


def _imported_modules(tree: ast.AST) -> list[str]:
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def test_services_never_import_adapters():
    offenders = []
    for file in sorted(SERVICES_DIR.glob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for mod in _imported_modules(tree):
            if "infrastructure.adapters" in mod:
                offenders.append(f"{file.name} -> {mod}")
    assert not offenders, "services 直连适配器（违反 spec §4.2 硬约束 2）：" + "；".join(
        offenders
    )
