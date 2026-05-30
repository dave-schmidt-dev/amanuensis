"""Shared fixtures for ``tests/llm/`` — workspace marker + cache builders.

The M5 tests need a minimal workspace (with the INV-1 marker so the
underlying ``ReplayLog`` / ``Substrate`` constructors don't refuse).
This conftest mirrors the ``cli_workspace`` pattern from
``tests/cli/conftest.py`` without re-exporting the rest of that
fixture set — none of the M5 tests need the planted-atom substrate.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def llm_workspace(tmp_path: Path) -> Path:
    """An empty tmpdir with the INV-1 marker."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: llm-test\n",
        encoding="utf-8",
    )
    return tmp_path
