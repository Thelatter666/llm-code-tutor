"""M-3 信封锁：全部 JSON 端点的 200 响应必须声明统一信封（C5 击杀前提）。

例外清单（清理批次裁定 R5）：两个 SSE 端点返回 `text/event-stream`，
`{code, message, data, request_id}` 无法描述事件流，豁免 response_model。
"""

import pytest

from app.main import app

SSE_PATHS = {
    ("/api/v1/chat/conversations/{conversation_id}/messages", "post"),
    ("/api/v1/exercises/{exercise_id}/hint", "post"),
}

ENVELOPE_REQUIRED = {"code", "message", "data", "request_id"}


@pytest.fixture(scope="module")
def schema():
    return app.openapi()


def _resolve(ref_schema, components):
    node = ref_schema
    while "$ref" in node:
        name = node["$ref"].split("/")[-1]
        node = components[name]
    return node


def test_all_json_endpoints_declare_envelope(schema):
    components = schema["components"]["schemas"]
    checked = 0
    for path, item in schema["paths"].items():
        if not path.startswith(("/api/v1", "/health")):
            continue  # SPA catch-all（FileResponse）与静态挂载不属信封端点
        for method, op in item.items():
            if method not in ("get", "post", "patch", "put", "delete"):
                continue
            if (path, method) in SSE_PATHS:
                assert "text/event-stream" in op["responses"]["200"]["content"]
                continue
            content = op["responses"]["200"]["content"]
            assert "application/json" in content, f"{method.upper()} {path}"
            raw = content["application/json"]["schema"]
            assert "ApiResponse" in str(raw), f"{method.upper()} {path}"
            resp = _resolve(raw, components)
            assert ENVELOPE_REQUIRED <= set(resp.get("properties", {})), (
                f"{method.upper()} {path} 缺信封字段"
            )
            checked += 1
    assert checked >= 54, f"JSON 端点数异常：{checked}"


def test_sse_endpoints_stay_unenveloped(schema):
    for path, method in SSE_PATHS:
        op = schema["paths"][path][method]
        assert "text/event-stream" in op["responses"]["200"]["content"]
