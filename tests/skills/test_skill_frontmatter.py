"""Validate the shipped skill files in ``src/amanuensis/skills/``.

Each skill file is YAML frontmatter + Markdown body. This test parses
every shipped skill, asserts the required frontmatter fields are
present and well-typed, and asserts the role-set invariants the M7.1
plan codifies: exactly one orchestrator, at least two active roles
(Extractor + Auditor), and at least three stub roles (Contrarian,
Constructive, Premortem).

The shipped skill body is the contract between the orchestrator and
the supervisor LLM; frontmatter is what the dispatch driver and
``amanuensis install-skills`` machinery reads programmatically.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from amanuensis.skills._frontmatter import split_frontmatter

SKILLS_DIR = Path(__file__).resolve().parents[2] / "src" / "amanuensis" / "skills"

REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "role",
    "version",
    "active",
    "stub",
    "expects_substrate",
    "phase",
    "cli_commands_invoked",
)

VALID_ROLES: tuple[str, ...] = (
    "orchestrator",
    "extractor",
    "auditor",
    "contrarian",
    "constructive",
    "premortem",
    "map-resolve",
    "map-audit",
    # Phase 2b M5 — Connector role.
    "connect",
)


def _iter_skill_files() -> Iterator[Path]:
    yield from sorted(SKILLS_DIR.glob("*.md"))


def test_skills_directory_exists() -> None:
    assert SKILLS_DIR.is_dir(), f"skills directory missing: {SKILLS_DIR}"


def test_at_least_one_skill_file_present() -> None:
    files = list(_iter_skill_files())
    assert files, f"no .md skill files found under {SKILLS_DIR}"


@pytest.mark.parametrize("skill_path", list(_iter_skill_files()), ids=lambda p: p.name)
def test_skill_frontmatter_is_well_formed(skill_path: Path) -> None:
    text = skill_path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    assert body.strip(), f"{skill_path.name}: body is empty"

    for field in REQUIRED_FIELDS:
        assert field in fm, f"{skill_path.name}: missing required field '{field}'"

    assert isinstance(fm["name"], str) and fm["name"], (
        f"{skill_path.name}: 'name' must be non-empty str"
    )
    assert isinstance(fm["description"], str) and fm["description"], (
        f"{skill_path.name}: 'description' must be non-empty str"
    )
    assert isinstance(fm["role"], str) and fm["role"], (
        f"{skill_path.name}: 'role' must be non-empty str"
    )
    assert isinstance(fm["version"], str) and fm["version"], (
        f"{skill_path.name}: 'version' must be non-empty str"
    )
    assert isinstance(fm["active"], bool), f"{skill_path.name}: 'active' must be bool"
    assert isinstance(fm["stub"], bool), f"{skill_path.name}: 'stub' must be bool"
    assert isinstance(fm["expects_substrate"], bool), (
        f"{skill_path.name}: 'expects_substrate' must be bool"
    )
    assert isinstance(fm["phase"], str) and fm["phase"], (
        f"{skill_path.name}: 'phase' must be non-empty str"
    )

    invoked: Any = fm["cli_commands_invoked"]
    assert isinstance(invoked, list), f"{skill_path.name}: 'cli_commands_invoked' must be a list"
    for entry in invoked:  # pyright: ignore[reportUnknownVariableType]
        assert isinstance(entry, str) and entry, (
            f"{skill_path.name}: 'cli_commands_invoked' entries must be non-empty str"
        )

    if fm["stub"] is True:
        assert fm["active"] is False, f"{skill_path.name}: stub skill must have active=false"
        assert "stub_reason" in fm, f"{skill_path.name}: stub skill must declare 'stub_reason'"
        assert isinstance(fm["stub_reason"], str) and fm["stub_reason"].strip(), (
            f"{skill_path.name}: 'stub_reason' must be non-empty str"
        )
    else:
        assert fm["active"] is True, f"{skill_path.name}: non-stub skill must have active=true"


def _all_frontmatters() -> list[dict[str, Any]]:
    frontmatters: list[dict[str, Any]] = []
    for path in _iter_skill_files():
        fm, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        frontmatters.append(fm)
    return frontmatters


def test_at_least_one_orchestrator_skill_exists() -> None:
    fms = _all_frontmatters()
    orchestrators = [fm for fm in fms if fm.get("role") == "orchestrator"]
    assert orchestrators, "no skill with role: orchestrator found"


def test_at_least_two_active_skills_exist() -> None:
    fms = _all_frontmatters()
    active = [fm for fm in fms if fm.get("active") is True]
    assert len(active) >= 2, f"expected at least 2 active skills, found {len(active)}"


def test_at_least_three_stub_skills_exist() -> None:
    fms = _all_frontmatters()
    stubs = [fm for fm in fms if fm.get("stub") is True]
    assert len(stubs) >= 3, f"expected at least 3 stub skills, found {len(stubs)}"


@pytest.mark.parametrize("skill_path", list(_iter_skill_files()), ids=lambda p: p.name)
def test_skill_role_in_valid_set(skill_path: Path) -> None:
    text = skill_path.read_text(encoding="utf-8")
    fm, _ = split_frontmatter(text)
    role = fm.get("role")
    assert role in VALID_ROLES, f"{skill_path.name}: role={role!r} not in VALID_ROLES"
