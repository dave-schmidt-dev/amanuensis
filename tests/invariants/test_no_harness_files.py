"""Gate test for INV-2 (No harness-specific files at project root).

Quoting INVARIANTS.md INV-2 verbatim:

    No ``CLAUDE.md``, ``AGENTS.md``, ``GEMINI.md``, or ``README.md`` at
    the amanuensis project root. Documentation lives in ``docs/``
    (human-facing, build-step-derived).

What this gate certifies
------------------------
Four cases:

1. A clean workspace (no forbidden files) passes.
2. A workspace with a hand-authored ``mappings/README.md`` (lacking the
   ``<!-- amanuensis-generated: do not edit -->`` marker) is flagged.
3. A workspace whose ``mappings/README.md`` carries the generator marker
   is accepted.
4. The ``no-harness-files`` pre-commit hook in ``.pre-commit-config.yaml``
   names every file in the ``FORBIDDEN`` tuple — so the shell gate and
   the pytest gate stay in sync.

Scope
-----
Cases 1-3 use fixture workspaces under ``tmp_path``. Case 4 reads the
live ``.pre-commit-config.yaml`` from the repo root and is a static
consistency check, not a filesystem walk.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.invariants

FORBIDDEN = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "README.md")

# Repo root: tests/invariants/test_no_harness_files.py -> tests/invariants/
# -> tests/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_root_scan_clean(clean_workspace: Path) -> None:
    """Case 1: a workspace with no forbidden files at root passes."""
    for name in FORBIDDEN:
        assert not (clean_workspace / name).exists()


def test_hand_authored_readme_fails(workspace_with_hand_authored_readme: Path) -> None:
    """Case 2: a hand-authored README (no generator marker) is flagged.

    The test does not scan the root (the fixture puts the README under
    ``mappings/`` to avoid polluting the root scan), but confirms the
    absence of the marker — callers responsible for enforcing INV-2
    must reject such files.
    """
    bad = workspace_with_hand_authored_readme / "mappings" / "README.md"
    assert bad.is_file()
    assert "<!-- amanuensis-generated:" not in bad.read_text(encoding="utf-8")


def test_marker_readme_passes(workspace_with_marker_readme: Path) -> None:
    """Case 3: a generator-written README (marker present) is accepted."""
    good = workspace_with_marker_readme / "mappings" / "README.md"
    assert good.is_file()
    assert "<!-- amanuensis-generated: do not edit -->" in good.read_text(encoding="utf-8")


def test_precommit_hook_parity() -> None:
    """Case 4: the ``no-harness-files`` pre-commit hook lists every forbidden name.

    Keeps the shell-level gate and the pytest-level gate in sync: adding a
    new entry to ``FORBIDDEN`` here without updating ``.pre-commit-config.yaml``
    (or vice versa) will trip this test.
    """
    cfg_path = _REPO_ROOT / ".pre-commit-config.yaml"
    assert cfg_path.is_file(), f"missing .pre-commit-config.yaml at {cfg_path}"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    hooks: list[dict[str, object]] = []
    for repo in cfg.get("repos", []):
        for h in repo.get("hooks", []):
            if h.get("id") == "no-harness-files":
                hooks.append(h)
    assert hooks, "no-harness-files pre-commit hook not found in .pre-commit-config.yaml"
    entry = hooks[0].get("entry", "")
    for name in FORBIDDEN:
        assert name in entry, (
            f"pre-commit hook 'no-harness-files' entry is missing {name!r}. "
            "Update .pre-commit-config.yaml to match the FORBIDDEN tuple."
        )
