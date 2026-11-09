"""A test here runs inside the host's per-user sandbox, never against the real folders."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("procedo.core.testing")  # the host-free CI has no sandbox to prove


def test_per_user_environment_is_redirected_into_the_test_folder(tmp_path):
    for name in ("APPDATA", "LOCALAPPDATA"):
        assert Path(os.environ[name]).resolve().is_relative_to(tmp_path.resolve())
