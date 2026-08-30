from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.main import app

ROOT = Path(__file__).resolve().parents[2]


def _block(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _pip_lines(block: str) -> list[str]:
    return [ln for ln in block.splitlines() if "pip install" in ln]


async def test_health_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200 and r.json()["code"] == 0


def test_makefile_declares_required_targets():
    text = (ROOT / "Makefile").read_text()
    for target in (
        "install:",
        "install-lite:",
        "setup-local-embed:",
        "dev:",
        "serve:",
        "test:",
        "seed:",
    ):
        assert target in text, f"Makefile 缺少目标 {target}"


def test_install_includes_local_embed_extras():
    """B3：ADR-0004 的可用性前提——默认安装必须带本地 embedding。"""
    text = (ROOT / "Makefile").read_text()
    lines = _pip_lines(_block(text, "install:", "install-lite:"))
    assert lines, "install 目标中未找到 pip install 行"
    assert any("local-embed" in ln for ln in lines)


def test_install_lite_excludes_local_embed_extras():
    """B3：install-lite 必须真的跳过，否则名不副实。

    只看 pip install 行而非整个块 —— 块内的提示语含 setup-local-embed 字样。
    """
    text = (ROOT / "Makefile").read_text()
    lines = _pip_lines(_block(text, "install-lite:", "setup-local-embed:"))
    assert lines, "install-lite 目标中未找到 pip install 行"
    assert all("local-embed" not in ln for ln in lines)


def test_makefile_pins_single_worker():
    """ADR-0002：dev 与 serve 均必须固定 --workers 1。"""
    text = (ROOT / "Makefile").read_text()
    assert text.count("--workers 1") >= 2


def test_env_example_documents_app_secret():
    """M14：spec §8.8 的主密钥来源必须在示例中出现。"""
    text = (ROOT / "backend" / ".env.example").read_text()
    assert "APP_SECRET" in text
