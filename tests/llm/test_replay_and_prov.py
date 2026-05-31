"""Replay-log appender + LLM-PROV writer tests (M5.2).

Replay-log appender contracts:

1. ``append_replay_entry`` writes one entry at the canonical path
   (``distillations/<src>/replay-log/<yyyy-mm-dd>/<seq:012>.yaml``).
2. The per-distillation seq counter advances; two successive appends
   land at seq 0 then seq 1.
3. The appender acquires the workspace flock — a concurrent appender
   from another process blocks while we hold the lock.

LLM-PROV writer contracts:

4. ``write_llm_provenance`` routes through ``Substrate.add_provenance``,
   producing a PROV file at the canonical path with
   ``was_attributed_to.kind == "llm"`` and ``.identifier == model_id``.
5. The PROV record's id is content-addressable: re-computing
   ``compute_id`` on the parsed record matches the on-disk id.
"""

from __future__ import annotations

import multiprocessing
import time
from datetime import UTC, datetime, timedelta
from multiprocessing.process import BaseProcess
from pathlib import Path

import pytest

from amanuensis.fs import Substrate, acquire_workspace_lock
from amanuensis.fs._serialize import parse_provenance_yaml
from amanuensis.llm import append_replay_entry, write_llm_provenance
from amanuensis.schemas import AgentAttribution, ReplayLogEntry, compute_id

SOURCE_ID = "llm-test-src"


def _make_actor() -> AgentAttribution:
    return AgentAttribution(kind="llm", identifier="claude-opus-4-7", role="extractor")


def _build_entry(*, activity: str = "extractor-propose") -> ReplayLogEntry:
    """Build a ReplayLogEntry caller-side (the M5.2 contract)."""
    return ReplayLogEntry(
        seq=0,  # Overwritten by the appender; placeholder here.
        timestamp=datetime.now(UTC),
        actor=_make_actor(),
        activity=activity,
        inputs_hash="a" * 64,
        outputs_hash="b" * 64,
        cache_hit=False,
        substrate_changes=["distillations/llm-test-src/atoms/a-deadbeef00000001.md"],
        duration_seconds=0.5,
    )


# --- Replay-log appender tests ---------------------------------------


def test_replay_log_appender_writes_entry(llm_workspace: Path) -> None:
    """One append → one file at the canonical layout."""
    entry = _build_entry()
    path = append_replay_entry(llm_workspace, entry, source_id=SOURCE_ID)

    assert path.is_file()
    # Canonical layout: distillations/<src>/replay-log/<yyyy-mm-dd>/<seq:012>.yaml
    parts = path.relative_to(llm_workspace).parts
    assert parts[0] == "distillations"
    assert parts[1] == SOURCE_ID
    assert parts[2] == "replay-log"
    assert parts[3].count("-") == 2  # YYYY-MM-DD shape
    assert parts[4] == "000000000000.yaml"  # seq=0, width-12


def test_replay_log_appender_increments_seq(llm_workspace: Path) -> None:
    """Two appends → seqs 0, 1; counter advances."""
    p0 = append_replay_entry(llm_workspace, _build_entry(activity="first"), source_id=SOURCE_ID)
    p1 = append_replay_entry(llm_workspace, _build_entry(activity="second"), source_id=SOURCE_ID)
    assert p0.name == "000000000000.yaml"
    assert p1.name == "000000000001.yaml"
    assert p0 != p1


# --- Module-level child entry point (multiprocessing-spawn pickling) -


def _appender_child(workspace_str: str) -> None:
    """Try to append an entry from a child process; relies on flock to block."""
    from amanuensis.llm import append_replay_entry as _append
    from amanuensis.schemas import AgentAttribution, ReplayLogEntry

    entry = ReplayLogEntry(
        seq=0,
        timestamp=datetime.now(UTC),
        actor=AgentAttribution(kind="llm", identifier="m", role="extractor"),
        activity="child-append",
        inputs_hash="c" * 64,
        outputs_hash="d" * 64,
        cache_hit=False,
        substrate_changes=[],
        duration_seconds=0.001,
    )
    _append(Path(workspace_str), entry, source_id=SOURCE_ID, lock_timeout=30.0)


def test_replay_log_appender_acquires_flock(llm_workspace: Path) -> None:
    """A child appender blocks while the parent holds the workspace flock.

    Acquires the workspace flock in the parent, spawns a child that
    tries to append, gives the child a brief window to block, then
    releases the lock — the child should complete cleanly after release.
    """
    ctx = multiprocessing.get_context("spawn")

    with acquire_workspace_lock(llm_workspace, timeout=5.0):
        proc: BaseProcess = ctx.Process(
            target=_appender_child,
            args=(str(llm_workspace),),
        )
        proc.start()
        # Give the child a chance to start and block on the flock.
        # 0.5s is well above process-startup latency; if the child were
        # NOT blocked it would have written and exited by then.
        time.sleep(0.5)
        assert proc.is_alive(), "child appender should be blocked on the workspace flock"

    # Lock released; the child should complete cleanly.
    proc.join(timeout=30)
    assert not proc.is_alive(), "child appender did not exit after lock release"
    assert proc.exitcode == 0, f"child exited with {proc.exitcode}"

    # The child's entry should be on disk.
    from amanuensis.fs import ReplayLog

    log = ReplayLog.for_source(llm_workspace, SOURCE_ID)
    entries = list(log.list_entries())
    assert len(entries) == 1
    assert entries[0].activity == "child-append"


# --- LLM-PROV writer tests -------------------------------------------


def test_write_llm_provenance_routes_through_substrate(llm_workspace: Path) -> None:
    """PROV file written; kind='llm' and identifier=model_id."""
    substrate = Substrate(llm_workspace)
    now = datetime.now(UTC)
    prov = write_llm_provenance(
        substrate=substrate,
        source_id=SOURCE_ID,
        entity_type="atom",
        entity_id="a-deadbeef00000001",
        activity="extractor-propose",
        started_at=now,
        ended_at=now + timedelta(seconds=1),
        used_entity_ids=["p-0001", "p-0002"],
        model_id="claude-opus-4-7",
        role="extractor",
        inputs_hash="a" * 64,
    )

    # File exists at canonical path.
    expected = substrate.provenance_path(SOURCE_ID, prov.id)
    assert expected.is_file()

    # Attribution shape.
    parsed = parse_provenance_yaml(expected.read_text(encoding="utf-8"))
    assert parsed.was_attributed_to.kind == "llm"
    assert parsed.was_attributed_to.identifier == "claude-opus-4-7"
    assert parsed.was_attributed_to.role == "extractor"
    assert parsed.entity_id == "a-deadbeef00000001"
    assert parsed.activity == "extractor-propose"


def test_prov_record_id_is_content_addressable(llm_workspace: Path) -> None:
    """The persisted PROV record's id matches compute_id of the parsed record."""
    substrate = Substrate(llm_workspace)
    now = datetime.now(UTC)
    prov = write_llm_provenance(
        substrate=substrate,
        source_id=SOURCE_ID,
        entity_type="relation",
        entity_id="r-feedfacef00ddead",
        activity="extractor-relate",
        started_at=now,
        ended_at=now,
        used_entity_ids=[],
        model_id="claude-opus-4-7",
        role="extractor",
        inputs_hash="z" * 64,
    )
    on_disk = parse_provenance_yaml(
        substrate.provenance_path(SOURCE_ID, prov.id).read_text(encoding="utf-8")
    )
    assert compute_id(on_disk) == on_disk.id


def test_write_llm_provenance_rejects_invalid_entity_type(llm_workspace: Path) -> None:
    """An ``entity_type`` outside the LLM-permitted set raises ValueError fast."""
    substrate = Substrate(llm_workspace)
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="entity_type"):
        write_llm_provenance(
            substrate=substrate,
            source_id=SOURCE_ID,
            entity_type="iteration-issued",  # human, not LLM
            entity_id="i-deadbeef00000001",
            activity="bogus",
            started_at=now,
            ended_at=now,
            used_entity_ids=[],
            model_id="m",
            role="extractor",
            inputs_hash="a" * 64,
        )


def test_write_llm_provenance_rejects_human_supervisor_role(llm_workspace: Path) -> None:
    """``role="human_supervisor"`` is not a valid LLM attribution role."""
    substrate = Substrate(llm_workspace)
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="role"):
        write_llm_provenance(
            substrate=substrate,
            source_id=SOURCE_ID,
            entity_type="atom",
            entity_id="a-deadbeef00000001",
            activity="bogus",
            started_at=now,
            ended_at=now,
            used_entity_ids=[],
            model_id="m",
            role="human_supervisor",
            inputs_hash="a" * 64,
        )
