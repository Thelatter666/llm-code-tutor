from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

CODE_STATUS = {
    4010: 401,
    4030: 403,
    4040: 404,
    4090: 409,
    4290: 429,
    5000: 500,
    5021: 502,
    5032: 503,
}


class ApiError(Exception):
    def __init__(
        self,
        code: int,
        message: str,
        status: int | None = None,
        *,
        data: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.status = status or CODE_STATUS.get(code, 400)
        # 错误也需要带结构化数据：如 §8.7 的 409 要回传 need_rebuild 与待重建清单
        self.data = data
        super().__init__(message)


def _payload(code: int, message: str, request_id: str, data: dict | None = None) -> dict:
    return {"code": code, "message": message, "data": data, "request_id": request_id}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status,
            content=_payload(
                exc.code,
                exc.message,
                getattr(request.state, "request_id", ""),
                exc.data,
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=_payload(5000, "服务器内部错误", getattr(request.state, "request_id", "")),
        )
