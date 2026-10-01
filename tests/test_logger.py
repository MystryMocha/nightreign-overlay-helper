import logging

from src import logger


def test_uses_named_logger_not_root():
    logger.info("hello")
    root = logging.getLogger()
    assert not any(isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is not None
                   and getattr(h.stream, "name", "").endswith(".log") for h in root.handlers)
    named = logging.getLogger(logger.LOGGER_NAME)
    assert named.handlers and named.propagate is False


def test_debug_level_does_not_leak_to_third_party_loggers():
    logger.set_log_level(logging.DEBUG)
    try:
        assert logger.is_debug_enabled()
        assert not logging.getLogger("PIL.PngImagePlugin").isEnabledFor(logging.DEBUG)
    finally:
        logger.set_log_level(logging.INFO)


def test_error_without_exception_has_no_nonetype_trace(appdata):
    logger.error("outside of except")
    for h in logging.getLogger(logger.LOGGER_NAME).handlers:
        h.flush()
    content = "".join(p.read_text(encoding="utf-8") for p in (appdata / "nightreign-overlay-helper" / "logs").glob("*.log"))
    assert "outside of except" in content
    assert "NoneType: None" not in content


def test_error_inside_except_keeps_trace(appdata):
    try:
        1 / 0
    except ZeroDivisionError:
        logger.error("division failed")
    for h in logging.getLogger(logger.LOGGER_NAME).handlers:
        h.flush()
    content = "".join(p.read_text(encoding="utf-8") for p in (appdata / "nightreign-overlay-helper" / "logs").glob("*.log"))
    assert "ZeroDivisionError" in content


def test_debug_file_path_is_inside_log_dir():
    path = logger.get_debug_file_path("x.jpg")
    assert path.startswith(logger.LOG_DIR)
