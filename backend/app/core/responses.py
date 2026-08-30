import uuid

from fastapi import FastAPI, Request


def install_request_id(app: FastAPI) -> None:
    @app.middleware("http")
    async def _mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


def ok(data=None, *, request_id: str, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data, "request_id": request_id}
