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
    def __init__(self, code: int, message: str, status: int | None = None):
        self.code = code
        self.message = message
        self.status = status or CODE_STATUS.get(code, 400)
        super().__init__(message)


def _payload(code: int, message: str, request_id: str) -> dict:
    return {"code": code, "message": message, "data": None, "request_id": request_id}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status,
            content=_payload(exc.code, exc.message, getattr(request.state, "request_id", "")),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=_payload(5000, "服务器内部错误", getattr(request.state, "request_id", "")),
        )
