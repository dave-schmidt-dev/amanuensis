"""Write-isolation enforcement tests (M6.3, CV-5).

Five contracts:

1. Writing only within the allowed subtree ⇒ no violation reported.
2. Writing outside the allowed subtree ⇒ violation list contains that
   path.
3. Modifying a pre-existing file's mtime outside the allowed subtree ⇒
   violation.
4. Deletions are NOT reported (per module docstring).
5. The snapshot ignores skip directories (.venv / __pycache__ / .git).

T6.7 extension: ``map-resolve`` and ``map-audit`` output directories use
multi-component names (e.g. ``map-resolve-<hash>``). The isolation
machinery accepts them as valid ``allowed_subtree`` values just like
single-component role dirs (``extractor-<hash>``).

Phase 2b M4 extension: the new ``connect`` role lands its outputs under
``dispatch/outputs/connect-<inputs_hash>/`` per the spec. INV-11 demands
the same write-isolation contract as Phase 1 / Phase 2a roles. The
parametrized fixtures below cover ``connect-<hash>`` alongside the
existing map and extractor / auditor cases so the isolation machinery
remains role-agnostic.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from amanuensis.dispatch.isolation import (
    assert_no_unauthorized_mutation,
    snapshot_workspace_tree,
)


def _touch(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _bump_mtime(path: Path) -> None:
    """Force mtime forward without rewriting content."""
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 60))


def test_no_violation_when_role_only_writes_in_allowed_subtree(
    dispatch_workspace: Path,
) -> None:
    """The role writes only inside its assigned output dir ⇒ empty violations."""
    allowed = dispatch_workspace / "dispatch" / "outputs" / "test-1"
    allowed.mkdir(parents=True)

    # Plant a non-substrate file outside the allowed subtree.
    _touch(dispatch_workspace / "distillations" / "src" / "atoms" / "existing.md")

    before = snapshot_workspace_tree(dispatch_workspace, allowed_subtree=allowed)

    # Simulate the role writing to its own output dir.
    _touch(allowed / "output.yaml", "atoms: []\n")

    violations = assert_no_unauthorized_mutation(
        before, dispatch_workspace, allowed_subtree=allowed
    )
    assert violations == []


def test_violation_when_role_writes_outside_allowed_subtree(
    dispatch_workspace: Path,
) -> None:
    """The role writes to ``atoms/`` (forbidden) ⇒ violation reported."""
    allowed = dispatch_workspace / "dispatch" / "outputs" / "test-2"
    allowed.mkdir(parents=True)

    before = snapshot_workspace_tree(dispatch_workspace, allowed_subtree=allowed)

    forbidden = _touch(dispatch_workspace / "distillations" / "src" / "atoms" / "evil.md", "rogue")

    violations = assert_no_unauthorized_mutation(
        before, dispatch_workspace, allowed_subtree=allowed
    )
    assert forbidden.resolve() in violations


def test_violation_when_role_modifies_existing_file(dispatch_workspace: Path) -> None:
    """Mtime change on a pre-existing path outside allowed subtree ⇒ violation."""
    allowed = dispatch_workspace / "dispatch" / "outputs" / "test-3"
    allowed.mkdir(parents=True)
    existing = _touch(dispatch_workspace / "distillations" / "src" / "atoms" / "a.md")

    before = snapshot_workspace_tree(dispatch_workspace, allowed_subtree=allowed)
    # Ensure mtime resolution > 0 between snapshot and bump on fast FSes.
    time.sleep(0.01)
    _bump_mtime(existing)

    violations = assert_no_unauthorized_mutation(
        before, dispatch_workspace, allowed_subtree=allowed
    )
    assert existing.resolve() in violations


def test_deletion_is_not_reported_as_violation(dispatch_workspace: Path) -> None:
    """A role deleting a file is not reported (per the M6.3 contract)."""
    allowed = dispatch_workspace / "dispatch" / "outputs" / "test-4"
    allowed.mkdir(parents=True)
    victim = _touch(dispatch_workspace / "distillations" / "src" / "atoms" / "v.md")

    before = snapshot_workspace_tree(dispatch_workspace, allowed_subtree=allowed)
    victim.unlink()

    violations = assert_no_unauthorized_mutation(
        before, dispatch_workspace, allowed_subtree=allowed
    )
    assert violations == []


def test_snapshot_skips_dot_venv_pycache_git(dispatch_workspace: Path) -> None:
    """Files inside skip directories are NOT in the snapshot."""
    allowed = dispatch_workspace / "dispatch" / "outputs" / "test-5"
    allowed.mkdir(parents=True)
    venv_file = _touch(dispatch_workspace / ".venv" / "lib" / "site-packages" / "x.py")
    pyc_file = _touch(dispatch_workspace / "src" / "__pycache__" / "m.cpython-312.pyc")
    git_file = _touch(dispatch_workspace / ".git" / "HEAD", "ref: refs/heads/main\n")

    snap = snapshot_workspace_tree(dispatch_workspace, allowed_subtree=allowed)
    assert venv_file.resolve() not in snap
    assert pyc_file.resolve() not in snap
    assert git_file.resolve() not in snap


def test_snapshot_skips_workspace_lock(dispatch_workspace: Path) -> None:
    """``.amanuensis-lock`` is touched by infra and skipped from the snapshot."""
    allowed = dispatch_workspace / "dispatch" / "outputs" / "test-6"
    allowed.mkdir(parents=True)
    lock = _touch(dispatch_workspace / ".amanuensis-lock", "")
    snap = snapshot_workspace_tree(dispatch_workspace, allowed_subtree=allowed)
    assert lock.resolve() not in snap


def test_violation_list_is_sorted(dispatch_workspace: Path) -> None:
    """Violations come back sorted (deterministic for tests)."""
    allowed = dispatch_workspace / "dispatch" / "outputs" / "test-7"
    allowed.mkdir(parents=True)

    before = snapshot_workspace_tree(dispatch_workspace, allowed_subtree=allowed)

    # Write three files in non-lex order to make sure the sort matters.
    z = _touch(dispatch_workspace / "z.md")
    a = _touch(dispatch_workspace / "a.md")
    m = _touch(dispatch_workspace / "m.md")

    violations = assert_no_unauthorized_mutation(
        before, dispatch_workspace, allowed_subtree=allowed
    )
    assert violations == sorted([a.resolve(), m.resolve(), z.resolve()])


# --- T6.7: map-role output dirs as allowed_subtree values -----------------
#
# ``map-resolve`` and ``map-audit`` dir names contain a hyphen in the role
# component itself (e.g. ``map-resolve-aabbcc...``). Verify that the
# write-isolation machinery treats them like any other output dir — writes
# inside are clean and writes outside are flagged.


@pytest.mark.parametrize(
    "role_dir",
    [
        "map-resolve-" + "a" * 64,
        "map-audit-" + "b" * 64,
        # Phase 1 roles for comparison: single-component names still work.
        "extractor-" + "c" * 64,
        "auditor-" + "d" * 64,
        # Phase 2b M4: connect role uses a single-component name; INV-11
        # write-isolation contract applies identically.
        "connect-" + "e" * 64,
    ],
)
def test_map_role_output_dir_no_violation_when_writing_inside(
    dispatch_workspace: Path, role_dir: str
) -> None:
    """Writing inside a map-role output dir reports no isolation violation."""
    allowed = dispatch_workspace / "dispatch" / "outputs" / role_dir
    allowed.mkdir(parents=True)

    before = snapshot_workspace_tree(dispatch_workspace, allowed_subtree=allowed)

    _touch(allowed / "output.yaml", "proposed_entities: []\n")

    violations = assert_no_unauthorized_mutation(
        before, dispatch_workspace, allowed_subtree=allowed
    )
    assert violations == []


@pytest.mark.parametrize(
    "role_dir",
    [
        "map-resolve-" + "e" * 64,
        "map-audit-" + "f" * 64,
        # Phase 2b M4: connect role's outside-write contract.
        "connect-" + "0" * 64,
    ],
)
def test_map_role_output_dir_violation_when_writing_outside(
    dispatch_workspace: Path, role_dir: str
) -> None:
    """Writing outside a map-role output dir is flagged as an isolation violation."""
    allowed = dispatch_workspace / "dispatch" / "outputs" / role_dir
    allowed.mkdir(parents=True)

    before = snapshot_workspace_tree(dispatch_workspace, allowed_subtree=allowed)

    forbidden = _touch(dispatch_workspace / "mappings" / "entities" / "e-fake.md", "rogue")

    violations = assert_no_unauthorized_mutation(
        before, dispatch_workspace, allowed_subtree=allowed
    )
    assert forbidden.resolve() in violations
