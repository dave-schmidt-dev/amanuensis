"""Concurrency + crash-discipline tests for ``ReplayLog`` (M1.7 — plan §5).

The replay log assigns a monotonic, gap-free ``seq`` to every entry,
serializing under the workspace flock from M1.8. These tests exercise:

1. Fresh workspace: ``read_seq()`` returns 0 (no counter file yet).
2. ``append()`` populates ``seq`` and ``timestamp`` correctly.
3. Default timestamp is tz-aware UTC.
4. Caller-supplied ``timestamp`` is honored.
5. Entry path matches ``distillations/<source-id>/replay-log/<yyyy-mm-dd>/<padded-seq>.yaml``.
6. ``list_entries()`` yields entries in seq-ascending order across multiple days.
7. ``get_entry(seq=N)`` returns the right entry; missing seq raises
   ``SubstrateNotFound``.
8. Concurrent writers: 10 spawn-context processes append simultaneously;
   final seq set is {0..9}, no duplicates, no gaps, counter advances to 10.
   Parametrized over distillation scope and mapping scope.
9. Crash-discipline (orphan-overwrite): pre-seeding an orphan entry at
   the unclaimed seq, then appending — the orphan is overwritten with
   the new entry's content; counter advances by 1; no gap, no duplicate.

Child processes use ``multiprocessing.get_context("spawn")`` per the
M1.6/M1.8 pattern (avoids forked-state surprises on macOS). The race
test uses a parent-side barrier (a ready-file plus a go-file) so all
children try to take the workspace flock at approximately the same
instant — without the barrier, processes could quietly serialize on
their own startup latency and we'd never exercise contention.
"""

from __future__ import annotations

import multiprocessing
import time
from datetime import UTC, datetime, timedelta, timezone
from multiprocessing.process import BaseProcess
from pathlib import Path

import pytest
import yaml

from amanuensis.fs import ReplayLog, SubstrateMarkerMissing, SubstrateNotFound
from amanuensis.schemas import AgentAttribution, ReplayLogEntry

SOURCE_ID = "src-fixture-001"

# Mirror of replay-log layout constants. Kept here (not imported as
# private symbols) so pyright stays clean and the tests assert against
# the published on-disk contract, not against the implementation
# module's internals. Drift between these and ``replay_log.py`` would
# be caught by ``test_append_entry_path_layout``.
_COUNTER_FILENAME = ".next-seq"
_SEQ_WIDTH = 12


# --- Helpers ---------------------------------------------------------


def _make_agent() -> AgentAttribution:
    return AgentAttribution(kind="llm", identifier="claude-opus-4-7", role="extractor")


def _append_one(
    log: ReplayLog,
    *,
    activity: str = "extract_v1",
    timestamp: datetime | None = None,
    lock_timeout: float = 10.0,
) -> ReplayLogEntry:
    """Minimal-args wrapper around ``log.append`` for the test corpus."""
    return log.append(
        actor=_make_agent(),
        activity=activity,
        inputs_hash="i" + "0" * 31,
        outputs_hash="o" + "0" * 31,
        cache_hit=False,
        substrate_changes=[],
        duration_seconds=0.001,
        timestamp=timestamp,
        lock_timeout=lock_timeout,
    )


def _make_log(tmp_workspace: Path, scope: str, source_id: str | None) -> ReplayLog:
    """Factory for a ReplayLog instance based on scope discriminator."""
    if scope == "mapping":
        return ReplayLog.for_mappings(tmp_workspace)
    return ReplayLog.for_source(tmp_workspace, source_id or SOURCE_ID)


# --- Child entry points (module-level for spawn pickling) ------------


def _race_child(
    workspace_str: str,
    source_id: str | None,
    scope: str,
    ready_path_str: str,
    go_path_str: str,
    child_index: int,
) -> None:
    """Signal readiness, wait for go, then append exactly one entry.

    The barrier (ready + go) maximises the chance that all children are
    contending for the workspace flock at approximately the same
    instant. Without it, slow process startup could silently serialize
    the appends and hide a real concurrency bug.
    """
    ready_path = Path(ready_path_str)
    go_path = Path(go_path_str)

    ws = Path(workspace_str)
    if scope == "mapping":
        log = ReplayLog.for_mappings(ws)
    else:
        log = ReplayLog.for_source(ws, source_id or SOURCE_ID)

    # Mark this child as ready (its own ready file).
    ready_path.write_text("ready", encoding="utf-8")

    # Wait for the parent to give the go signal. Bound the wait so a
    # broken test doesn't deadlock CI; 10s is plenty for parent's
    # barrier check.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if go_path.exists():
            break
        time.sleep(0.005)

    log.append(
        actor=_make_agent(),
        activity=f"race_child_{child_index}",
        inputs_hash="i" + "0" * 31,
        outputs_hash="o" + "0" * 31,
        cache_hit=False,
        substrate_changes=[f"child-{child_index}"],
        duration_seconds=0.001,
        lock_timeout=30.0,  # Large — 10 children may queue serially.
    )


# --- Construction tests ---------------------------------------------


def test_init_rejects_missing_marker(tmp_path: Path) -> None:
    """Constructing on a non-workspace directory fails fast (INV-1 defense)."""
    with pytest.raises(SubstrateMarkerMissing):
        ReplayLog.for_source(tmp_path, SOURCE_ID)


def test_init_rejects_nonexistent_directory(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(SubstrateMarkerMissing):
        ReplayLog.for_source(missing, SOURCE_ID)


def test_init_rejects_invalid_source_id(tmp_workspace: Path) -> None:
    """Path-escaping source ids are refused by the substrate id check."""
    from amanuensis.fs import SubstrateInvalidId

    with pytest.raises(SubstrateInvalidId):
        ReplayLog.for_source(tmp_workspace, "../escape")


# --- Lock-free read tests --------------------------------------------


def test_read_seq_fresh_workspace_returns_zero(tmp_workspace: Path) -> None:
    """No counter file yet ⇒ next-to-assign value is 0."""
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    assert log.read_seq() == 0


def test_list_entries_fresh_workspace_is_empty(tmp_workspace: Path) -> None:
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    assert list(log.list_entries()) == []


def test_get_entry_missing_seq_raises(tmp_workspace: Path) -> None:
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    with pytest.raises(SubstrateNotFound):
        log.get_entry(seq=0)


def test_get_entry_missing_seq_raises_after_some_appends(tmp_workspace: Path) -> None:
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    _append_one(log)
    _append_one(log)
    with pytest.raises(SubstrateNotFound):
        log.get_entry(seq=999)


# --- Append-correctness tests ----------------------------------------


def test_append_populates_seq_and_timestamp(tmp_workspace: Path) -> None:
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    before = datetime.now(UTC) - timedelta(seconds=1)
    entry = _append_one(log)
    after = datetime.now(UTC) + timedelta(seconds=1)

    assert entry.seq == 0
    assert before <= entry.timestamp <= after
    # tz-aware (the schema requires AwareDatetime; double-check the default).
    assert entry.timestamp.tzinfo is not None
    assert entry.timestamp.utcoffset() == timedelta(0)


def test_append_honors_caller_timestamp(tmp_workspace: Path) -> None:
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    custom = datetime(2025, 6, 15, 8, 30, 0, tzinfo=UTC)
    entry = _append_one(log, timestamp=custom)
    assert entry.timestamp == custom


def test_append_bumps_counter(tmp_workspace: Path) -> None:
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    assert log.read_seq() == 0
    _append_one(log)
    assert log.read_seq() == 1
    _append_one(log)
    assert log.read_seq() == 2


def test_append_entry_path_layout(tmp_workspace: Path) -> None:
    """Entry lands at ``distillations/<src>/replay-log/<yyyy-mm-dd>/<seq:012>.yaml``."""
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    ts = datetime(2026, 5, 29, 14, 30, 0, tzinfo=UTC)
    _append_one(log, timestamp=ts)
    expected = (
        tmp_workspace
        / "distillations"
        / SOURCE_ID
        / "replay-log"
        / "2026-05-29"
        / f"{0:0{_SEQ_WIDTH}d}.yaml"
    )
    assert expected.is_file()
    # Sanity: width-12.
    assert expected.name == "000000000000.yaml"


def test_append_day_directory_uses_utc(tmp_workspace: Path) -> None:
    """A non-UTC tz-aware timestamp still groups by UTC date."""
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    # 2026-05-29T01:00:00-05:00 == 2026-05-29T06:00:00Z → UTC day 2026-05-29.
    ts = datetime(2026, 5, 29, 1, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    _append_one(log, timestamp=ts)
    day_dir = tmp_workspace / "distillations" / SOURCE_ID / "replay-log" / "2026-05-29"
    assert day_dir.is_dir()


def test_get_entry_roundtrips(tmp_workspace: Path) -> None:
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    e0 = _append_one(log, activity="a0")
    e1 = _append_one(log, activity="a1")
    assert log.get_entry(seq=0).activity == "a0"
    assert log.get_entry(seq=1).activity == "a1"
    # Equality on the full model so we catch silent field drift.
    assert log.get_entry(seq=0) == e0
    assert log.get_entry(seq=1) == e1


def test_list_entries_yields_seq_ascending(tmp_workspace: Path) -> None:
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    # Append a few entries on the same UTC day.
    base = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)
    for i in range(5):
        _append_one(log, timestamp=base + timedelta(seconds=i))
    seqs = [e.seq for e in log.list_entries()]
    assert seqs == [0, 1, 2, 3, 4]


def test_list_entries_orders_across_day_dirs(tmp_workspace: Path) -> None:
    """Lexicographic day-dir traversal yields chronological order."""
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    _append_one(log, timestamp=datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC))
    _append_one(log, timestamp=datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC))
    _append_one(log, timestamp=datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC))
    seqs = [e.seq for e in log.list_entries()]
    assert seqs == [0, 1, 2]
    # Three day directories created.
    log_dir = tmp_workspace / "distillations" / SOURCE_ID / "replay-log"
    day_dirs = sorted(p.name for p in log_dir.iterdir() if p.is_dir())
    assert day_dirs == ["2026-05-28", "2026-05-29", "2026-05-30"]


def test_counter_file_lives_at_expected_path(tmp_workspace: Path) -> None:
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)
    _append_one(log)
    counter = tmp_workspace / "distillations" / SOURCE_ID / "replay-log" / _COUNTER_FILENAME
    assert counter.is_file()
    assert counter.read_text(encoding="utf-8").strip() == "1"


# --- Concurrent writer race -----------------------------------------


@pytest.mark.parametrize(
    "scope,source_id",
    [
        ("distillation", SOURCE_ID),
        ("mapping", None),
    ],
    ids=["distillation", "mapping"],
)
@pytest.mark.parametrize("n_writers", [10])
def test_concurrent_appends_no_gaps_no_duplicates(
    tmp_workspace: Path, n_writers: int, scope: str, source_id: str | None
) -> None:
    """Plan §5 invariant: N concurrent writers ⇒ exactly N entries, seqs {0..N-1}.

    Parametrized over distillation and mapping scopes. Uses spawn-context
    children (cross-platform reliability; M1.6 pattern) and a parent-side
    barrier (per-child ready files + a single go file) so all children
    contend for the workspace flock at roughly the same instant. Without
    the barrier, slow process startup could quietly serialize the appends
    and hide a real concurrency bug.
    """
    ctx = multiprocessing.get_context("spawn")
    go_path = tmp_workspace / ".go"
    ready_paths = [tmp_workspace / f".ready-{i}" for i in range(n_writers)]

    procs: list[BaseProcess] = []
    for i in range(n_writers):
        p = ctx.Process(
            target=_race_child,
            args=(
                str(tmp_workspace),
                source_id,
                scope,
                str(ready_paths[i]),
                str(go_path),
                i,
            ),
        )
        p.start()
        procs.append(p)

    try:
        # Wait for ALL children to signal readiness.
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if all(rp.exists() for rp in ready_paths):
                break
            time.sleep(0.01)
        else:
            pytest.fail("not all children signalled readiness in time")

        # Release the barrier — all children attempt the lock now.
        go_path.write_text("go", encoding="utf-8")

        for p in procs:
            p.join(timeout=30)
            assert not p.is_alive(), f"child pid={p.pid} did not exit"
            assert p.exitcode == 0, f"child exited with {p.exitcode}"
    finally:
        for p in procs:
            if p.is_alive():  # pragma: no cover — defensive
                p.terminate()
                p.join(timeout=5)

    # --- Assertions -------------------------------------------------
    log = _make_log(tmp_workspace, scope, source_id)
    entries = list(log.list_entries())

    assert len(entries) == n_writers, (
        f"expected {n_writers} entries, got {len(entries)} — possible duplicate or gap"
    )

    seqs = [e.seq for e in entries]
    seq_set = set(seqs)

    # No duplicates.
    assert len(seq_set) == n_writers, f"duplicate seqs in {seqs}"
    # No gaps; covers full range.
    assert seq_set == set(range(n_writers)), f"missing seq(s) from {sorted(seq_set)}"
    # Counter advanced to N.
    assert log.read_seq() == n_writers

    # Each child wrote a uniquely-identifiable activity; all should be present.
    activities = sorted(e.activity for e in entries)
    assert activities == sorted(f"race_child_{i}" for i in range(n_writers))


# --- Crash discipline: orphan-entry overwrite ------------------------


def test_orphan_entry_is_overwritten_by_next_writer(tmp_workspace: Path) -> None:
    """Plan §5 crash discipline: a crashed writer leaves a recoverable state.

    Simulate the failure: ``append`` writes the entry at seq N, then
    crashes BEFORE bumping the counter. The next writer reads N (counter
    didn't advance), writes a NEW entry at seq N (overwriting the orphan),
    and bumps the counter to N+1. Net: no gap, no duplicate, and the
    orphan's content is gone.
    """
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)

    # Seed: append 5 real entries so the counter reaches 5. Pin the
    # timestamp to the same UTC day the orphan + recovery use below,
    # so all 7 entries share one day-dir regardless of when this test
    # actually runs. (Without pinning, ``datetime.now(UTC)`` would put
    # the seeds in *today's* day-dir while the orphan/recovery land in
    # 2026-05-29's — ``list_entries`` walks day-dirs lexicographically,
    # so post-2026-05-29 the seqs come back out of order and the final
    # ``seqs == [0..5]`` assertion fails.)
    seed_day = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)
    for i in range(5):
        _append_one(log, activity=f"real_{i}", timestamp=seed_day + timedelta(seconds=i))
    assert log.read_seq() == 5

    # Manually fabricate an "orphan" entry at seq 5: this represents a
    # writer that wrote the entry file (step 3 of crash discipline) and
    # then died before bumping the counter (step 4). The counter remains
    # at 5; the orphan sits at distillations/.../<day>/000000000005.yaml.
    orphan_ts = datetime(2026, 5, 29, 23, 0, 0, tzinfo=UTC)
    orphan_entry = ReplayLogEntry(
        seq=5,
        timestamp=orphan_ts,
        actor=_make_agent(),
        activity="ORPHAN_FROM_CRASHED_WRITER",
        inputs_hash="i" + "0" * 31,
        outputs_hash="o" + "0" * 31,
        cache_hit=False,
        substrate_changes=["orphan"],
        duration_seconds=0.001,
    )
    orphan_path = (
        tmp_workspace
        / "distillations"
        / SOURCE_ID
        / "replay-log"
        / "2026-05-29"
        / f"{5:0{_SEQ_WIDTH}d}.yaml"
    )
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_text(
        yaml.safe_dump(
            orphan_entry.model_dump(mode="python"),
            sort_keys=True,
            default_flow_style=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    # Confirm orphan is on disk and counter is unchanged.
    assert orphan_path.is_file()
    assert log.read_seq() == 5

    # Next append: should claim seq 5 (overwriting the orphan) and bump
    # counter to 6. Use the same day so the orphan path is the same
    # canonical location and the rename is a true overwrite.
    new_ts = datetime(2026, 5, 29, 23, 30, 0, tzinfo=UTC)
    new_entry = _append_one(log, activity="recovery_writer", timestamp=new_ts)

    assert new_entry.seq == 5
    assert log.read_seq() == 6

    # The entry on disk at seq 5 must be the NEW entry, not the orphan.
    persisted = log.get_entry(seq=5)
    assert persisted.activity == "recovery_writer"
    assert persisted.activity != "ORPHAN_FROM_CRASHED_WRITER"
    assert persisted == new_entry

    # No gap, no duplicate: seqs are 0..5 contiguous.
    seqs = [e.seq for e in log.list_entries()]
    assert seqs == [0, 1, 2, 3, 4, 5]


def test_orphan_in_different_day_directory_is_removed_by_recovery(
    tmp_workspace: Path,
) -> None:
    """Cross-day orphan recovery (plan §5 "no duplicates" promise).

    A writer crashes at 23:59 UTC after writing its entry file but
    before bumping the counter; recovery runs at 00:01 UTC the next
    day. Without explicit recovery, ``atomic_write_text`` would only
    overwrite the canonical path it is given (which now lives in the
    *new* UTC day directory) — the stale orphan in the *old* day
    directory would survive, producing two files with the same seq in
    different day directories.

    The fix: inside the held workspace flock, scan all day subdirs for
    files matching the claimed seq and unlink any whose path differs
    from the canonical write target.
    """
    log = ReplayLog.for_source(tmp_workspace, SOURCE_ID)

    # Seed: append 5 real entries on day D (2026-05-29). Counter ⇒ 5.
    day_d = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)
    for i in range(5):
        _append_one(log, activity=f"real_{i}", timestamp=day_d + timedelta(seconds=i))
    assert log.read_seq() == 5

    # Fabricate the post-crash state: an orphan entry at seq 5 on day D.
    # This represents a writer that wrote the entry file (step 4 of
    # crash discipline) and died before bumping the counter (step 5).
    orphan_ts = datetime(2026, 5, 29, 23, 59, 30, tzinfo=UTC)
    orphan_entry = ReplayLogEntry(
        seq=5,
        timestamp=orphan_ts,
        actor=_make_agent(),
        activity="ORPHAN_FROM_CROSS_DAY_CRASH",
        inputs_hash="i" + "0" * 31,
        outputs_hash="o" + "0" * 31,
        cache_hit=False,
        substrate_changes=["orphan"],
        duration_seconds=0.001,
    )
    orphan_path = (
        tmp_workspace
        / "distillations"
        / SOURCE_ID
        / "replay-log"
        / "2026-05-29"
        / f"{5:0{_SEQ_WIDTH}d}.yaml"
    )
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_text(
        yaml.safe_dump(
            orphan_entry.model_dump(mode="python"),
            sort_keys=True,
            default_flow_style=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    assert orphan_path.is_file()
    assert log.read_seq() == 5

    # Recovery: a writer arrives at 00:01 UTC on day D+1 (2026-05-30).
    # The new entry's canonical path is on day D+1, NOT day D — so
    # ``atomic_write_text`` alone would leave the day-D orphan behind.
    new_ts = datetime(2026, 5, 30, 0, 1, 0, tzinfo=UTC)
    new_entry = _append_one(log, activity="recovery_writer", timestamp=new_ts)

    # The orphan in day D's directory MUST be gone.
    assert not orphan_path.exists(), (
        "cross-day orphan at 2026-05-29/000000000005.yaml was not unlinked"
    )

    # The new entry MUST exist in day D+1's directory.
    new_path = (
        tmp_workspace
        / "distillations"
        / SOURCE_ID
        / "replay-log"
        / "2026-05-30"
        / f"{5:0{_SEQ_WIDTH}d}.yaml"
    )
    assert new_path.is_file()

    # Counter advanced to 6.
    assert log.read_seq() == 6

    # ``get_entry(5)`` returns the NEW entry, not the orphan.
    persisted = log.get_entry(seq=5)
    assert persisted.activity == "recovery_writer"
    assert persisted.activity != "ORPHAN_FROM_CROSS_DAY_CRASH"
    assert persisted == new_entry

    # list_entries yields exactly seqs 0..5 — no duplicate at seq 5.
    seqs = [e.seq for e in log.list_entries()]
    assert seqs == [0, 1, 2, 3, 4, 5]
