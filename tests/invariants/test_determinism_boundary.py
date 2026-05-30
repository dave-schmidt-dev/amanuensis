"""Gate test for INV-4 (Determinism boundary) — read-only half.

Quoting INVARIANTS.md INV-4:

    Non-deterministic actions (LLM calls, human judgments) are permitted
    only at named events. Each event has: input content hash, output
    content hash, role attribution, model identifier (for LLM events),
    timestamp, and a deterministic validation gate that rejects malformed
    output before it enters the substrate. All other operations are pure
    functions over substrate state.

What this gate certifies
------------------------
Two complementary properties for every CLI command classified as
**read-only**:

1. **Substrate purity.** Running the command does not add, remove, or
   modify any file under the workspace root. Snapshot the full file tree
   (path + sha256(content)) before and after; assert equality.
2. **Output determinism.** Running the command TWICE in a row on the
   same substrate state produces byte-identical stdout. This is the
   "pure function over substrate state" half of INV-4: the same input
   must yield the same output, every time.

Read-only commands gated by this test
-------------------------------------
- ``status`` (with and without ``--json``)
- ``atom list``
- ``atom show``
- ``atom validate``
- ``clarification list``
- ``iteration list``
- ``vocabulary list``
- ``vocabulary show``
- ``vocabulary snapshot``
- ``install-skills`` (M4.3 stub: detects harnesses but writes nothing,
  so it is read-only for INV-4 accounting until M7.6 finalises it; that
  finalisation re-classifies the command as mutating and moves its
  gating to the M5.3 mutating-side test.)

Scope boundary
--------------
This test covers the **read-only half** of INV-4 only. The mutating
half — verifying that mutating commands route non-determinism through
the M5.x cache + replay-log wrapper, and that re-running a mutating
command on an already-mutated substrate behaves with the documented
idempotency contract — is gated by ``tests/invariants/test_determinism_boundary_mutating.py``
(introduced by M5.3 once the LLM-boundary mechanics ship).

TODO(M5.3): add the mutating-side gate test covering:
``init``, ``ingest``, ``clarification resolve``, ``iteration add``.
Each of those needs its idempotency contract certified separately
because the contracts differ: ``init`` is naturally idempotent,
``ingest`` refuses re-ingest with ``SourceMirrorExists``,
``clarification resolve`` is one-shot (a second call on a resolved
clarification fails with a clear error), and ``iteration add`` always
writes a NEW directive (the contract is "append-only", not "idempotent").

Why fixtures, not real ingest
-----------------------------
The hand-built ``planted_atom`` / ``planted_clarification`` fixtures in
``tests/cli/conftest.py`` populate a non-trivial substrate state — one
atom, one provenance record, one vocabulary snapshot, one open
clarification — without invoking the docling / pdfplumber ingesters.
That keeps this test fast (no PDF parsing) and deterministic (no
docling version drift across CI / dev machines).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate
from amanuensis.schemas import Atom, Clarification, ProvenanceRecord
from tests.cli.conftest import SOURCE_ID

# The substrate-setup fixtures (``cli_workspace``, ``cli_substrate``,
# ``planted_atom``, ``planted_clarification``) are re-exported by
# ``tests/invariants/conftest.py`` so they are visible here without
# duplication. pytest's directory-scoped conftest discovery treats
# fixtures named at function-parameter level as already-resolved.

runner = CliRunner()

ArgvFactory = Callable[[Path, str], list[str]]
"""``(workspace_path, atom_id) -> argv`` — the atom_id is plumbed in for the
one command (``atom show``) that needs a specific id. Other factories
ignore it."""


def _snapshot_workspace(workspace_root: Path) -> dict[str, str]:
    """Walk every file under ``workspace_root``; return ``{relpath: sha256}``.

    Used to detect any substrate mutation a read-only command might
    accidentally introduce (a stray temp file, a touched mtime that
    rewrote content, etc.). We hash content (not mtime) because INV-4
    cares about substrate state, not filesystem metadata.
    """
    snapshot: dict[str, str] = {}
    for path in sorted(workspace_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(workspace_root).as_posix()
        snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _diff_snapshots(before: dict[str, str], after: dict[str, str]) -> str:
    """Pretty-print snapshot differences for clearer failure messages."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(p for p in before.keys() & after.keys() if before[p] != after[p])
    parts: list[str] = []
    if added:
        parts.append("added:\n  " + "\n  ".join(added))
    if removed:
        parts.append("removed:\n  " + "\n  ".join(removed))
    if modified:
        parts.append("modified:\n  " + "\n  ".join(modified))
    return "\n".join(parts) if parts else "(no diff)"


# Each entry: (label, argv_factory). ``label`` identifies the command in
# failure messages so a regression points at the offender immediately.
# ``argv_factory(workspace, atom_id)`` builds the CLI argv. The factory
# accepts ``atom_id`` so ``atom show`` (the one command that needs a
# specific id) can plug in the planted atom's id at call time.
_READ_ONLY_COMMANDS: list[tuple[str, ArgvFactory]] = [
    (
        "status",
        lambda ws, _aid: ["status", "--workspace", str(ws)],
    ),
    (
        "status --json",
        lambda ws, _aid: ["status", "--json", "--workspace", str(ws)],
    ),
    (
        "atom list",
        lambda ws, _aid: ["atom", "list", SOURCE_ID, "--workspace", str(ws)],
    ),
    (
        "atom show",
        lambda ws, aid: ["atom", "show", SOURCE_ID, aid, "--workspace", str(ws)],
    ),
    (
        "atom validate",
        lambda ws, _aid: ["atom", "validate", SOURCE_ID, "--workspace", str(ws)],
    ),
    (
        "clarification list",
        lambda ws, _aid: ["clarification", "list", "--workspace", str(ws)],
    ),
    (
        "iteration list",
        lambda ws, _aid: ["iteration", "list", "--workspace", str(ws)],
    ),
    (
        "vocabulary list",
        lambda ws, _aid: ["vocabulary", "list", "--workspace", str(ws)],
    ),
    (
        "vocabulary show",
        lambda ws, _aid: [
            "vocabulary",
            "show",
            "asserts_obligation",
            "--workspace",
            str(ws),
        ],
    ),
    (
        "vocabulary snapshot",
        lambda ws, _aid: ["vocabulary", "snapshot", SOURCE_ID, "--workspace", str(ws)],
    ),
    (
        "install-skills",
        lambda ws, _aid: ["install-skills", "--workspace", str(ws)],
    ),
]


@pytest.mark.invariants
@pytest.mark.parametrize(
    ("label", "argv_factory"),
    _READ_ONLY_COMMANDS,
    ids=[entry[0] for entry in _READ_ONLY_COMMANDS],
)
def test_inv4_read_only_command_does_not_mutate_substrate(
    cli_workspace: Path,
    cli_substrate: Substrate,
    planted_atom: tuple[Atom, ProvenanceRecord],
    planted_clarification: Clarification,
    label: str,
    argv_factory: ArgvFactory,
) -> None:
    """INV-4 read-only side: command leaves substrate byte-identical
    AND its stdout is deterministic across repeated invocations.

    The ``cli_substrate`` / ``planted_atom`` / ``planted_clarification``
    fixtures set up a non-trivial substrate state (one atom + matching
    provenance + vocabulary snapshot + one open clarification under
    ``SOURCE_ID``). We snapshot the file tree, run the command, re-
    snapshot, and assert the trees are identical. Then we run the
    command a second time and assert stdout matches the first run byte
    for byte — the "pure function over substrate state" half of INV-4.
    """
    # The fixtures are referenced so pytest builds the substrate state
    # before the command runs. They're not otherwise used in the body —
    # we walk the filesystem directly.
    _ = cli_substrate
    _ = planted_clarification
    atom, _prov = planted_atom

    argv = argv_factory(cli_workspace, atom.id)

    # --- 1. Snapshot before --------------------------------------------
    before = _snapshot_workspace(cli_workspace)

    # --- 2. First invocation -------------------------------------------
    first = runner.invoke(app, argv)
    assert first.exit_code == 0, (
        f"INV-4 read-only command {label!r} failed:\n"
        f"  exit_code={first.exit_code}\n"
        f"  argv={argv}\n"
        f"  output={first.output}"
    )

    # --- 3. Snapshot after first run -----------------------------------
    after_first = _snapshot_workspace(cli_workspace)
    assert before == after_first, (
        f"INV-4 violation: read-only command {label!r} mutated substrate state.\n"
        f"  argv={argv}\n"
        f"  diff:\n{_diff_snapshots(before, after_first)}"
    )

    # --- 4. Second invocation: stdout must be byte-identical -----------
    second = runner.invoke(app, argv)
    assert second.exit_code == 0, (
        f"INV-4 idempotency: second invocation of {label!r} failed:\n"
        f"  exit_code={second.exit_code}\n"
        f"  argv={argv}\n"
        f"  output={second.output}"
    )
    assert first.stdout == second.stdout, (
        f"INV-4 violation: command {label!r} is not a pure function over "
        f"substrate state — two consecutive runs produced different stdout.\n"
        f"  argv={argv}\n"
        f"  first stdout:\n{first.stdout}\n"
        f"  second stdout:\n{second.stdout}"
    )

    # --- 5. And the substrate is STILL untouched after the second run --
    after_second = _snapshot_workspace(cli_workspace)
    assert before == after_second, (
        f"INV-4 violation: second invocation of {label!r} mutated substrate.\n"
        f"  argv={argv}\n"
        f"  diff:\n{_diff_snapshots(before, after_second)}"
    )
