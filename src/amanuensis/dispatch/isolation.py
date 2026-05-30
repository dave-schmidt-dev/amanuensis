"""Write-isolation enforcement (M6.3, CV-5 fix).

A dispatched role runs inside an agent harness subprocess that has full
access to the workspace filesystem. CV-5 (Phase 1 plan) requires that
the role NOT mutate any path outside its assigned output directory
``dispatch/outputs/<role>-<inputs_hash>/``. The dispatch driver enforces
that policy structurally:

1. Before subprocess invocation, snapshot the workspace tree as
   ``{path: mtime}`` for every file EXCEPT those under the allowed
   subtree (and the few "expected to change" trees like ``.venv/`` —
   though in practice the driver runs in a clean workspace).
2. After subprocess exit, re-walk the tree and compare. Any file that
   was added or had its mtime change is a violation; the driver routes
   the queue entry to ``dispatch/failures/`` with
   ``reason="write-isolation-violation"`` and a detail enumerating the
   offending paths.

Why mtime + not content-hash:
mtime is cheap (one ``stat`` per file) and sufficient — a write that
doesn't change mtime is a write that didn't happen. Hashing every file
before and after would scale poorly for sources with thousands of
paragraph files. The trade-off is that a write-then-restore-mtime
attack can evade the check; this is acceptable for CV-5 because the
threat model is "buggy role agent", not "actively malicious role
agent". An adversarial threat model would call for filesystem-level
sandboxing (chroot / namespaces), which is out of scope for Phase 1.

What's excluded from the snapshot:
- The allowed subtree itself (the role's output directory).
- ``.venv/``, ``__pycache__/``, ``.git/`` — pre-existing churn that
  doesn't reflect role behaviour. Skipping these by NAME (not by path
  prefix) is conservative: a nested ``__pycache__`` deep in the
  substrate is also excluded, which matches the spirit of "ignore
  Python build artifacts" but would mask a role that maliciously
  named its output ``__pycache__``. Again, buggy-not-malicious threat
  model.
- ``.amanuensis-lock`` (the workspace flock sentinel) — touched by the
  lock acquisition itself when the file is first created.
"""

from __future__ import annotations

from pathlib import Path

_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".venv",
        "__pycache__",
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
    }
)
"""Directory basenames to skip during the workspace walk.

These names commonly hold build / cache / VCS state whose mtimes are
not under role control. Matched by basename, so a nested occurrence is
also skipped — see the module docstring for the rationale.
"""

_SKIP_FILE_NAMES: frozenset[str] = frozenset(
    {
        ".amanuensis-lock",
    }
)
"""File basenames to skip during the walk (touched by infrastructure)."""


def snapshot_workspace_tree(
    workspace_root: Path,
    *,
    allowed_subtree: Path,
) -> dict[Path, float]:
    """Walk ``workspace_root`` and record ``{path: mtime}`` per file.

    Skips files inside ``allowed_subtree`` (the role's assigned output
    directory) and inside any directory whose basename is in
    :data:`_SKIP_DIR_NAMES`. Returns a dict keyed by the absolute
    resolved path so the post-walk comparison can detect newly-created
    files (keys that didn't exist in the snapshot) AND mtime changes
    on pre-existing files (keys whose value changed).

    Args:
        workspace_root: tree root to walk.
        allowed_subtree: subtree the role IS permitted to mutate. May
            or may not exist on disk at snapshot time — the role
            creates its output directory.

    Returns:
        ``{absolute_path: mtime_float}`` for every file in scope.
    """
    root = workspace_root.resolve()
    allowed = allowed_subtree.resolve()
    out: dict[Path, float] = {}

    for path in _walk_files(root, allowed):
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:  # pragma: no cover - racy unlink; defensive
            continue
        out[path] = mtime
    return out


def assert_no_unauthorized_mutation(
    before: dict[Path, float],
    workspace_root: Path,
    *,
    allowed_subtree: Path,
) -> list[Path]:
    """Re-walk and return paths that were added / modified out-of-bounds.

    Compares ``before`` (from :func:`snapshot_workspace_tree`) against
    the current state of the tree. A path is a violation if:

    - It exists now but did NOT exist in the snapshot (creation).
    - It exists now AND in the snapshot but the mtime changed
      (modification).

    Deletions are NOT reported as violations — CV-5 is about *new
    content* the role tried to land in the substrate. A role that
    deletes a substrate file should still trigger failure handling, but
    that's a higher-layer concern (the next dispatch will fail when the
    file is missing, and the deletion gets caught via the missing-file
    error). Keeping this function focused on "writes outside the allowed
    subtree" matches the M6.3 contract verbatim.

    Returns:
        Sorted list of violating absolute paths (empty list = clean).
    """
    root = workspace_root.resolve()
    allowed = allowed_subtree.resolve()
    violations: list[Path] = []

    for path in _walk_files(root, allowed):
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:  # pragma: no cover - racy unlink; defensive
            continue
        prior = before.get(path)
        if prior is None:
            violations.append(path)
            continue
        if mtime != prior:
            violations.append(path)

    violations.sort()
    return violations


def _walk_files(root: Path, allowed_subtree: Path):
    """Yield in-scope file paths beneath ``root`` (excluding skips + allowed)."""
    # ``Path.walk`` (3.12+) returns (dirpath, dirnames, filenames) and
    # lets us prune ``dirnames`` in place, mirroring ``os.walk`` while
    # staying Path-native.
    for dirpath, dirnames, filenames in root.walk():
        # Skip the allowed subtree entirely (don't descend, don't yield).
        if _is_within(dirpath, allowed_subtree):
            dirnames.clear()
            continue
        # Prune skip-named subdirs IN PLACE so the walk doesn't descend.
        # Also prune any subdir that IS the allowed subtree (when the
        # walk hasn't reached it yet) so we don't yield the leaf.
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _SKIP_DIR_NAMES and not _is_within(dirpath / d, allowed_subtree)
        ]
        # Sort directory names for deterministic walk order across runs.
        dirnames.sort()

        for fname in sorted(filenames):
            if fname in _SKIP_FILE_NAMES:
                continue
            yield (dirpath / fname).resolve()


def _is_within(path: Path, parent: Path) -> bool:
    """True iff ``path`` equals ``parent`` or is nested under it.

    Operates on already-resolved paths (the walk yields absolute paths;
    the allowed subtree is resolved at the API boundary).
    """
    path_r = path.resolve()
    parent_r = parent.resolve()
    if path_r == parent_r:
        return True
    try:
        path_r.relative_to(parent_r)
    except ValueError:
        return False
    return True
