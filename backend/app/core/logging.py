"""应用运行日志的统一配置。

P1 大量使用 `logger.exception` / `logger.warning` 记录降级与失败路径，但此前没有
统一配置 —— 默认只有 `WARNING` 及以上会输出到 stderr，且没有时间、模块名和
request_id 相关的结构，排查问题只能靠堆栈猜上下文。

**与审计日志的分工**：审计日志（`AuditLog` 表）记的是「谁在什么时候对什么做了什么」，
面向管理员追溯；这里配的是应用运行日志，面向开发/运维排查。两者不重复。

**为什么不做按请求注入 request_id**：日志是全局的，而 request_id 是请求局部的。
要做到每条日志都带 request_id 得用 `contextvars` + 自定义 Filter，是另一个量级的
改动；请求维度的追溯已经有统一响应里的 `request_id` 兜住，这里不重复造。
"""

import logging
import sys

from app.core.config import get_settings

# 默认格式：时间 · 级别 · 模块名 · 消息。模块名足够定位来源，不必打全 logger 名。
DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 第三方库太吵：下面这些只在 WARNING 及以上才放行
_NOISY_LOGGERS = ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore", "chromadb")


def setup_logging(level: str | None = None) -> None:
    """配置根 logger 的输出格式与级别；幂等，可重复调用。

    `level` 为空时按环境取：dev → INFO，其余 → WARNING。
    环境变量 `LOG_LEVEL` 优先（便于演示现场临时开 DEBUG 而不改代码）。
    """
    resolved = (level or "").strip().upper() or _default_level()

    root = logging.getLogger()
    handler = _ensure_handler(root)

    handler.setFormatter(logging.Formatter(DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT))
    root.setLevel(_coerce_level(resolved))

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _default_level() -> str:
    import os

    return os.environ.get("LOG_LEVEL") or (
        "INFO" if get_settings().env == "dev" else "WARNING"
    )


def _coerce_level(raw: str) -> int:
    level = logging.getLevelName(raw)
    return level if isinstance(level, int) else logging.INFO


def _ensure_handler(root: logging.Logger) -> logging.StreamHandler:
    """复用已有的 stdout handler，避免重复调用时刷出多份日志。"""
    for existing in root.handlers:
        if isinstance(existing, logging.StreamHandler) and existing.stream is sys.stdout:
            return existing

    handler = logging.StreamHandler(sys.stdout)
    root.addHandler(handler)
    return handler
