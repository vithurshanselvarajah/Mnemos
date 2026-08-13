"""Tests for the logging configuration helper."""

from __future__ import annotations

import logging


def test_configure_logging_sets_info_level(backend_imports):
    from app.core.logging import configure_logging

    configure_logging(logging.INFO)
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_replaces_handlers(backend_imports):
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(logging.NullHandler())
    from app.core.logging import configure_logging

    configure_logging(logging.WARNING)
    assert len(root.handlers) == 1
    assert not isinstance(root.handlers[0], logging.NullHandler)


def test_configure_logging_quiet_httpx(backend_imports):
    from app.core.logging import configure_logging

    configure_logging(logging.DEBUG)
    for noisy in ("httpx", "httpcore", "urllib3"):
        assert logging.getLogger(noisy).level == logging.WARNING


def test_configure_logging_respects_debug(backend_imports):
    from app.core.logging import configure_logging

    configure_logging(logging.DEBUG)
    assert logging.getLogger().level == logging.DEBUG
