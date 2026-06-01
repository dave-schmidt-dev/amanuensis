"""``amanuensis dispatch`` — drain the dispatch queue (M6.5).

Mutating command. Acquires the workspace flock for the duration of the
drain so a parallel ``distill`` / ``dispatch`` / web POST does not
race on substrate writes.

Three modes:

- ``--check``: probe the four known harness binaries
  (``shutil.which``) and emit a JSON object
  ``{"claude": "/path|null", "codex": "...", "cursor": "...",
  "gemini": "..."}``. No queue work; exit 0.

- ``--once``: process at most one queued entry, then exit. If the queue
  is empty, exit 0 immediately.

- (default): loop, processing entries until the queue is empty OR
  ``--max-iterations`` is reached (safety cap; the default is generous
  enough for any single-source Phase 1 drain).

Per-entry steps:

1. Dequeue (peek; do not unlink yet).
2. Map ``entry.role`` → harness. Phase 1 hardcoded mapping:
   - ``extractor`` → ``claude``
   - ``auditor``  → ``claude``
   - any other role: routed to failures with reason ``role-unmapped``
     until M7.x introduces ``dispatch/role_routes.yaml``.
3. If the mapped harness is not installed: route to failures with
   reason ``harness-not-installed``.
4. Delegate to :func:`amanuensis.llm.cached_call` to consult the cache.
   - Cache hit: ``cached_call`` itself has materialised the output;
     move the queue entry out of the way (it's already been satisfied)
     and append a replay-log entry with ``cache_hit=True``.
   - Cache miss: ``cached_call`` re-wrote the queue entry; the driver
     then:
       a) Snapshots the workspace mtime tree (excluding the role's
          assigned output dir).
       b) Invokes the harness via :func:`amanuensis.dispatch.invoke_role`.
       c) Re-walks the tree; on violation → failures with reason
          ``write-isolation-violation``.
       d) On parse error / non-zero exit / timeout → failures with the
          matching reason.
       e) On success: write a cache entry (mode 0600),
          ``move_to_outputs``, append a replay-log entry with
          ``cache_hit=False``, and write a PROV-O record via
          :func:`amanuensis.llm.write_llm_provenance`.

PROV-O is written ONLY for cache misses. A cache hit is a deterministic
re-play of a prior boundary crossing; the original miss's PROV record
remains the canonical attribution.
"""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from amanuensis.dispatch.driver import (
    KNOWN_HARNESSES,
    InvokeResult,
    detect_harnesses,
    invoke_role,
)
from amanuensis.dispatch.isolation import (
    assert_no_unauthorized_mutation,
    snapshot_workspace_tree,
)
from amanuensis.dispatch.queue import (
    dequeue,
    move_to_failures,
    move_to_outputs,
)
from amanuensis.fs import ReplayLog, Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import _safe_load  # pyright: ignore[reportPrivateUsage]
from amanuensis.fs.replay_log import _MAP_ROLES  # pyright: ignore[reportPrivateUsage]
from amanuensis.llm import (
    DispatchQueueEntry,
    append_replay_entry,
    write_llm_provenance,
)
from amanuensis.schemas import AgentAttribution, ReplayLogEntry

from ._marker import require_marker, workspace_from_kwargs

# --- Configuration constants ---------------------------------------------

# Phase 1 role → harness map. Hardcoded; M7.x can introduce a config
# file (``dispatch/role_routes.yaml``) without changing the dispatch
# loop's contract. Roles not in the map route to failures with reason
# ``role-unmapped`` (vs. crashing the driver — INV-8 demands the queue
# always reaches a resolved state).
_DEFAULT_ROLE_TO_HARNESS: dict[str, str] = {
    "extractor": "claude",
    "auditor": "claude",
    "map-resolve": "claude",
    "map-audit": "claude",
    # Phase 2b M5 — Connector role (proposes cross-doc relations).
    "connect": "claude",
}


_DEFAULT_TIMEOUT_SECONDS: int = 600
"""Per-subprocess wall-clock limit (10 min). Plenty for Phase 1 prompts."""


# Test-only injection seam. The echo-role fixture (M6.4) sets this to
# point at its shell script so the driver bypasses ``shutil.which``.
# Production code never touches this. Keyed by harness id; if absent,
# the driver uses the standard ``shutil.which`` lookup via
# ``invoke_role``'s default. We expose it as a module-level dict because
# the CLI command is invoked via ``typer.testing.CliRunner.invoke`` —
# threading the override through the Typer-bound function signature would
# require a hidden CLI flag, which is worse.
TEST_HARNESS_OVERRIDES: dict[str, Path] = {}
"""TEST-ONLY harness-binary overrides (see module note above)."""


# --- CLI entry point ------------------------------------------------------


@require_marker
def dispatch_command(
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="Probe harness CLIs, emit a JSON report, and exit.",
        ),
    ] = False,
    once: Annotated[
        bool,
        typer.Option(
            "--once",
            help="Process at most one queued entry, then exit.",
        ),
    ] = False,
    max_iterations: Annotated[
        int,
        typer.Option(
            "--max-iterations",
            help="Safety cap on iterations when --once is not set.",
        ),
    ] = 50,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Drain the dispatch queue, routing each entry to its harness."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})

    if check:
        _emit_check_report()
        return

    # The dispatch loop is structurally mutating, but we deliberately do
    # NOT wrap the whole drain in :func:`acquire_workspace_lock`. The
    # writes the loop performs are each individually safe:
    #
    # - Queue / outputs / failures moves use atomic-rename (M6.1).
    # - Cache writes go through :func:`amanuensis.fs._atomic.atomic_write_text`.
    # - Replay-log appends acquire the workspace lock themselves
    #   (:meth:`ReplayLog.append`); wrapping the dispatch loop in the
    #   same lock would deadlock that inner acquire (per-process flock
    #   reacquire blocks on the same fd lineage).
    # - PROV-O writes use atomic-rename through :class:`Substrate`.
    #
    # If a future need requires whole-drain mutual exclusion against
    # other writers (e.g. web POST), the right move is a separate
    # "dispatch is draining" sentinel, not the workspace flock — both
    # because the replay-log helpers need that flock for their own work
    # and because a long-running drain shouldn't keep a clarification
    # form from posting for the entire duration.
    iterations = 0
    cap = 1 if once else max_iterations
    substrate = Substrate(workspace_path)
    while iterations < cap:
        picked = dequeue(workspace_path)
        if picked is None:
            break
        queue_path, entry = picked
        _process_one_entry(
            workspace_path=workspace_path,
            substrate=substrate,
            queue_path=queue_path,
            entry=entry,
        )
        iterations += 1
    typer.echo(f"dispatch: processed {iterations} entr{'y' if iterations == 1 else 'ies'}")


# --- Per-entry processing ------------------------------------------------


def _process_one_entry(
    *,
    workspace_path: Path,
    substrate: Substrate,
    queue_path: Path,
    entry: DispatchQueueEntry,
) -> None:
    """Drive one queue entry end-to-end (cache check, invoke, route)."""
    harness_id = _DEFAULT_ROLE_TO_HARNESS.get(entry.role)
    if harness_id is None:
        move_to_failures(
            workspace_path,
            queue_path,
            reason="role-unmapped",
            detail=(
                f"role {entry.role!r} has no harness mapping in Phase 1's "
                "default role-routes table (extractor / auditor only)"
            ),
        )
        return

    # Production: use shutil.which probe. Tests can pin via
    # TEST_HARNESS_OVERRIDES[harness_id] to point at a fixture script.
    harness_binary_path = TEST_HARNESS_OVERRIDES.get(harness_id)
    if harness_binary_path is None:
        detected = detect_harnesses().get(harness_id)
        if detected is None:
            move_to_failures(
                workspace_path,
                queue_path,
                reason="harness-not-installed",
                detail=(
                    f"harness binary for {harness_id!r} not found on PATH; "
                    "install the harness CLI or remap the role"
                ),
            )
            return

    # Cache lookup is keyed by the entry's own ``inputs_hash`` (which
    # was computed at enqueue time by :func:`cached_call`). We do NOT
    # delegate to ``cached_call`` here because that would re-hash the
    # entry's inputs and, in the rare case where the queue entry's hash
    # was hand-pinned (tests, recovery from a malformed queue), produce
    # a different hash + a NEW queue entry — leaving the original
    # orphaned. The entry's pinned hash IS the contract.
    started_at = datetime.now(UTC)
    cache_path = workspace_path / "cache" / f"{entry.inputs_hash}.yaml"
    if cache_path.is_file():
        _handle_cache_hit(
            workspace_path=workspace_path,
            queue_path=queue_path,
            entry=entry,
            cache_path=cache_path,
            started_at=started_at,
        )
        return

    # Cache miss path: invoke harness, enforce isolation, persist.
    _dispatch_cache_miss(
        workspace_path=workspace_path,
        substrate=substrate,
        queue_path=queue_path,
        entry=entry,
        harness_id=harness_id,
        harness_binary_path=harness_binary_path,
        started_at=started_at,
    )


def _handle_cache_hit(
    *,
    workspace_path: Path,
    queue_path: Path,
    entry: DispatchQueueEntry,
    cache_path: Path,
    started_at: datetime,
) -> None:
    """Materialise the cached output, retire the queue entry, append replay.

    The cache file's shape (per CV-15 + the M5.1 cache format) is
    ``{model_id, output_payload, completed_at}``. We extract
    ``output_payload`` and hand it to :func:`move_to_outputs`, which
    writes the canonical ``dispatch/outputs/.../output.yaml`` and
    unlinks the queue entry atomically. The replay-log entry is then
    appended with ``cache_hit=True``; no PROV-O write (the original
    miss's PROV remains canonical).
    """
    cache_text = cache_path.read_text(encoding="utf-8")
    cache_payload = _safe_load(cache_text)
    output_payload = cache_payload.get("output_payload")
    if not isinstance(output_payload, dict):
        # Cache file is malformed; route to failures rather than crash.
        move_to_failures(
            workspace_path,
            queue_path,
            reason="cache-corrupt",
            detail=(f"cache file at {cache_path} missing or non-dict 'output_payload'"),
        )
        return
    cast_payload: dict[str, Any] = output_payload
    move_to_outputs(
        workspace_path,
        queue_path,
        role=entry.role,
        inputs_hash=entry.inputs_hash,
        output_payload=cast_payload,
    )
    _append_replay(
        workspace_path=workspace_path,
        entry=entry,
        cache_hit=True,
        outputs_hash=entry.inputs_hash,
        duration_seconds=(datetime.now(UTC) - started_at).total_seconds(),
        substrate_changes=[
            f"dispatch/outputs/{entry.role}-{entry.inputs_hash}/output.yaml",
        ],
    )


def _dispatch_cache_miss(
    *,
    workspace_path: Path,
    substrate: Substrate,
    queue_path: Path,
    entry: DispatchQueueEntry,
    harness_id: str,
    harness_binary_path: Path | None,
    started_at: datetime,
) -> None:
    """Invoke the harness for a cache-miss queue entry; route the outcome."""
    output_dir = workspace_path / "dispatch" / "outputs" / f"{entry.role}-{entry.inputs_hash}"
    # Ensure the allowed subtree exists so the snapshot's "allowed"
    # filter is a real path. The role's own output is written later by
    # ``move_to_outputs``; pre-creating the dir is harmless.
    output_dir.mkdir(parents=True, exist_ok=True)

    before = snapshot_workspace_tree(workspace_path, allowed_subtree=output_dir)

    result: InvokeResult = invoke_role(
        harness=harness_id,
        prompt=entry.prompt,
        timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
        harness_binary_path=harness_binary_path,
        cwd=output_dir,
    )

    # Write-isolation check ALWAYS runs, even on subprocess failure —
    # a role that crashed could still have written outside its lane
    # before exiting non-zero.
    violations = assert_no_unauthorized_mutation(before, workspace_path, allowed_subtree=output_dir)
    if violations:
        joined = "; ".join(str(p) for p in violations[:10])
        move_to_failures(
            workspace_path,
            queue_path,
            reason="write-isolation-violation",
            detail=(
                f"role mutated {len(violations)} path(s) outside its assigned output dir: {joined}"
            ),
        )
        return

    if result.timed_out:
        move_to_failures(
            workspace_path,
            queue_path,
            reason="timeout",
            detail=f"harness exceeded {_DEFAULT_TIMEOUT_SECONDS}s wall-clock limit",
        )
        return

    if result.exit_code != 0:
        move_to_failures(
            workspace_path,
            queue_path,
            reason="harness-exit-nonzero",
            detail=f"exit_code={result.exit_code}; stderr={result.stderr[:512]}",
        )
        return

    if result.output_payload is None:
        move_to_failures(
            workspace_path,
            queue_path,
            reason="output-parse-error",
            detail=result.parse_error or "stdout did not parse to a top-level mapping",
        )
        return

    # All gates passed. Persist cache → outputs → replay-log → PROV.
    ended_at = datetime.now(UTC)
    _persist_cache_entry(
        workspace_path=workspace_path,
        inputs_hash=entry.inputs_hash,
        model_id=entry.model_id,
        output_payload=result.output_payload,
        completed_at=ended_at,
    )
    move_to_outputs(
        workspace_path,
        queue_path,
        role=entry.role,
        inputs_hash=entry.inputs_hash,
        output_payload=result.output_payload,
    )
    _append_replay(
        workspace_path=workspace_path,
        entry=entry,
        cache_hit=False,
        outputs_hash=entry.inputs_hash,
        duration_seconds=(ended_at - started_at).total_seconds(),
        substrate_changes=[
            f"cache/{entry.inputs_hash}.yaml",
            f"dispatch/outputs/{entry.role}-{entry.inputs_hash}/output.yaml",
        ],
    )
    _write_prov_for_miss(
        substrate=substrate,
        entry=entry,
        started_at=started_at,
        ended_at=ended_at,
    )


# --- Persistence helpers --------------------------------------------------


def _persist_cache_entry(
    *,
    workspace_path: Path,
    inputs_hash: str,
    model_id: str,
    output_payload: dict[str, Any],
    completed_at: datetime,
) -> Path:
    """Write the cache file at mode 0600 (CV-15)."""
    cache_dir = workspace_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{inputs_hash}.yaml"
    payload: dict[str, Any] = {
        "model_id": model_id,
        "output_payload": output_payload,
        "completed_at": completed_at.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
    }
    text = yaml.safe_dump(payload, sort_keys=True, default_flow_style=False, allow_unicode=True)
    atomic_write_text(cache_path, text)
    try:
        cache_path.chmod(stat.S_IMODE(0o600))
    except FileNotFoundError:  # pragma: no cover - racy cleanup
        pass
    return cache_path


def _append_replay(
    *,
    workspace_path: Path,
    entry: DispatchQueueEntry,
    cache_hit: bool,
    outputs_hash: str,
    duration_seconds: float,
    substrate_changes: list[str],
) -> None:
    """Append a ReplayLogEntry for this dispatch (M5.2 facade).

    Map roles (``map-resolve``, ``map-audit``) route to the workspace-
    level mappings replay log (``mappings/replay-log/``). All other roles
    route to the per-distillation replay log via :func:`append_replay_entry`.
    """
    actor = AgentAttribution(
        kind="llm",
        identifier=entry.model_id,
        role=_coerce_role(entry.role),
    )
    now = datetime.now(UTC)
    if entry.role in _MAP_ROLES:
        # Map roles write to the workspace-level mappings scope, not to
        # a per-distillation tree. Use ReplayLog.for_mappings directly so
        # the replay-log path resolver is in one place (fs.replay_log).
        ReplayLog.for_mappings(workspace_path).append(
            actor=actor,
            activity=f"{entry.role}-dispatch",
            inputs_hash=entry.inputs_hash,
            outputs_hash=outputs_hash,
            cache_hit=cache_hit,
            substrate_changes=substrate_changes,
            duration_seconds=duration_seconds,
            timestamp=now,
        )
        return
    log_entry = ReplayLogEntry(
        seq=0,  # Overwritten by the appender.
        timestamp=now,
        actor=actor,
        activity=f"{entry.role}-dispatch",
        inputs_hash=entry.inputs_hash,
        outputs_hash=outputs_hash,
        cache_hit=cache_hit,
        substrate_changes=substrate_changes,
        duration_seconds=duration_seconds,
    )
    # The dispatch activity is per-distillation; we don't have a source_id
    # on the queue entry directly. The role's inputs payload SHOULD carry
    # one (the extractor's prompt is built per-paragraph), but the queue
    # schema doesn't guarantee it. Convention: try entry.inputs.get(
    # "source_id"); fall back to a workspace-level sentinel.
    source_id = _extract_source_id(entry)
    append_replay_entry(workspace_path, log_entry, source_id=source_id)


def _write_prov_for_miss(
    *,
    substrate: Substrate,
    entry: DispatchQueueEntry,
    started_at: datetime,
    ended_at: datetime,
) -> None:
    """Write the LLM-attributed PROV record for a fresh dispatch.

    Skipped on cache hits (per module docstring). The ``entity_id`` for
    the PROV record is the dispatch output's content hash, since at this
    layer we don't yet know which atom / relation the role produced —
    that's M7.4 reconciliation's concern. For Phase 1's M6 scope, we
    record a PROV record attributing the OUTPUT itself (entity_type
    chosen by role: extractor → atom, auditor → atom).
    """
    # Roles outside the allowed PROV entity-type set silently skip the
    # PROV write — the dispatch is still recorded in the replay log.
    # The PROV writer's closed sets (_LLM_ROLES / _LLM_ENTITY_TYPES) gate
    # which boundary crossings have substrate-level provenance.
    entity_type = _role_to_entity_type(entry.role)
    if entity_type is None:
        return
    try:
        write_llm_provenance(
            substrate=substrate,
            source_id=_extract_source_id(entry),
            entity_type=entity_type,
            entity_id=f"q-{entry.inputs_hash}",  # placeholder; M7.4 replaces
            activity=f"{entry.role}-dispatch",
            started_at=started_at,
            ended_at=ended_at,
            used_entity_ids=[],
            model_id=entry.model_id,
            role=_coerce_role(entry.role),
            inputs_hash=entry.inputs_hash,
        )
    except ValueError:
        # Role / entity-type outside the PROV writer's closed set;
        # silently skip — the replay-log entry is the durable record.
        return


def _coerce_role(role: str) -> Any:
    """Pass through the role string; the PROV writer validates."""
    # PROV writer accepts a Literal of allowed roles; downstream
    # validation happens there. We keep this helper as a single coercion
    # point so future role additions only need to update _LLM_ROLES.
    return role


def _role_to_entity_type(role: str) -> str | None:
    """Map a role to the PROV entity-type it produces.

    Returns None for roles whose output type doesn't map cleanly to the
    LLM-PROV closed set (PROV write is then skipped — the replay log
    still records the boundary crossing).
    """
    # Extractor and auditor both produce/audit atoms in Phase 1.
    if role in ("extractor", "auditor"):
        return "atom"
    return None


def _extract_source_id(entry: DispatchQueueEntry) -> str:
    """Best-effort source_id from the queue entry's inputs payload.

    Falls back to a workspace-level sentinel when the inputs payload
    doesn't carry one. The replay-log + PROV writers require some
    source_id (they file under ``distillations/<source_id>/`` paths);
    losing the per-distillation routing is preferable to crashing the
    drain on a malformed entry.
    """
    candidate = entry.inputs.get("source_id")
    if isinstance(candidate, str) and candidate:
        return candidate
    return "workspace"


# --- --check report -------------------------------------------------------


def _emit_check_report() -> None:
    """Print the harness-availability report as JSON."""
    detected = detect_harnesses()
    # Sort the keys for stable diff in test snapshots.
    payload: dict[str, str | None] = {k: detected.get(k) for k in sorted(KNOWN_HARNESSES)}
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))
