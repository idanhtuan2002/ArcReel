import logging

import pytest

from lib.logging_config import _HANDLER_ATTR, setup_logging


class TestSetupLogging:
    def test_sets_root_level(self):
        setup_logging(level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_default_level_is_info(self):
        setup_logging()
        assert logging.getLogger().level == logging.INFO

    def test_adds_handler_to_root(self):
        setup_logging()
        root = logging.getLogger()
        assert any(getattr(h, _HANDLER_ATTR, False) for h in root.handlers)

    def test_log_format_contains_level_and_name(self):
        setup_logging(level="INFO")
        root = logging.getLogger()
        our_handler = next(h for h in root.handlers if getattr(h, _HANDLER_ATTR, False))
        formatter = our_handler.formatter
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "INFO" in formatted
        assert "test.module" in formatted
        assert "hello world" in formatted

    def test_env_variable_override(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        setup_logging()
        assert logging.getLogger().level == logging.WARNING

    def test_idempotent_no_duplicate_handlers(self):
        setup_logging()
        setup_logging()
        root = logging.getLogger()
        our_handlers = [h for h in root.handlers if getattr(h, _HANDLER_ATTR, False)]
        assert len(our_handlers) == 1

    def teardown_method(self):
        """每个测试后清理 root logger handlers。"""
        root = logging.getLogger()
        root.handlers = [h for h in root.handlers if not getattr(h, _HANDLER_ATTR, False)]
        root.setLevel(logging.WARNING)


def test_redacting_formatter_masks_credentials_and_signed_urls_in_messages_and_tracebacks() -> None:
    import logging

    from lib.logging_config import RedactingFormatter

    formatter = RedactingFormatter(fmt="%(message)s")
    secret = "sk-proj-" + "a1b2c3d4e5f6g7h8"

    def _fail() -> None:
        raise RuntimeError(
            f"401 Authorization: Bearer {secret} for https://cdn.invalid/obj.mp4?X-Amz-Signature=deadbeef"
        )

    with pytest.raises(RuntimeError) as raised:
        _fail()
    record = logging.LogRecord(
        "lib.video_backends.base",
        logging.WARNING,
        __file__,
        1,
        "provider said %s via %s",
        (f"api_key={secret}", "https://user:hunter2@host.invalid/path?token=abc"),
        (raised.type, raised.value, raised.tb),
    )

    rendered = formatter.format(record)

    assert secret not in rendered
    assert "deadbeef" not in rendered
    assert "hunter2" not in rendered
    assert "token=abc" not in rendered
    assert "RuntimeError" in rendered
    assert "https://cdn.invalid/obj.mp4" in rendered
