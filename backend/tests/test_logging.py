"""core/logging.py 的契约。

只验「配置本身是对的」，不断言具体输出 —— 格式字符串改了不该让测试失败。
"""

import logging

import pytest

from app.core.logging import _NOISY_LOGGERS, setup_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """改的是全局状态，用例结束必须还原，否则会污染整个测试会话。"""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_noisy = {name: logging.getLogger(name).level for name in _NOISY_LOGGERS}
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    for name, level in saved_noisy.items():
        logging.getLogger(name).setLevel(level)


def test_setup_logging_is_idempotent():
    """反复调用不得刷出多份日志 —— 常见于 reload 与测试重入。"""
    root = logging.getLogger()
    setup_logging()
    after_first = len(root.handlers)
    setup_logging()
    setup_logging()
    assert len(root.handlers) == after_first


def test_explicit_level_is_applied():
    setup_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_unknown_level_falls_back_to_info(caplog):
    """日志级别拼错不该让服务起不来 —— 比起不了床，多打点日志是小事。"""
    setup_logging("NOT_A_LEVEL")
    assert logging.getLogger().level == logging.INFO


def test_log_level_env_overrides_the_default(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    setup_logging()
    assert logging.getLogger().level == logging.ERROR


def test_noisy_third_party_loggers_are_quieted():
    """uvicorn.access 这类每请求一行，INFO 级会把应用日志完全淹没。"""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)
    setup_logging("DEBUG")
    for name in _NOISY_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING, name


def test_formatter_carries_timestamp_and_module():
    setup_logging("INFO")
    handler = next(
        h for h in logging.getLogger().handlers if isinstance(h, logging.StreamHandler)
    )
    record = logging.LogRecord(
        name="app.demo", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hi", args=(), exc_info=None,
    )
    text = handler.format(record)
    assert "app.demo" in text
    assert "hi" in text
    assert ":" in text  # 时间分隔符，确认 asctime 真的写进去了
