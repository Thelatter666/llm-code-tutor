from pydantic import BaseModel


class ApiResponse[T](BaseModel):
    code: int = 0
    message: str = "ok"
    data: T | None = None
    request_id: str


class Page[T](BaseModel):
    items: list[T]
    total: int
