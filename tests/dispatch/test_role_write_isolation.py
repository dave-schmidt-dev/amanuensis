"""Write-isolation enforcement tests (M6.3, CV-5).

Five contracts:

1. Writing only within the allowed subtree ⇒ no violation reported.
2. Writing outside the allowed subtree ⇒ violation list contains that
   path.
3. Modifying a pre-existing file's mtime outside the allowed subtree ⇒
   violation.
4. Deletions are NOT reported (per module docstring).
5. The snapshot ignores skip directories (.venv / __pycache__ / .git).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

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
