"""``amanuensis distill <source-id>`` — orchestrator entry point (M7.3).

The distill command is the supervisor's no-LLM CLI entry into the
extractor + auditor pipeline. It does NOT itself talk to a model — that
is the dispatch driver's job (``amanuensis dispatch``). What this
command does:

1. Confirm the workspace marker (INV-1) via ``@require_marker``.
2. Confirm the source-mirror manifest exists for the requested
   ``source-id``; refuse with a clear message otherwise.
3. Load the orchestrator skill (``distill.md``) from the installed
   ``amanuensis.skills`` package, emit a brief preamble that includes
   the orchestrator skill's frontmatter ``description``.
4. Resolve the role set (``--role-set extractor,auditor`` by default).
   For each role:

   - Read the corresponding ``distill_<role>.md`` skill file from the
     installed package.
   - If the skill is marked ``active: false`` and ``stub: true``: skip
     it, emit a notice to stderr, and append a ``ReplayLogEntry``
     describing the skip (``activity="distill-orchestrate"``,
     ``substrate_changes=["role-skipped:<role>"]``).
   - Otherwise: enqueue a :class:`DispatchQueueEntry` whose
     ``inputs_hash`` is computed via the canonical-form hashing pattern
     :func:`amanuensis.llm.cached_call._compute_inputs_hash` uses so the
     downstream cache + replay-log + PROV records cross-reference
     consistently.

5. Acquire the workspace flock for the duration of steps 4-5 so two
   concurrent ``distill`` invocations cannot race on enqueue.

6. Print a clean handoff message naming the dispatch command the
   supervisor should run next.

Interactive mode (``--interactive``) is a Phase 1 stub: it prints a
notice that the interactive subagent-tool integration is a future
milestone and exits 0.

Judgement calls
---------------
- ``role`` field on AgentAttribution: the closed set in
  :mod:`amanuensis.schemas._shared` does NOT include ``"orchestrator"``.
  We use ``"human_supervisor"`` for the CLI-driven skip-record, which
  is the closed-set value that best matches "the human supervisor's
  CLI is recording an event it observed".
- ``ReplayLogEntry`` shape: the Phase 1 ReplayLogEntry schema has no
  ``entity_type`` field (entity_type belongs to PROV records, and the
  PROV ``entity_type`` is a closed Literal that does not admit
  ``"role-skipped"``). We encode the skip in ``substrate_changes`` as
  ``"role-skipped:<role>"`` — that field's documented purpose is
  "paths written or deleted by the activity," and a skip notice
  conceptually fits the same "what happened" slot without a PROV-schema
  change.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Annotated, Any

import typer

from amanuensis.dispatch.queue import enqueue
from amanuensis.fs import Substrate, acquire_workspace_lock
from amanuensis.llm import DispatchQueueEntry, append_replay_entry
from amanuensis.schemas import AgentAttribution, ReplayLogEntry
from amanuensis.skills._frontmatter import split_frontmatter

from ._marker import fatal, require_marker, workspace_from_kwargs

# Hardcoded Phase 1 default model identifier (M6.5). The actual model
# routing is the dispatch driver's concern; the queue entry carries this
# value so the cross-reference fields (cache key, PROV identifier) all
# agree on what model is intended.
_DEFAULT_MODEL_ID: str = "claude-opus-4-7"

_DEFAULT_ROLE_SET: str = "extractor,auditor"


@require_marker
def distill_command(
    source_id: Annotated[
        str,
        typer.Argument(
            help="Source identifier (the ``source-id`` used at ingest time).",
        ),
    ],
    role_set: Annotated[
        str,
        typer.Option(
            "--role-set",
            help=(
                "Comma-separated role list to enqueue. Default: "
                "``extractor,auditor``. Stub roles (active=false) are "
                "skipped with a stderr notice."
            ),
        ),
    ] = _DEFAULT_ROLE_SET,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            help=(
                "Interactive supervisor mode (M7.3 stub — prints a notice "
                "and exits 0; use the non-interactive default for now)."
            ),
        ),
    ] = False,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Enqueue extractor + auditor (and any other requested roles) for a source."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    if interactive:
        typer.echo(
            "interactive mode is M7.x; for now use the default non-interactive "
            "flow and then `amanuensis dispatch --once`"
        )
        return

    # Step 2: confirm source-mirror existence. We only check existence
    # of the manifest path — parsing happens at dispatch / reconciliation
    # time. A missing manifest means ingest was never run for this id.
    manifest_path = substrate.manifest_path(source_id)
    if not manifest_path.is_file():
        fatal(
            f"source-mirror manifest not found at {manifest_path}; "
            f"run `amanuensis ingest <pdf> --source-id {source_id}` first."
        )
        return  # unreachable; ``fatal`` raises typer.Exit

    # Step 3: load the orchestrator skill and emit the preamble.
    orchestrator_fm, _orchestrator_body = _load_skill("distill.md")
    description = orchestrator_fm.get("description", "")
    typer.echo(f"distill: {description}")
    typer.echo(f"source_id: {source_id}")

    roles = _parse_role_set(role_set)

    # Step 4: classify each role into "enqueue" or "skip" by parsing its
    # skill frontmatter. Reading the frontmatter is a pure FS read on
    # the installed package; it does NOT need the workspace flock.
    enqueue_plans: list[tuple[str, str]] = []  # (role, prompt-body)
    skipped_pairs: list[tuple[str, str]] = []  # (role, stub_reason)
    try:
        for role in roles:
            kind, payload = _classify_role(role)
            if kind == "skip":
                skipped_pairs.append((role, payload))
            else:
                enqueue_plans.append((role, payload))
    except Exception as exc:
        fatal(f"distill failed: {exc}")
        return  # unreachable

    # Step 5: enqueue under the workspace flock so two concurrent
    # ``distill`` invocations cannot race on the queue writes. We do
    # NOT hold the lock across the replay-log appends below — the
    # replay-log helpers acquire the same workspace flock themselves
    # (see :class:`amanuensis.fs.ReplayLog`), and POSIX flock is not
    # reentrant within the same process / fd lineage, so wrapping both
    # in one acquire would deadlock.
    enqueued_count = 0
    try:
        with acquire_workspace_lock(workspace_path):
            for role, body in enqueue_plans:
                _enqueue_role(
                    workspace_path=workspace_path,
                    role=role,
                    body=body,
                    source_id=source_id,
                    manifest_path=manifest_path,
                )
                enqueued_count += 1
    except Exception as exc:
        fatal(f"distill failed: {exc}")
        return  # unreachable

    # Step 6: emit skip notices and record replay-log entries for skips.
    # Done OUTSIDE the workspace flock (see deadlock rationale above);
    # ``append_replay_entry`` takes the lock itself per call.
    skipped: list[str] = []
    for role, stub_reason in skipped_pairs:
        typer.echo(
            f"# skipping stub role: {role} ({stub_reason})",
            err=True,
        )
        sys.stderr.flush()
        try:
            _record_skip(
                workspace_path=workspace_path,
                role=role,
                source_id=source_id,
                stub_reason=stub_reason,
            )
        except Exception as exc:
            fatal(f"distill failed: {exc}")
            return  # unreachable
        skipped.append(role)

    typer.echo(
        f"Enqueued {enqueued_count} role(s) for source {source_id}. "
        "Run `amanuensis dispatch --once` to drain the queue."
    )
    if skipped:
        # Echo the skipped roles to stdout too as a final summary so the
        # operator does not have to scroll back through stderr.
        typer.echo(f"Skipped stub role(s): {', '.join(skipped)}")


# --- Internal helpers -------------------------------------------------


def _parse_role_set(raw: str) -> list[str]:
    """Split the ``--role-set`` value into a list of role names.

    Empty entries (from stray commas) are dropped; leading/trailing
    whitespace per entry is stripped. The result preserves the caller's
    declared order so an operator who wants extractor first, auditor
    second sees that order in the queue.
    """
    parts = [piece.strip() for piece in raw.split(",")]
    return [piece for piece in parts if piece]


def _load_skill(filename: str) -> tuple[dict[str, Any], str]:
    """Read a skill file from the installed ``amanuensis.skills`` package."""
    text = resources.files("amanuensis.skills").joinpath(filename).read_text(encoding="utf-8")
    return split_frontmatter(text)


def _skill_filename_for_role(role: str) -> str:
    """Map ``extractor`` / ``auditor`` / ``contrarian`` / ... to a skill filename.

    The M7.1 shipped naming convention is ``distill_<short-name>.md``;
    the orchestrator skill is the unprefixed ``distill.md``. The mapping
    here is the table the orchestrator uses to find each role's skill.
    """
    # The short-form names ship as ``distill_extract.md`` etc; the role
    # field IN the frontmatter is the long form (``extractor``,
    # ``auditor``, ...). Mapping table is small and explicit.
    aliases: dict[str, str] = {
        "extractor": "distill_extract.md",
        "auditor": "distill_audit.md",
        "contrarian": "distill_contrarian.md",
        "constructive": "distill_constructive.md",
        "premortem": "distill_premortem.md",
    }
    if role in aliases:
        return aliases[role]
    # Unknown role: try the obvious ``distill_<role>.md`` convention so
    # a future role ships its skill file by name and works without
    # touching this table. The caller surfaces the resulting FileNotFound
    # with a clear message.
    return f"distill_{role}.md"


def _classify_role(role: str) -> tuple[str, str]:
    """Classify a role as ``"enqueue"`` or ``"skip"`` per its skill frontmatter.

    Returns ``("enqueue", body)`` for active roles (the body is the
    skill prompt text), or ``("skip", stub_reason)`` for inactive stubs.
    Pure FS read against the installed ``amanuensis.skills`` package;
    no workspace mutation, no flock needed.
    """
    skill_filename = _skill_filename_for_role(role)
    try:
        fm, body = _load_skill(skill_filename)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"role {role!r}: skill file {skill_filename!r} not found in amanuensis.skills package"
        ) from exc

    is_stub = fm.get("stub") is True
    is_active = fm.get("active") is True
    if is_stub and not is_active:
        stub_reason = str(fm.get("stub_reason", "(no stub_reason in frontmatter)"))
        return "skip", stub_reason
    return "enqueue", body


def _enqueue_role(
    *,
    workspace_path: Path,
    role: str,
    body: str,
    source_id: str,
    manifest_path: Path,
) -> None:
    """Build the DispatchQueueEntry for ``role`` and write it to the queue."""
    inputs: dict[str, Any] = {
        "source_id": source_id,
        "manifest_path": str(manifest_path),
        "workspace_root": str(workspace_path),
    }
    inputs_hash = _compute_inputs_hash(
        role=role,
        prompt=body,
        inputs=inputs,
        model_id=_DEFAULT_MODEL_ID,
    )
    entry = DispatchQueueEntry(
        role=role,
        prompt=body,
        inputs=inputs,
        model_id=_DEFAULT_MODEL_ID,
        inputs_hash=inputs_hash,
        enqueued_at=datetime.now(UTC),
    )
    enqueue(workspace_path, entry)
    typer.echo(f"  enqueued: {role} (inputs_hash={inputs_hash[:12]}…)")


def _record_skip(
    *,
    workspace_path: Path,
    role: str,
    source_id: str,
    stub_reason: str,
) -> None:
    """Append a ReplayLogEntry describing a stub-role skip.

    Encoded in ``substrate_changes`` as ``"role-skipped:<role>"`` plus a
    free-form ``"role-skipped-reason:<stub_reason>"``. The
    ``inputs_hash`` field is a deterministic hash of (source_id, role,
    "skipped") so a re-run of the same distill produces the same row id
    in the log — useful for de-duplication if the operator scripts a
    retry loop. The ``outputs_hash`` is the same hash (no separate
    output exists for a skip).
    """
    skip_hash = hashlib.sha256(
        json.dumps(
            {"event": "skipped", "role": role, "source_id": source_id},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    actor = AgentAttribution(
        kind="human",
        identifier="cli",
        role="human_supervisor",
    )
    log_entry = ReplayLogEntry(
        seq=0,  # Overwritten by the appender.
        timestamp=datetime.now(UTC),
        actor=actor,
        activity="distill-orchestrate",
        inputs_hash=skip_hash,
        outputs_hash=skip_hash,
        cache_hit=False,
        substrate_changes=[
            f"role-skipped:{role}",
            f"role-skipped-reason:{stub_reason}",
        ],
        duration_seconds=0.0,
    )
    append_replay_entry(workspace_path, log_entry, source_id=source_id)


def _compute_inputs_hash(
    *,
    role: str,
    prompt: str,
    inputs: dict[str, Any],
    model_id: str,
) -> str:
    """Deterministic SHA-256 hash of the queue entry's canonical inputs.

    Mirrors :func:`amanuensis.llm.cached_call._compute_inputs_hash` —
    canonical-form normalisation (sort dict keys recursively; reject
    NaN/Inf; tz-aware datetimes only; repr() floats) then a JSON encode
    with sorted keys + ``ensure_ascii=True`` + no whitespace +
    ``allow_nan=False``. The hash is the cross-reference key the
    dispatch driver and the cache use.

    We intentionally keep this as a thin local mirror rather than
    importing the private ``_compute_inputs_hash`` from
    :mod:`amanuensis.llm.cached_call` — that function is private to its
    module and we do not want to leak it as an import surface.
    """
    canonical = _to_canonical(
        {
            "role": role,
            "prompt": prompt,
            "inputs": inputs,
            "model_id": model_id,
        }
    )
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _to_canonical(value: Any) -> Any:
    """Canonical-form normalisation for the cache-key payload.

    Local mirror of :func:`amanuensis.llm.cached_call._to_canonical` so
    the distill command produces byte-identical hashes to anything else
    that ever goes through the cached-call wrapper for the same inputs.
    """
    import math

    if isinstance(value, dict):
        mapping: dict[str, Any] = value  # pyright: ignore[reportUnknownVariableType]
        return {k: _to_canonical(mapping[k]) for k in sorted(mapping.keys())}
    if isinstance(value, list):
        items: list[Any] = value  # pyright: ignore[reportUnknownVariableType]
        return [_to_canonical(item) for item in items]
    if isinstance(value, tuple):
        items_tup: tuple[Any, ...] = value  # pyright: ignore[reportUnknownVariableType]
        return [_to_canonical(item) for item in items_tup]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime cannot appear in distill inputs; use tz-aware UTC")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"non-finite float cannot be canonicalised: {value!r}")
        return repr(value)
    return value
