from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import install_spa_fallback


def _dist(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "index.html").write_text("<h1>app</h1>")
    return tmp_path


def test_unknown_path_falls_back_to_index(tmp_path):
    app = FastAPI()
    install_spa_fallback(app, _dist(tmp_path))
    r = TestClient(app).get("/some/spa/route")
    assert r.status_code == 200
    assert "app" in r.text


def test_api_path_is_not_swallowed(tmp_path):
    """Starlette 按注册顺序匹配：API 路由必须先于 catch-all 注册。"""
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    install_spa_fallback(app, _dist(tmp_path))
    assert TestClient(app).get("/api/v1/ping").json() == {"ok": True}


def test_missing_dist_dir_is_noop(tmp_path):
    app = FastAPI()
    install_spa_fallback(app, tmp_path / "nope")
    assert TestClient(app).get("/anything").status_code == 404


def test_unknown_api_path_returns_4040(tmp_path):
    """M12：catch-all 内的 api/ 分支可被真实触发——未注册的 /api 路径会落到这里。"""
    from app.core.errors import ApiError
    from app.core.errors import install_exception_handlers

    app = FastAPI()
    install_exception_handlers(app)
    install_spa_fallback(app, _dist(tmp_path))

    r = TestClient(app, raise_server_exceptions=False).get("/api/v1/not-registered")
    assert r.json()["code"] == 4040
