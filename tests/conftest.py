"""The host's per-user sandbox around every test here, so none reaches the real LOCALAPPDATA."""

from __future__ import annotations


def pytest_configure(config):
    """Absent without the host (the lib's own CI); any other import failure is a broken sandbox."""
    try:
        from procedo.core import testing
    except ModuleNotFoundError as exc:
        if exc.name not in ("procedo", "procedo.core"):
            raise
        return
    testing.register_plugin(config)
