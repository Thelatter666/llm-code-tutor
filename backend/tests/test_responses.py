from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import ApiError, install_exception_handlers
from app.core.responses import install_request_id, ok


def _build() -> TestClient:
    app = FastAPI()
    install_request_id(app)
    install_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret stack detail")

    @app.get("/biz")
    async def biz():
        raise ApiError(4040, "资源不存在")

    @app.get("/good")
    async def good():
        return ok({"a": 1}, request_id="rid-1")

    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_error_returns_5000_without_stack():
    r = _build().get("/boom")
    assert r.status_code == 500
    assert r.json()["code"] == 5000
    assert "secret stack detail" not in r.text


def test_api_error_maps_to_status_and_code():
    r = _build().get("/biz")
    assert r.status_code == 404
    assert r.json()["code"] == 4040


def test_ok_response_shape():
    body = _build().get("/good").json()
    assert body == {"code": 0, "message": "ok", "data": {"a": 1}, "request_id": "rid-1"}


def test_request_id_is_injected_and_echoed():
    assert _build().get("/good").headers.get("x-request-id")
