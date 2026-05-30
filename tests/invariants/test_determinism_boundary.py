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
This file covers BOTH halves of INV-4:

- **Read-only half** (M4.4): every read-only CLI command is a pure
  function over substrate state — runs do not mutate any file and
  repeated invocations produce byte-identical stdout. See
  ``_READ_ONLY_COMMANDS`` and ``test_inv4_read_only_command_does_not_mutate_substrate``.

- **Mutating half** (M5.3, landed): every LLM-call boundary writes a
  replay-log entry AND a PROV-O record AND a cache entry; cache-hit
  replays produce byte-identical outputs. See the "Mutating side
  (M5.3)" section at the bottom of this file. The mutating-side gate
  exercises the M5.1/M5.2 LLM-boundary wrappers directly rather than
  driving the CLI: M5.3 ships before M6 (dispatch driver), so there's
  no `amanuensis dispatch` command yet to invoke. The contracts gated
  are structural — that the three artefacts exist after one completion
  cycle, and that a cache-hit replay is byte-identical.

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
from typing import Any

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


# =====================================================================
# Mutating side (M5.3): LLM-call boundary writes the three artefacts
# =====================================================================
#
# INV-4 says non-deterministic actions are permitted only at named
# events. Each event must carry: input hash, output hash, role
# attribution, model identifier, timestamp, AND a deterministic
# validation gate. The structural shape of "one event = three on-disk
# artefacts (cache entry + PROV-O record + replay-log entry)" is what
# these tests certify; the validation-gate aspect rides on the schemas
# (every artefact is a strict, ``extra="forbid"`` Pydantic model that
# refuses malformed payloads at parse time).
#
# These tests drive the M5.1/M5.2 wrappers directly rather than the CLI:
# M5.3 lands before M6 (dispatch driver), so there is no
# ``amanuensis dispatch`` command yet to exercise. The contracts we gate
# are structural — the three artefacts exist after one completion cycle,
# and a cache-hit replay is byte-identical.

from datetime import UTC, datetime  # noqa: E402  — kept with M5.3 block

import yaml  # noqa: E402  — kept with M5.3 block

from amanuensis.fs import ReplayLog  # noqa: E402  — kept with M5.3 block
from amanuensis.llm import (  # noqa: E402  — kept with M5.3 block
    append_replay_entry,
    cached_call,
    write_llm_provenance,
)
from amanuensis.schemas import (  # noqa: E402  — kept with M5.3 block
    AgentAttribution,
    ReplayLogEntry,
)

# Re-use the simple workspace pattern from tests/cli/conftest.py via the
# ``cli_workspace`` fixture (already re-exported by
# tests/invariants/conftest.py).


_M53_SOURCE_ID = "cli-fixture-src"  # mirrors tests/cli/conftest.py SOURCE_ID


def _plant_cache_entry_for(workspace: Path, inputs_hash: str, model_id: str) -> bytes:
    """Hand-craft a cache entry; returns its on-disk bytes for round-trip checks.

    M6 will be the real writer; here we plant deterministic content so
    the cache-hit branch under test produces a predictable artefact.
    """
    cache_dir = workspace / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        {
            "model_id": model_id,
            "output_payload": {"atoms": ["a-deadbeef00000001"]},
            "completed_at": "2026-05-30T00:00:00.000000Z",
        },
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )
    (cache_dir / f"{inputs_hash}.yaml").write_text(text, encoding="utf-8")
    return text.encode("utf-8")


@pytest.mark.invariants
def test_inv4_llm_call_boundary_writes_all_three_artefacts(
    cli_workspace: Path,
) -> None:
    """INV-4 mutating side: one completed LLM call ⇒ three on-disk artefacts.

    Drives the M5.1/M5.2 wrappers directly:

    1. :func:`cached_call` with cache MISS — writes a queue entry.
    2. Simulate the dispatch-driver completion by hand-writing a cache
       entry, calling :func:`cached_call` again to materialise the
       dispatch-output, calling :func:`write_llm_provenance` for PROV,
       and :func:`append_replay_entry` for the replay log.
    3. Assert all three canonical artefacts exist with the right shape.
    """
    substrate = Substrate(cli_workspace)
    model_id = "claude-opus-4-7"
    role = "extractor"
    inputs: dict[str, Any] = {"paragraph_id": "p-0001"}

    # --- 1. Cache miss → queue entry exists ---------------------------
    miss = cached_call(
        workspace_root=cli_workspace,
        role=role,
        prompt="Extract atoms from the paragraph.",
        inputs=inputs,
        model_id=model_id,
    )
    assert miss.cache_hit is False
    assert miss.queue_entry_path is not None
    assert miss.queue_entry_path.is_file()
    queue_path = miss.queue_entry_path

    # --- 2. Plant cache, materialise dispatch output via cached_call --
    _plant_cache_entry_for(cli_workspace, miss.inputs_hash, model_id)
    hit = cached_call(
        workspace_root=cli_workspace,
        role=role,
        prompt="Extract atoms from the paragraph.",
        inputs=inputs,
        model_id=model_id,
    )
    assert hit.cache_hit is True
    assert hit.output_path is not None
    output_path = hit.output_path

    # --- 3. Write the PROV-O record (M5.2) ----------------------------
    now = datetime.now(UTC)
    prov = write_llm_provenance(
        substrate=substrate,
        source_id=_M53_SOURCE_ID,
        entity_type="atom",
        entity_id="a-deadbeef00000001",
        activity="extractor-propose",
        started_at=now,
        ended_at=now,
        used_entity_ids=["p-0001"],
        model_id=model_id,
        role=role,
        inputs_hash=hit.inputs_hash,
    )
    prov_path = substrate.provenance_path(_M53_SOURCE_ID, prov.id)
    assert prov_path.is_file()
    assert prov.was_attributed_to.kind == "llm"
    assert prov.was_attributed_to.identifier == model_id

    # --- 4. Append the replay-log entry (M5.2) ------------------------
    entry = ReplayLogEntry(
        seq=0,  # overwritten by the appender
        timestamp=now,
        actor=AgentAttribution(kind="llm", identifier=model_id, role="extractor"),
        activity="extractor-propose",
        inputs_hash=hit.inputs_hash,
        outputs_hash="o" * 64,  # placeholder; M6 will compute the real value
        cache_hit=True,
        substrate_changes=[str(prov_path.relative_to(cli_workspace))],
        duration_seconds=0.001,
    )
    replay_path = append_replay_entry(cli_workspace, entry, source_id=_M53_SOURCE_ID)
    assert replay_path.is_file()

    # The replay-log entry holds the cross-reference fields INV-4 wants.
    log = ReplayLog(cli_workspace, _M53_SOURCE_ID)
    persisted = log.get_entry(seq=0)
    assert persisted.inputs_hash == hit.inputs_hash
    assert persisted.actor.kind == "llm"
    assert persisted.actor.identifier == model_id

    # --- 5. The three canonical artefacts coexist ---------------------
    # (queue entry, dispatch output, PROV, replay) — the queue entry is
    # still on disk from the miss in step 1 (M6 unlinks queue entries
    # after dispatch; M5 leaves them as a coordination breadcrumb).
    assert queue_path.is_file()
    assert output_path.is_file()
    assert prov_path.is_file()
    assert replay_path.is_file()


@pytest.mark.invariants
def test_inv4_cache_hit_yields_byte_identical_output(cli_workspace: Path) -> None:
    """A cache hit produces the cache file's bytes verbatim in dispatch outputs.

    This is the "same input ⇒ same output" half of INV-4 applied to the
    cache replay path. The cache IS authoritative; the dispatch-output
    file is a verbatim materialisation of the cached payload.
    """
    role = "extractor"
    model_id = "claude-opus-4-7"
    inputs: dict[str, Any] = {"paragraph_id": "p-0042"}

    miss = cached_call(
        workspace_root=cli_workspace,
        role=role,
        prompt="P",
        inputs=inputs,
        model_id=model_id,
    )
    expected = _plant_cache_entry_for(cli_workspace, miss.inputs_hash, model_id)

    hit = cached_call(
        workspace_root=cli_workspace,
        role=role,
        prompt="P",
        inputs=inputs,
        model_id=model_id,
    )
    assert hit.cache_hit is True
    assert hit.output_path is not None
    assert hit.output_path.read_bytes() == expected, (
        "INV-4 violation: cache-hit dispatch output is not byte-identical to the cache entry"
    )

    # And a second hit produces the same bytes (idempotent replay).
    second = cached_call(
        workspace_root=cli_workspace,
        role=role,
        prompt="P",
        inputs=inputs,
        model_id=model_id,
    )
    assert second.output_path is not None
    assert second.output_path.read_bytes() == expected


@pytest.mark.invariants
def test_inv4_inputs_hash_is_deterministic_across_calls(cli_workspace: Path) -> None:
    """The cache key is a deterministic function of (role, prompt, inputs, model_id).

    Two successive calls with the same inputs must yield the same
    ``inputs_hash`` — without this, the cache would never hit and the
    determinism boundary would be unobservable.

    Reframes ``test_inputs_hash_stable_across_dict_key_order`` from
    ``tests/llm/test_cache.py`` as an INV-4 assertion (the cache key
    IS the INV-4 input content hash).
    """
    inputs_a: dict[str, Any] = {"a": 1, "b": [2, 3], "c": {"d": True, "e": None}}
    inputs_b: dict[str, Any] = {"c": {"e": None, "d": True}, "b": [2, 3], "a": 1}

    first = cached_call(
        workspace_root=cli_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs_a,
        model_id="m",
    )
    second = cached_call(
        workspace_root=cli_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs_b,
        model_id="m",
    )
    assert first.inputs_hash == second.inputs_hash, (
        "INV-4 violation: inputs_hash is not a deterministic function of "
        "the (role, prompt, inputs, model_id) tuple"
    )
