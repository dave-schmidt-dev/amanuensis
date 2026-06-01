"""``amanuensis map`` — entity resolution registry (Phase 2a) + cross-doc relations (Phase 2b).

Commands
--------
- ``amanuensis map [OPTIONS]`` (orchestrator callback) — run the full
  map warp-plan cycle; enqueues the map-resolve role.  T7.2.
- ``amanuensis map status`` — read-only workspace summary.  T7.4.
- ``amanuensis map entity {list,show,merge}`` — entity CRUD; T7.5-T7.6.
- ``amanuensis map resolution {show,supersede}`` — resolution inspection; T7.8-T7.9 stubs.
- ``amanuensis map vocabulary {show,snapshot}`` — vocabulary registry; T7.10 stubs.
- ``amanuensis map relation {list,show,supersede}`` — cross-doc relation
  inspection + correction (Phase 2b M7 / T7.1-T7.3).

Hard rules upheld here
-----------------------
- INV-1: every non-stub command is wrapped in ``@require_marker``.
- INV-4: ``map status`` is read-only; no flock, no replay-log writes.
- INV-8: substrate access is mediated through ``Substrate`` exclusively.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Annotated, Any

import typer

from amanuensis.dispatch.connect_orchestrator import run_connect_phase
from amanuensis.dispatch.hierarchize_orchestrator import run_hierarchize_phase
from amanuensis.dispatch.queue import enqueue
from amanuensis.fs import ReplayLog, Substrate, WorkspaceLockTimeout, acquire_workspace_lock
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import serialize_yaml
from amanuensis.llm.queue import DispatchQueueEntry
from amanuensis.schemas import (
    AgentAttribution,
    CrossDocRelationSupersede,
    EntitySupersede,
    Probandum,
    ProvenanceRecord,
    Resolution,
    ResolutionSupersede,
    RoleAttribution,
    compute_id,
)
from amanuensis.vocabulary.entity_registry import EntityVocabularyError, load_entity_vocabulary

from ._common import load_workspace_config
from ._marker import fatal, require_marker, workspace_from_kwargs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MODEL_ID: str = "claude-opus-4-7"
_DEFAULT_ROLE_SET: str = "map-resolve,map-audit"

# The on-disk subdir under each harness's skills root that owns our files.
_AMANUENSIS_NAMESPACE: str = "amanuensis"

# Map roles required in the harness skill directory for the preflight check.
_REQUIRED_SKILL_FILES: tuple[str, ...] = ("map_resolve.md", "map_audit.md")

# ---------------------------------------------------------------------------
# Top-level app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="map",
    help="Resolve entities across distillations; manage the mapping registry.",
    invoke_without_command=True,
    no_args_is_help=False,
    add_completion=False,
)

# Module-level alias used by callers that import the map sub-app
# directly (notably ``tests/cli/test_map_relation.py``). The CLI is
# wired through ``amanuensis.cli.app.add_typer(map_cli.app, ...)``; this
# alias gives external consumers a name that does not collide with
# their own ``app`` symbol.
map_app = app

# ---------------------------------------------------------------------------
# Nested sub-apps
# ---------------------------------------------------------------------------

entity_app = typer.Typer(
    name="entity",
    help="Inspect and manage canonical entities.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(entity_app, name="entity", help="Inspect and manage canonical entities.")

resolution_app = typer.Typer(
    name="resolution",
    help="Inspect and supersede resolution records.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(
    resolution_app,
    name="resolution",
    help="Inspect and supersede resolution records.",
)

vocabulary_app = typer.Typer(
    name="vocabulary",
    help="Show and snapshot the entity-kind vocabulary.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(
    vocabulary_app,
    name="vocabulary",
    help="Show and snapshot the entity-kind vocabulary.",
)

# Phase 2b M7: cross-doc relation sub-app (list / show / supersede).
relation_app = typer.Typer(
    name="relation",
    help="Inspect and supersede cross-doc relation records.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(
    relation_app,
    name="relation",
    help="Inspect and supersede cross-doc relation records.",
)

# Phase 2c M9: probandum sub-app (add / list / show / lineage / link /
# supersede). Probandum-edge supersede lives under its own peer sub-app
# (``probandum_edge_app`` below) — the id namespaces and supersede
# pipelines are distinct, mirroring how Phase 2b put relation supersedes
# under ``map relation`` rather than under a generic supersede verb.
probandum_app = typer.Typer(
    name="probandum",
    help="Manage Phase 2c argument-tree probanda (ultimate / penultimate / interim).",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(
    probandum_app,
    name="probandum",
    help="Manage Phase 2c argument-tree probanda (ultimate / penultimate / interim).",
)

# Probandum-edge supersede lives at ``map probandum-edge supersede``; the
# only verb is ``supersede`` for now so the sub-app stays single-purpose.
probandum_edge_app = typer.Typer(
    name="probandum-edge",
    help="Supersede Phase 2c probandum-edges.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(
    probandum_edge_app,
    name="probandum-edge",
    help="Supersede Phase 2c probandum-edges.",
)

# Walton-scheme registry (closed vocabulary backing INV-18 at probandum
# write-time). Read-only ``show`` + mutating ``snapshot`` (with optional
# ``--extend``) mirror Phase 2a's ``map vocabulary`` sub-app.
walton_scheme_app = typer.Typer(
    name="walton-scheme",
    help="Show and snapshot the Walton-scheme registry (Phase 2c closed vocabulary).",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(
    walton_scheme_app,
    name="walton-scheme",
    help="Show and snapshot the Walton-scheme registry (Phase 2c closed vocabulary).",
)


# ---------------------------------------------------------------------------
# Top-level map orchestrator (T7.2)
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
@require_marker
def map_command(
    ctx: typer.Context,
    role_set: Annotated[
        str,
        typer.Option(
            "--role-set",
            help=("Comma-separated role list to enqueue. Default: ``map-resolve,map-audit``."),
        ),
    ] = _DEFAULT_ROLE_SET,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help=(
                "Non-interactive mode (default and only mode for now). "
                "The flag exists for forward-compat with Phase 2a.5."
            ),
        ),
    ] = False,
    connect_only: Annotated[
        bool,
        typer.Option(
            "--connect-only",
            help=(
                "Skip the resolve/audit phases and run only the Phase 2b "
                "Connect phase against an already-resolved substrate."
            ),
        ),
    ] = False,
    hierarchize_only: Annotated[
        bool,
        typer.Option(
            "--hierarchize-only",
            help=(
                "Skip the resolve/audit/connect phases and run only the "
                "Phase 2c Hierarchize phase against an already-resolved + "
                "connected substrate."
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
    """Run the full map warp-plan cycle (T7.2 + Phase 2b M6/T6.3 + Phase 2c M8/T8.5).

    Default phase order:

    1. **Resolve / audit** — enqueue ``map-resolve`` (and, after a
       supervisor runs ``amanuensis dispatch --once``, the operator
       re-runs ``amanuensis map`` to enqueue ``map-audit``). This
       half is Phase 2a M11.2's first-engagement contract.
    2. **Connect** — enqueue one ``connect`` dispatch event per
       multi-source canonical-entity cluster, then reconcile any
       pending connect outputs. The driver-side LLM invocation is
       deferred to first-engagement (the supervisor runs
       ``amanuensis dispatch --once`` between phases).
    3. **Hierarchize** — enqueue one ``hierarchize`` dispatch event per
       qualifying penultimate cluster, then reconcile any pending
       hierarchize outputs. Skipped silently when the Walton-scheme
       snapshot is not yet pinned (the operator hasn't engaged Phase
       2c yet). The driver-side LLM invocation is deferred to
       first-engagement.

    ``--connect-only`` skips step 1 entirely and runs steps 2 + 3
    (Connect + Hierarchize) — useful when the resolve+audit substrate
    is already settled and the operator just wants to refresh
    cross-doc edges and the argument tree.

    ``--hierarchize-only`` skips steps 1 + 2 and runs only step 3 —
    useful when the operator is iterating on the Hierarchize role
    against an already-connected substrate.

    ``--non-interactive`` is the default and only implemented mode.
    An interactive mode that drives dispatch inline is Phase 2a.5
    future work, not blocking.
    """
    # Only run the orchestrator body when invoked directly (i.e. no
    # subcommand was given).  When a subcommand is present Typer invokes
    # the callback first, then the subcommand — we skip the orchestrator
    # body in that case.
    if ctx.invoked_subcommand is not None:
        return

    # ``non_interactive`` is the only implemented mode for now; the flag
    # is accepted for forward-compat with Phase 2a.5 interactive mode.
    # Consume the value so static analysis (vulture) sees it as used.
    _ = non_interactive

    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    # ------------------------------------------------------------------
    # R13: empty-workspace short-circuit.  If no distillations exist
    # there is nothing to resolve.  This runs BEFORE the skill preflight
    # (see ordering note below): a workspace with no distillations needs
    # a friendly message regardless of whether the skills are installed.
    # ------------------------------------------------------------------
    source_ids: list[str] = sorted(substrate.list_distillations())
    if not source_ids:
        typer.echo(
            f"no distillations found under {workspace_path}/distillations/; "
            "run `amanuensis distill` first"
        )
        return

    # ------------------------------------------------------------------
    # T7.3 preflight: both map skills must be installed for the claude
    # harness.  We check AFTER the empty-workspace branch so operators
    # with no distillations still see the friendly message regardless of
    # skill state.
    #
    # Env-var seam: AMANUENSIS_HARNESS_HOME overrides Path.home() so
    # tests can point at a fake home without monkeypatching Path.home.
    #
    # Phase 2b note: the connect-only path skips the resolve/audit skill
    # preflight too, on the assumption that an operator targeting
    # ``--connect-only`` has already validated the resolve/audit skills
    # are present at least once. If they haven't, the connect skill
    # file (bundled into the package) is still resolved via importlib.
    # ------------------------------------------------------------------
    # Skip preflight when scoping to a downstream phase (connect or
    # hierarchize); those flags assume the resolve/audit skills have
    # been validated at least once already.
    if not connect_only and not hierarchize_only:
        harness_home_str = os.environ.get("AMANUENSIS_HARNESS_HOME")
        harness_home = Path(harness_home_str) if harness_home_str else Path.home()
        skills_dir = harness_home / ".claude" / "skills" / _AMANUENSIS_NAMESPACE
        missing = [f for f in _REQUIRED_SKILL_FILES if not (skills_dir / f).is_file()]
        if missing:
            typer.secho(
                "map-resolve/map-audit skills not installed for harness 'claude'; "
                "run `amanuensis install-skills --harness claude` first",
                err=True,
            )
            raise typer.Exit(code=2)

    # ------------------------------------------------------------------
    # Acquire workspace flock (5 s timeout) for the resolve/audit
    # orchestrator body. The Connect phase runs AFTER the flock is
    # released:
    #
    #   - ``enqueue_connect_clusters`` only writes content-addressable
    #     queue files (atomic_write_text); it does not append to the
    #     replay log and does not need flock protection.
    #   - ``reconcile_outputs`` re-acquires the flock itself for the
    #     mappings-substrate write transaction; a re-entrant fresh
    #     ``os.open`` of the lock file from the same process would
    #     deadlock, so we drop the resolve/audit lock first.
    # ------------------------------------------------------------------
    if not connect_only and not hierarchize_only:
        try:
            with acquire_workspace_lock(workspace_path, timeout=5.0):
                _run_map_orchestrator(
                    workspace_path=workspace_path,
                    substrate=substrate,
                    source_ids=source_ids,
                    role_set=role_set,
                )
        except WorkspaceLockTimeout as exc:
            typer.secho(
                "workspace flock held by another process — wait or release .amanuensis-lock",
                err=True,
            )
            raise typer.Exit(code=2) from exc

    # Phase 2b Connect phase: enqueue clusters + drain pending connect
    # outputs. Skipped under ``--hierarchize-only``.
    if not hierarchize_only:
        report = run_connect_phase(substrate)
        _emit_connect_phase_summary(report=report, connect_only=connect_only)

    # Phase 2c Hierarchize phase: enqueue penultimate clusters + drain
    # pending hierarchize outputs. Runs after Connect (and outside any
    # workspace flock — ``run_hierarchize_phase`` re-acquires the flock
    # internally via ``reconcile_outputs``).
    #
    # Skipped when the Walton-scheme snapshot is missing: the operator
    # has not yet engaged Phase 2c, so silently no-op rather than
    # raising. (``amanuensis map vocabulary walton snapshot`` pins it.)
    # Exception: under ``--hierarchize-only`` the operator has
    # explicitly asked for Hierarchize, so a missing snapshot is a
    # hard error (mirroring how ``--connect-only`` would behave if the
    # connect skill bundle were unbundled).
    if substrate.load_walton_scheme_snapshot() is not None:
        hierarchize_report = run_hierarchize_phase(substrate)
        _emit_hierarchize_phase_summary(report=hierarchize_report)
    elif hierarchize_only:
        typer.secho(
            "Walton-scheme snapshot not pinned; "
            "run `amanuensis map vocabulary walton snapshot` first",
            err=True,
        )
        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# Phase 2c Hierarchize-phase summary emitter (T8.3)
# ---------------------------------------------------------------------------


def _emit_hierarchize_phase_summary(*, report: Any) -> None:
    """Echo a supervisor-facing summary of the Hierarchize-phase outcome.

    Mirrors :func:`_emit_connect_phase_summary` — operators scanning
    ``amanuensis map`` output should see one line per phase.

    ``report`` is a ``HierarchizePhaseReport`` (typed loosely as
    ``Any`` here to keep the cross-module import light; the dataclass
    shape is stable and the only fields read are the numeric counters
    and the committed/clarification lists).
    """
    label = "Hierarchize phase"
    if report.enqueued == 0 and report.outputs_consumed == 0:
        typer.echo(
            f"{label}: no clusters enqueued, no outputs to consume. "
            "Run `amanuensis dispatch --once` to drive any pending hierarchize events."
        )
        return
    typer.echo(
        f"{label}: enqueued={report.enqueued} "
        f"outputs_consumed={report.outputs_consumed} "
        f"probanda_committed={len(report.probanda_committed)} "
        f"edges_committed={len(report.edges_committed)} "
        f"clarifications_raised={len(report.clarifications_raised)}"
    )


# ---------------------------------------------------------------------------
# Phase 2b Connect-phase summary emitter (T6.3)
# ---------------------------------------------------------------------------


def _emit_connect_phase_summary(
    *,
    report: Any,
    connect_only: bool,
) -> None:
    """Echo a supervisor-facing summary of the Connect-phase outcome.

    Mirrors the brevity of the resolve/audit handoff line — operators
    scanning ``amanuensis map`` output should see one line per phase.

    ``report`` is a ``ConnectPhaseReport`` (typed loosely as ``Any``
    here to keep the cross-module import light; the dataclass shape is
    stable and the only fields read are the four numeric counters).
    """
    label = "connect" if connect_only else "Connect phase"
    if report.enqueued == 0 and report.outputs_consumed == 0:
        # Most common case for an operator running ``amanuensis map``
        # on a fresh resolve/audit substrate: no connect outputs have
        # landed yet (the supervisor hasn't dispatched the connect
        # queue). Surface this clearly so the next step is obvious.
        typer.echo(
            f"{label}: no clusters enqueued, no outputs to consume. "
            "Run `amanuensis dispatch --once` to drive any pending connect events."
        )
        return
    typer.echo(
        f"{label}: enqueued={report.enqueued} "
        f"outputs_consumed={report.outputs_consumed} "
        f"relations_committed={len(report.relations_committed)} "
        f"clarifications_raised={len(report.clarifications_raised)}"
    )


# ---------------------------------------------------------------------------
# Internal orchestrator (called under workspace flock)
# ---------------------------------------------------------------------------


def _run_map_orchestrator(
    *,
    workspace_path: Path,
    substrate: Substrate,
    source_ids: list[str],
    role_set: str,
) -> None:
    """Run the map orchestrator body while the workspace flock is held.

    Steps:
    1. Pin the entity-vocabulary snapshot on first invocation.
    2. Compute the inputs_hash.
    3. Build and enqueue the DispatchQueueEntry.
    4. Append a mappings replay-log entry (_lock_held=True).
    5. Print the supervisor-facing handoff message.
    """
    # Step 1: pin the snapshot on first invocation.
    snapshot_path = substrate.entity_vocabulary_snapshot_path()
    snapshot_was_new = False
    if not snapshot_path.is_file():
        vocab_path = _resolve_entity_vocab_template(workspace_path)
        if vocab_path is None:
            typer.secho(
                "entity-vocabulary template not found at "
                "vocabularies/generic/entity-kinds.yaml (repo-bundled default) "
                "or at the workspace's configured override — the bundled template "
                "ships with the repo; verify your install",
                err=True,
            )
            raise typer.Exit(code=1)
        try:
            vocab = load_entity_vocabulary(vocab_path)
        except EntityVocabularyError as exc:
            fatal(f"entity-vocabulary template invalid: {exc}")
            return  # unreachable; fatal raises
        substrate.snapshot_entity_vocabulary(vocab)
        snapshot_was_new = True

    # Step 2: compute inputs_hash.
    inputs_hash = _compute_map_inputs_hash(
        workspace_path=workspace_path,
        snapshot_path=snapshot_path,
        role_set=role_set,
    )

    # Step 3: read the map_resolve.md prompt body.
    prompt_body = (
        resources.files("amanuensis.skills").joinpath("map_resolve.md").read_text(encoding="utf-8")
    )

    entry = DispatchQueueEntry(
        role="map-resolve",
        prompt=prompt_body,
        inputs={
            "source_ids": source_ids,
            "snapshot_path": str(snapshot_path.relative_to(workspace_path)),
        },
        model_id=_DEFAULT_MODEL_ID,
        inputs_hash=inputs_hash,
        enqueued_at=datetime.now(UTC),
    )

    # Step 4: enqueue.
    queue_path = enqueue(workspace_path, entry)

    # Step 5: append replay-log entry (_lock_held=True — we hold the flock).
    substrate_changes: list[str] = [str(queue_path.relative_to(workspace_path))]
    if snapshot_was_new:
        substrate_changes.insert(0, str(snapshot_path.relative_to(workspace_path)))

    actor = AgentAttribution(
        kind="human",
        identifier="cli",
        role="human_supervisor",
    )
    ReplayLog.for_mappings(workspace_path).append(
        actor=actor,
        activity="map-orchestrate",
        inputs_hash=inputs_hash,
        outputs_hash=inputs_hash,
        cache_hit=False,
        substrate_changes=substrate_changes,
        duration_seconds=0.0,
        _lock_held=True,
    )

    # Step 6: supervisor-facing handoff.
    typer.echo(
        f"Enqueued role: map-resolve-{inputs_hash[:8]}. "
        "Run `amanuensis dispatch --once` to drive it."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_entity_vocab_template(workspace_path: Path) -> Path | None:
    """Return the entity-kinds vocab YAML path to use, or None if not found.

    Priority:
    1. ``domain.entity_vocabulary_registry`` from workspace amanuensis.yaml
       (expanded via ``~`` and ``$VAR``); accepts a file path.
    2. Bundled ``vocabularies/generic/entity-kinds.yaml`` at the repo root
       (``__file__`` is ``src/amanuensis/cli/map.py``; parents[3] = repo root).
    """
    config = load_workspace_config(workspace_path)
    domain = config.get("domain")
    if isinstance(domain, dict):
        domain_dict: dict[str, Any] = domain  # pyright: ignore[reportUnknownVariableType]
        registry_value = domain_dict.get("entity_vocabulary_registry")
        if isinstance(registry_value, str) and registry_value:
            expanded = Path(os.path.expandvars(os.path.expanduser(registry_value)))
            if expanded.is_file():
                return expanded

    # Bundled generic vocabulary: <repo>/vocabularies/generic/entity-kinds.yaml.
    # __file__ is src/amanuensis/cli/map.py → parents[3] = repo root.
    bundled = Path(__file__).resolve().parents[3] / "vocabularies" / "generic" / "entity-kinds.yaml"
    if bundled.is_file():
        return bundled

    return None


def _compute_map_inputs_hash(
    *,
    workspace_path: Path,
    snapshot_path: Path,
    role_set: str,
) -> str:
    """Deterministic SHA-256 hash for the map-resolve queue entry.

    The hash covers:
    - substrate_state_digest: SHA-256 of the sorted list of
      (relative_path, sha256_of_content) tuples for every file under
      ``distillations/<src>/atoms/``, ``distillations/<src>/relations/``,
      ``mappings/entities/``, and ``mappings/resolutions/``.
    - entity_vocab_snapshot_hash: SHA-256 of the snapshot file bytes
      (or empty-string hash if the snapshot does not yet exist on disk —
      this branch is hit only when the snapshot was JUST written in the
      same lock section, so we read it fresh below).
    - role_set_tag: sorted comma-joined role set string.
    """
    # Substrate state digest.
    substrate_files: list[tuple[str, str]] = []
    for subtree in (
        "distillations",
        "mappings/entities",
        "mappings/resolutions",
    ):
        base = workspace_path / subtree
        if subtree == "distillations":
            # Walk atoms/ and relations/ sub-trees for each source.
            if not base.is_dir():
                continue
            for src_dir in sorted(base.iterdir()):
                if not src_dir.is_dir():
                    continue
                for subdir_name in ("atoms", "relations"):
                    subdir = src_dir / subdir_name
                    if not subdir.is_dir():
                        continue
                    for fpath in sorted(subdir.rglob("*")):
                        if fpath.is_file() and ".tmp." not in fpath.name:
                            rel = str(fpath.relative_to(workspace_path))
                            content_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
                            substrate_files.append((rel, content_hash))
        else:
            if not base.is_dir():
                continue
            for fpath in sorted(base.rglob("*")):
                if fpath.is_file() and ".tmp." not in fpath.name:
                    rel = str(fpath.relative_to(workspace_path))
                    content_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
                    substrate_files.append((rel, content_hash))

    substrate_state_digest = hashlib.sha256(
        json.dumps(sorted(substrate_files), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    # Entity vocab snapshot hash.
    if snapshot_path.is_file():
        entity_vocab_snapshot_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    else:
        entity_vocab_snapshot_hash = hashlib.sha256(b"").hexdigest()

    # Role set tag: sorted comma-joined.
    role_set_tag = ",".join(sorted(r.strip() for r in role_set.split(",") if r.strip()))

    canonical = json.dumps(
        {
            "entity_vocab_snapshot_hash": entity_vocab_snapshot_hash,
            "role_set_tag": role_set_tag,
            "substrate_state_digest": substrate_state_digest,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# map status (T7.4)
# ---------------------------------------------------------------------------


_RESOLUTION_CLARIFICATION_KINDS = frozenset({"resolution-disputed", "resolution-ambiguous"})


@dataclass(frozen=True, slots=True)
class _MapStatusCounts:
    """Per-distillation or workspace-aggregate map status counts."""

    entity_operand_count: int
    resolved_count: int
    unresolved_count: int
    open_clarification_count: int
    last_map_run_at: str  # ISO 8601 UTC or "never"


def _compute_last_map_run_at(workspace_path: Path) -> str:
    """Return newest mappings replay-log entry timestamp, or 'never'."""
    try:
        log = ReplayLog.for_mappings(workspace_path)
    except Exception:
        return "never"
    newest: datetime | None = None
    for entry in log.list_entries():
        ts = entry.timestamp
        if newest is None or ts > newest:
            newest = ts
    if newest is None:
        return "never"
    return newest.astimezone(UTC).isoformat()


def _status_for_source(
    substrate: Substrate,
    source_id: str,
    last_map_run_at: str,
) -> _MapStatusCounts:
    """Compute map status counts for one distillation."""
    entity_operand_count = 0
    resolved_count = 0

    for atom in substrate.list_atoms(source_id):
        for idx, operand in enumerate(atom.operands):
            if operand.kind != "entity":
                continue
            entity_operand_count += 1
            resolution = substrate.latest_resolution_for(source_id, atom.id, idx)
            if resolution is not None:
                resolved_count += 1

    # substrate.list_clarifications has no source_id filter, so walk the
    # per-distillation open/ directory directly to count resolution-kind
    # clarifications for this source only.
    open_clarification_count = _count_open_resolution_clarifications(substrate, source_id)

    unresolved_count = max(0, entity_operand_count - resolved_count - open_clarification_count)

    return _MapStatusCounts(
        entity_operand_count=entity_operand_count,
        resolved_count=resolved_count,
        unresolved_count=unresolved_count,
        open_clarification_count=open_clarification_count,
        last_map_run_at=last_map_run_at,
    )


def _count_open_resolution_clarifications(substrate: Substrate, source_id: str) -> int:
    """Count open clarifications with resolution kinds for one distillation."""
    clar_open_dir = substrate.root / "distillations" / source_id / "clarifications" / "open"
    if not clar_open_dir.is_dir():
        return 0
    from amanuensis.fs._serialize import (
        parse_clarification_md,
    )

    count = 0
    for path in sorted(clar_open_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".md"):
            continue
        if ".tmp." in path.name:
            continue
        try:
            clar = parse_clarification_md(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if clar.kind in _RESOLUTION_CLARIFICATION_KINDS:
            count += 1
    return count


def _counts_to_dict(counts: _MapStatusCounts) -> dict[str, object]:
    """Serialise a _MapStatusCounts to a plain dict for JSON output."""
    return {
        "entity_operand_count": counts.entity_operand_count,
        "resolved_count": counts.resolved_count,
        "unresolved_count": counts.unresolved_count,
        "open_clarification_count": counts.open_clarification_count,
        "last_map_run_at": counts.last_map_run_at,
    }


def _emit_status_json(
    workspace_path: Path,
    per_distillation: dict[str, _MapStatusCounts],
    aggregate: _MapStatusCounts,
) -> None:
    """Print sorted-key JSON status payload."""
    payload: dict[str, object] = {
        "workspace_root": str(workspace_path),
        "workspace_aggregate": _counts_to_dict(aggregate),
    }
    if per_distillation:
        payload["per_distillation"] = {
            src: _counts_to_dict(c) for src, c in sorted(per_distillation.items())
        }
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _emit_status_human(
    workspace_path: Path,
    per_distillation: dict[str, _MapStatusCounts],
    aggregate: _MapStatusCounts,
) -> None:
    """Print human-readable map status summary."""
    typer.echo(f"workspace:             {workspace_path}")
    typer.echo("--- workspace_aggregate ---")
    typer.echo(f"  entity_operand_count:    {aggregate.entity_operand_count}")
    typer.echo(f"  resolved_count:          {aggregate.resolved_count}")
    typer.echo(f"  unresolved_count:        {aggregate.unresolved_count}")
    typer.echo(f"  open_clarification_count:{aggregate.open_clarification_count}")
    typer.echo(f"  last_map_run_at:         {aggregate.last_map_run_at}")
    for source_id, counts in sorted(per_distillation.items()):
        typer.echo(f"--- {source_id} ---")
        typer.echo(f"  entity_operand_count:    {counts.entity_operand_count}")
        typer.echo(f"  resolved_count:          {counts.resolved_count}")
        typer.echo(f"  unresolved_count:        {counts.unresolved_count}")
        typer.echo(f"  open_clarification_count:{counts.open_clarification_count}")
        typer.echo(f"  last_map_run_at:         {counts.last_map_run_at}")


@app.command("status")
@require_marker
def status_command(
    source_id_filter: Annotated[
        str | None,
        typer.Option(
            "--source-id",
            help="Filter to a single distillation by source-id.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-parseable JSON instead of human-readable text.",
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
    """Print map status counts for the workspace (read-only; INV-4)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    # Validate --source-id if supplied.
    all_source_ids = list(substrate.list_distillations())
    if source_id_filter is not None and source_id_filter not in all_source_ids:
        typer.echo(
            f"no source-id {source_id_filter!r} under distillations/",
            err=False,
        )
        raise typer.Exit(code=1)

    source_ids = [source_id_filter] if source_id_filter is not None else all_source_ids

    last_map_run_at = _compute_last_map_run_at(workspace_path)

    per_distillation: dict[str, _MapStatusCounts] = {
        src: _status_for_source(substrate, src, last_map_run_at) for src in source_ids
    }

    # Aggregate across all selected distillations.
    agg_entity = sum(c.entity_operand_count for c in per_distillation.values())
    agg_resolved = sum(c.resolved_count for c in per_distillation.values())
    agg_open_clar = sum(c.open_clarification_count for c in per_distillation.values())
    agg_unresolved = max(0, agg_entity - agg_resolved - agg_open_clar)
    aggregate = _MapStatusCounts(
        entity_operand_count=agg_entity,
        resolved_count=agg_resolved,
        unresolved_count=agg_unresolved,
        open_clarification_count=agg_open_clar,
        last_map_run_at=last_map_run_at,
    )

    if json_output:
        _emit_status_json(workspace_path, per_distillation, aggregate)
    else:
        _emit_status_human(workspace_path, per_distillation, aggregate)


# ---------------------------------------------------------------------------
# entity sub-commands (T7.5, T7.6)
# ---------------------------------------------------------------------------


@entity_app.command("list")
@require_marker
def entity_list_command(
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            help="Filter to entities of the given kind (must be in active vocabulary snapshot).",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """List canonical entities in the workspace (read-only; T7.5)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    # Validate --kind against active vocabulary snapshot if given.
    if kind is not None:
        from amanuensis.fs._errors import SubstrateNotFound

        try:
            vocab = substrate.get_entity_vocabulary_snapshot()
        except SubstrateNotFound:
            vocab = None
        valid_kinds: set[str] = {k.id for k in vocab.kinds} if vocab is not None else set()
        if vocab is not None and kind not in valid_kinds:
            typer.secho(
                f"kind '{kind}' not in active vocabulary snapshot; "
                "run `amanuensis map vocabulary show` to see kinds",
                err=True,
            )
            raise typer.Exit(code=2)

    entities = sorted(
        substrate.list_entities(),
        key=lambda e: (e.kind, e.canonical_name),
    )
    for entity in entities:
        if kind is not None and entity.kind != kind:
            continue
        typer.echo(
            f"{entity.id}  kind={entity.kind}  "
            f"canonical={entity.canonical_name}  aliases={len(entity.aliases)}"
        )


@entity_app.command("show")
@require_marker
def entity_show_command(
    entity_id: Annotated[
        str,
        typer.Argument(help="Entity id (e.g. e-<hash>)."),
    ],
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Print a canonical entity's frontmatter + resolutions + supersede chain (read-only; T7.5)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    path = substrate.entity_path(entity_id)
    if not path.is_file():
        typer.secho(
            f"entity '{entity_id}' not found in mappings/entities/",
            err=True,
        )
        raise typer.Exit(code=1)

    # Print raw on-disk content (frontmatter + markdown body).
    typer.echo(path.read_text(encoding="utf-8"), nl=False)

    # Resolutions pointing here.
    typer.echo("\n## Resolutions pointing here")
    resolution_count = 0
    for r in substrate.list_resolutions(where_entity_id=entity_id):
        short = r.id[2:10] if len(r.id) > 2 else r.id
        typer.echo(
            f"j-{short}  source={r.source_id}  atom={r.atom_id}  "
            f"operand={r.operand_index}  confidence={r.confidence}"
        )
        resolution_count += 1
    if resolution_count == 0:
        typer.echo("(none)")

    # Supersede chain.
    typer.echo("\n## Supersede chain")
    from amanuensis.fs._errors import (
        SubstrateNotFound,
        SupersedeChainTooDeep,
        SupersedeCycleDetected,
    )

    try:
        latest = substrate.latest_entity_for(entity_id)
    except (SubstrateNotFound, SupersedeCycleDetected, SupersedeChainTooDeep) as exc:
        typer.echo(f"(error walking chain: {exc})")
        return

    if latest.id == entity_id:
        typer.echo("(latest in chain)")
    else:
        typer.echo(f"superseded by {latest.id}")
        # Walk intermediate hops: find each EntitySupersede where
        # superseded_entity_id == current, chain forward.
        current = entity_id
        while current != latest.id:
            found_next = False
            for record in substrate.list_supersedes(kind="entity"):
                if isinstance(record, EntitySupersede) and record.superseded_entity_id == current:
                    typer.echo(f"  {current} -> {record.replacement_entity_id}")
                    current = record.replacement_entity_id
                    found_next = True
                    break
            if not found_next:
                break


@entity_app.command("merge")
@require_marker
def entity_merge_command(
    a_id: Annotated[
        str,
        typer.Argument(help="First entity id to merge."),
    ],
    b_id: Annotated[
        str,
        typer.Argument(help="Second entity id to merge."),
    ],
    canonical: Annotated[
        str,
        typer.Option(
            "--canonical",
            help="The entity id that becomes the canonical (surviving) entity.",
        ),
    ],
    reason: Annotated[
        str,
        typer.Option(
            "--reason",
            help="Reason for the merge (recorded in EntitySupersede).",
        ),
    ],
    actor: Annotated[
        str,
        typer.Option(
            "--actor",
            help="Identifier of the human performing the merge.",
        ),
    ] = "cli",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Print what would be written without making any changes.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Allow merging entities that are already superseded.",
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
    """Merge two entities, writing an EntitySupersede record (T7.6).

    Acquires workspace flock for the duration of the write.
    Supports --dry-run (no writes) and --force (allow already-superseded).
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    from amanuensis.fs._errors import SubstrateNotFound

    # --- Validate all three entity ids exist ---------------------------
    for eid, label in [(a_id, "first"), (b_id, "second"), (canonical, "--canonical")]:
        if not substrate.entity_path(eid).is_file():
            if label == "--canonical":
                typer.secho(
                    f"--canonical '{canonical}' is not in mappings/entities/",
                    err=True,
                )
            else:
                typer.secho(
                    f"entity '{eid}' not found in mappings/entities/",
                    err=True,
                )
            raise typer.Exit(code=1)

    # --- Validate neither is already superseded (unless --force) -------
    if not force:
        for eid in (a_id, b_id):
            try:
                latest = substrate.latest_entity_for(eid)
            except SubstrateNotFound:
                latest = None
            if latest is not None and latest.id != eid:
                typer.secho(
                    f"entity '{eid}' is already superseded by '{latest.id}'; "
                    "merge the latest entity in the chain "
                    f"(use `amanuensis map entity show {eid}`)",
                    err=True,
                )
                raise typer.Exit(code=1)

    # --- Build EntitySupersede record(s) for whichever ids != canonical -
    now = datetime.now(UTC)
    agent = AgentAttribution(kind="human", identifier=actor, role="human_supervisor")
    role_attr = RoleAttribution(agent=agent, activity="merged", at=now)

    to_supersede: list[str] = [eid for eid in (a_id, b_id) if eid != canonical]

    supersedes_to_write: list[EntitySupersede] = []
    provs_to_write: list[ProvenanceRecord] = []

    for superseded_id in to_supersede:
        es_draft = EntitySupersede(
            id="t-" + "0" * 16,
            kind="entity",
            superseded_entity_id=superseded_id,
            replacement_entity_id=canonical,
            reason=reason,
            provenance_id="p-" + "0" * 16,
            role_attributions=[role_attr],
            schema_version=1,
        )
        es_id = compute_id(es_draft)

        prov_draft = ProvenanceRecord(
            id="p-" + "0" * 16,
            entity_type="entity-supersede",
            entity_id=es_id,
            activity="entity-merge",
            activity_started_at=now,
            activity_ended_at=now,
            used_entity_ids=[],
            was_attributed_to=agent,
            was_influenced_by=[],
            schema_version=1,
        )
        prov_id = compute_id(prov_draft)
        prov = prov_draft.model_copy(update={"id": prov_id})
        es = es_draft.model_copy(update={"id": es_id, "provenance_id": prov_id})
        supersedes_to_write.append(es)
        provs_to_write.append(prov)

    # --- Dry-run: print what would be written --------------------------
    if dry_run:
        typer.echo("[dry-run] No writes will be made.")
        for es, prov in zip(supersedes_to_write, provs_to_write, strict=True):
            typer.echo(f"Would write EntitySupersede: {es.id}")
            typer.echo(f"  superseded_entity_id: {es.superseded_entity_id}")
            typer.echo(f"  replacement_entity_id: {es.replacement_entity_id}")
            typer.echo(f"  reason: {es.reason}")
            typer.echo(f"Would write ProvenanceRecord: {prov.id}")
        typer.echo(f"Resulting canonical chain: {canonical}")
        return

    # --- Mutating path: acquire flock and write ------------------------
    try:
        with acquire_workspace_lock(workspace_path, timeout=5.0):
            substrate_changes: list[str] = []

            for es, prov in zip(supersedes_to_write, provs_to_write, strict=True):
                # Write prov first, then the EntitySupersede.
                prov_path = substrate.mappings_provenance_path(prov.id)
                atomic_write_text(prov_path, serialize_yaml(prov))
                substrate_changes.append(str(prov_path.relative_to(workspace_path)))

                substrate.add_entity_supersede(es)
                es_path = substrate.supersede_path(es.id)
                substrate_changes.append(str(es_path.relative_to(workspace_path)))

            # Compute inputs hash for the replay-log entry.
            inputs_payload = json.dumps(
                {
                    "a_id": a_id,
                    "b_id": b_id,
                    "canonical_id": canonical,
                    "reason": reason,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            inputs_hash = hashlib.sha256(inputs_payload).hexdigest()

            actor_attr = AgentAttribution(kind="human", identifier=actor, role="human_supervisor")
            ReplayLog.for_mappings(workspace_path).append(
                actor=actor_attr,
                activity="entity-merge",
                inputs_hash=inputs_hash,
                outputs_hash=inputs_hash,
                cache_hit=False,
                substrate_changes=substrate_changes,
                duration_seconds=0.0,
                _lock_held=True,
            )

    except WorkspaceLockTimeout as exc:
        typer.secho(
            "workspace flock held by another process — wait or release .amanuensis-lock",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    for es in supersedes_to_write:
        typer.echo(
            f"Merged entity '{es.superseded_entity_id}' -> '{canonical}'. "
            f"EntitySupersede id: {es.id}"
        )


# ---------------------------------------------------------------------------
# resolution sub-commands (T7.7, T7.8)
# ---------------------------------------------------------------------------


@resolution_app.command("show")
@require_marker
def resolution_show_command(
    resolution_id: Annotated[
        str,
        typer.Argument(help="Resolution id (e.g. j-<hash>)."),
    ],
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Print a resolution record's YAML + supersede chain + latest-for-triple (read-only; T7.7)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    from amanuensis.fs._errors import SubstrateNotFound

    try:
        r = substrate.get_resolution(resolution_id)
    except SubstrateNotFound as exc:
        typer.secho(
            f"resolution '{resolution_id}' not found in mappings/resolutions/",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    # Print raw YAML body verbatim.
    typer.echo(substrate.resolution_path(resolution_id).read_text(encoding="utf-8"), nl=False)

    # Supersede chain section.
    typer.echo("\n## Supersede chain")
    chain_entries: list[str] = []
    for record in substrate.list_supersedes(kind="resolution"):
        if not isinstance(record, ResolutionSupersede):
            continue
        if record.superseded_resolution_id == resolution_id:
            chain_entries.append(
                f"superseded by {record.id} → resolution {record.replacement_resolution_id}"
                f" (reason: {record.reason})"
            )
        if record.replacement_resolution_id == resolution_id:
            chain_entries.append(
                f"supersedes {record.superseded_resolution_id} (reason: {record.reason})"
            )
    if chain_entries:
        for entry in chain_entries:
            typer.echo(entry)
    else:
        typer.echo("(no supersede chain)")

    # Latest-for-triple section.
    typer.echo("\n## Latest for triple")
    latest = substrate.latest_resolution_for(r.source_id, r.atom_id, r.operand_index)
    if latest is not None and latest.id == resolution_id:
        typer.echo("(this resolution is the latest for its triple)")
    else:
        latest_id = latest.id if latest is not None else "(none)"
        typer.echo(
            f"Latest for triple ({r.source_id}, {r.atom_id}, {r.operand_index}): {latest_id}"
        )


@resolution_app.command("supersede")
@require_marker
def resolution_supersede_command(
    old_id: Annotated[
        str,
        typer.Argument(help="Resolution id to supersede (e.g. j-<hash>)."),
    ],
    new_entity: Annotated[
        str,
        typer.Option(
            "--new-entity",
            help="Entity id the new resolution will point at.",
        ),
    ],
    reason: Annotated[
        str,
        typer.Option(
            "--reason",
            help="Human-readable reason for the correction.",
        ),
    ],
    actor: Annotated[
        str,
        typer.Option(
            "--actor",
            help="Identifier of the human performing the correction.",
        ),
    ] = "cli",
    confidence: Annotated[
        str,
        typer.Option(
            "--confidence",
            help="Confidence level for the new resolution (high/medium/low).",
        ),
    ] = "high",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Print what would be written without making any changes.",
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
    """Supersede a resolution, writing a new Resolution + ResolutionSupersede record (T7.8).

    Acquires workspace flock for the duration of the write.
    Supports --dry-run (no writes).
    """
    from typing import Literal, cast

    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    from amanuensis.dispatch.reconcile import (
        _stable_role_attribution_at,  # pyright: ignore[reportPrivateUsage]
    )
    from amanuensis.fs._errors import SubstrateNotFound

    # Validate confidence value.
    if confidence not in {"high", "medium", "low"}:
        typer.secho(
            f"--confidence must be one of high/medium/low, got '{confidence}'",
            err=True,
        )
        raise typer.Exit(code=2)
    confidence_lit = cast("Literal['high', 'medium', 'low']", confidence)

    # Validate old-id exists.
    try:
        old_res = substrate.get_resolution(old_id)
    except SubstrateNotFound as exc:
        typer.secho(
            f"resolution '{old_id}' not found in mappings/resolutions/",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    # Validate new-entity exists.
    if not substrate.entity_path(new_entity).is_file():
        typer.secho(
            f"entity '{new_entity}' not found in mappings/entities/",
            err=True,
        )
        raise typer.Exit(code=1)

    # Validate old-id is the latest for its triple.
    latest = substrate.latest_resolution_for(
        old_res.source_id, old_res.atom_id, old_res.operand_index
    )
    if latest is not None and latest.id != old_id:
        typer.secho(
            f"resolution '{old_id}' is already superseded by '{latest.id}'; "
            "supersede the latest in the chain",
            err=True,
        )
        raise typer.Exit(code=1)

    now = datetime.now(UTC)
    agent = AgentAttribution(kind="human", identifier=actor, role="human_supervisor")

    # Derive stable_at for the new resolution's role_attribution.
    stable_hash_input = old_id + new_entity + reason
    stable_at = _stable_role_attribution_at(stable_hash_input)

    # Build new Resolution.
    new_res_draft = Resolution(
        id="j-" + "0" * 16,
        source_id=old_res.source_id,
        atom_id=old_res.atom_id,
        operand_index=old_res.operand_index,
        entity_id=new_entity,
        confidence=confidence_lit,
        basis="supervisor correction via amanuensis map resolution supersede",
        provenance_id="p-" + "0" * 16,
        role_attributions=[RoleAttribution(agent=agent, activity="supersede", at=stable_at)],
        schema_version=1,
    )
    new_res_id = compute_id(new_res_draft)

    # Build ProvenanceRecord for the new Resolution.
    res_prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="resolution",
        entity_id=new_res_id,
        activity="resolution-supersede",
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=[new_entity],
        was_attributed_to=agent,
        was_influenced_by=[],
        schema_version=1,
    )
    res_prov_id = compute_id(res_prov_draft)
    res_prov = res_prov_draft.model_copy(update={"id": res_prov_id})
    new_res = new_res_draft.model_copy(update={"id": new_res_id, "provenance_id": res_prov_id})

    # Build ResolutionSupersede.
    rs_draft = ResolutionSupersede(
        id="s-" + "0" * 16,
        superseded_resolution_id=old_id,
        replacement_resolution_id=new_res_id,
        reason=reason,
        provenance_id="p-" + "0" * 16,
        role_attributions=[RoleAttribution(agent=agent, activity="superseded", at=now)],
        schema_version=1,
    )
    rs_id = compute_id(rs_draft)

    # Build ProvenanceRecord for the ResolutionSupersede.
    rs_prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="resolution-supersede",
        entity_id=rs_id,
        activity="resolution-supersede",
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=[],
        was_attributed_to=agent,
        was_influenced_by=[],
        schema_version=1,
    )
    rs_prov_id = compute_id(rs_prov_draft)
    rs_prov = rs_prov_draft.model_copy(update={"id": rs_prov_id})
    rs = rs_draft.model_copy(update={"id": rs_id, "provenance_id": rs_prov_id})

    # --- Dry-run: print what would be written --------------------------
    if dry_run:
        typer.echo("[dry-run] No writes will be made.")
        typer.echo(f"Would write new Resolution: {new_res_id}")
        typer.echo(serialize_yaml(new_res))
        typer.echo(f"Would write ResolutionSupersede: {rs_id}")
        typer.echo(serialize_yaml(rs))
        latest_after = new_res_id  # the new resolution would be the latest
        typer.echo(
            f"Resulting latest for triple ({old_res.source_id}, {old_res.atom_id}, "
            f"{old_res.operand_index}): {latest_after}"
        )
        return

    # --- Mutating path: acquire flock and write ------------------------
    try:
        with acquire_workspace_lock(workspace_path, timeout=5.0):
            substrate_changes: list[str] = []

            # Write the ResolutionSupersede FIRST so that add_resolution's
            # duplicate-triple guard (latest_resolution_for) sees the old
            # resolution as already superseded and allows the new one.
            rs_prov_path = substrate.mappings_provenance_path(rs_prov.id)
            atomic_write_text(rs_prov_path, serialize_yaml(rs_prov))
            substrate_changes.append(str(rs_prov_path.relative_to(workspace_path)))

            substrate.add_resolution_supersede(rs)
            rs_path = substrate.supersede_path(rs.id)
            substrate_changes.append(str(rs_path.relative_to(workspace_path)))

            # Now write the new Resolution (the supersede chain is in place).
            res_prov_path = substrate.mappings_provenance_path(res_prov.id)
            atomic_write_text(res_prov_path, serialize_yaml(res_prov))
            substrate_changes.append(str(res_prov_path.relative_to(workspace_path)))

            substrate.add_resolution(new_res)
            new_res_path = substrate.resolution_path(new_res.id)
            substrate_changes.append(str(new_res_path.relative_to(workspace_path)))

            # Compute inputs_hash for the replay-log entry.
            inputs_payload = json.dumps(
                {
                    "confidence": confidence,
                    "new_entity": new_entity,
                    "old_id": old_id,
                    "reason": reason,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            inputs_hash = hashlib.sha256(inputs_payload).hexdigest()

            actor_attr = AgentAttribution(kind="human", identifier=actor, role="human_supervisor")
            ReplayLog.for_mappings(workspace_path).append(
                actor=actor_attr,
                activity="resolution-supersede",
                inputs_hash=inputs_hash,
                outputs_hash=inputs_hash,
                cache_hit=False,
                substrate_changes=substrate_changes,
                duration_seconds=0.0,
                _lock_held=True,
            )

    except WorkspaceLockTimeout as exc:
        typer.secho(
            "workspace flock held by another process — wait or release .amanuensis-lock",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    typer.echo(
        f"Superseded resolution '{old_id}' → '{new_res_id}' (entity: {new_entity}). "
        f"ResolutionSupersede id: {rs_id}"
    )


# ---------------------------------------------------------------------------
# vocabulary sub-commands (T7.9, T7.10)
# ---------------------------------------------------------------------------


@vocabulary_app.command("show")
@require_marker
def vocabulary_show_command(
    archived: Annotated[
        str | None,
        typer.Option(
            "--archived",
            help="Show an archived snapshot by its id (SHA-256 truncated to 16 hex chars).",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Print the active entity-kind vocabulary snapshot (read-only; T7.9).

    With --archived <id>, print the archived snapshot instead.
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    if archived is not None:
        # Print archived snapshot.
        archive_path = substrate.archived_entity_vocabulary_path(archived)
        if not archive_path.is_file():
            typer.secho(
                f"archived snapshot '{archived}' not found at {archive_path}",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo(archive_path.read_text(encoding="utf-8"), nl=False)
        return

    # Print active snapshot.
    snapshot_path = substrate.entity_vocabulary_snapshot_path()
    if not snapshot_path.is_file():
        typer.secho(
            f"entity-vocabulary snapshot not found at {snapshot_path}; "
            "run `amanuensis map` to pin one",
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo(snapshot_path.read_text(encoding="utf-8"), nl=False)


@vocabulary_app.command("snapshot")
@require_marker
def vocabulary_snapshot_command(
    extend: Annotated[
        bool,
        typer.Option(
            "--extend",
            help="Archive the current snapshot and write a new one from the template.",
        ),
    ] = False,
    template: Annotated[
        Path | None,
        typer.Option(
            "--template",
            help="Path to the entity-vocabulary YAML template. Defaults to bundled generic.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Print what would be written without making any changes.",
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
    """Pin or extend the entity-kind vocabulary snapshot (T7.10).

    Without --extend: write the vocabulary from the template as the active
    snapshot.  Fails if a snapshot already exists with different content
    (use --extend to evolve it).

    With --extend: archive the current snapshot and write the template as
    the new active snapshot.

    Supports --dry-run (no writes performed).
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    # Resolve template path.
    if template is not None:
        template_path: Path = template
    else:
        template_path = (
            Path(__file__).resolve().parents[3] / "vocabularies" / "generic" / "entity-kinds.yaml"
        )

    if not template_path.is_file():
        typer.secho(
            f"entity-vocabulary template not found at {template_path}",
            err=True,
        )
        raise typer.Exit(code=1)

    # Load and validate the vocabulary.
    try:
        vocab = load_entity_vocabulary(template_path)
    except EntityVocabularyError as exc:
        fatal(f"entity-vocabulary template invalid: {exc}")
        return  # unreachable; fatal raises

    # Compute inputs hash (SHA-256 of canonical template bytes).
    template_bytes = template_path.read_bytes()
    inputs_hash = hashlib.sha256(template_bytes).hexdigest()

    snapshot_path = substrate.entity_vocabulary_snapshot_path()

    # ------------------------------------------------------------------
    # Dry-run branch
    # ------------------------------------------------------------------
    if dry_run:
        if not extend:
            # Without --extend.
            if snapshot_path.is_file():
                existing_bytes = snapshot_path.read_bytes()
                import yaml as _yaml

                new_serialized = _yaml.safe_dump(
                    vocab.model_dump(), sort_keys=False, default_flow_style=False
                )
                if existing_bytes == new_serialized.encode():
                    typer.echo("snapshot already pinned with identical content; would be no-op")
                else:
                    typer.echo(
                        "would FAIL: snapshot already pinned with different content; use --extend"
                    )
            else:
                typer.echo(f"would write snapshot to {snapshot_path}")
                import yaml as _yaml

                typer.echo(
                    _yaml.safe_dump(vocab.model_dump(), sort_keys=False, default_flow_style=False),
                    nl=False,
                )
        else:
            # With --extend.
            if not snapshot_path.is_file():
                typer.echo(
                    "would FAIL: no snapshot to extend; "
                    "use 'vocabulary snapshot' without --extend first"
                )
            else:
                existing_bytes = snapshot_path.read_bytes()
                archived_id_preview = hashlib.sha256(existing_bytes).hexdigest()[:16]
                archive_path = substrate.archived_entity_vocabulary_path(archived_id_preview)
                typer.echo(f"would archive current snapshot as {archived_id_preview}")
                typer.echo(f"would write new snapshot to {snapshot_path}")
                # Short diff summary: count of kinds before/after.
                from amanuensis.vocabulary.entity_registry import load_entity_vocabulary as _lev

                try:
                    old_vocab = _lev(snapshot_path)
                    old_count = len(old_vocab.kinds)
                except EntityVocabularyError:
                    old_count = 0
                new_count = len(vocab.kinds)
                typer.echo(f"kinds: {old_count} → {new_count}")
                _ = archive_path  # suppress vulture
        return

    # ------------------------------------------------------------------
    # Mutating branch: acquire workspace flock.
    # ------------------------------------------------------------------
    from amanuensis.fs._errors import MappingVocabularyAlreadyPinned

    try:
        with acquire_workspace_lock(workspace_path, timeout=5.0):
            if not extend:
                # Pin without extend.
                try:
                    substrate.snapshot_entity_vocabulary(vocab)
                except MappingVocabularyAlreadyPinned as exc:
                    typer.secho(
                        "entity-vocabulary snapshot already pinned; use --extend to evolve it",
                        err=True,
                    )
                    raise typer.Exit(code=1) from exc

                actor = AgentAttribution(kind="human", identifier="cli", role="human_supervisor")
                ReplayLog.for_mappings(workspace_path).append(
                    actor=actor,
                    activity="mapping-vocabulary-snapshot-pinned",
                    inputs_hash=inputs_hash,
                    outputs_hash=inputs_hash,
                    cache_hit=False,
                    substrate_changes=[
                        str(snapshot_path.relative_to(workspace_path)),
                    ],
                    duration_seconds=0.0,
                    _lock_held=True,
                )
                rel = snapshot_path.relative_to(workspace_path)
                typer.echo(f"Pinned entity-vocabulary snapshot at {rel}")

            else:
                # Extend: archive current, write new.
                try:
                    archived_id = substrate.extend_entity_vocabulary_snapshot(vocab)
                except Exception as exc:
                    from amanuensis.fs._errors import SubstrateNotFound

                    if isinstance(exc, SubstrateNotFound):
                        typer.secho(
                            "no snapshot to extend; "
                            "use 'vocabulary snapshot' without --extend first",
                            err=True,
                        )
                        raise typer.Exit(code=1) from exc
                    raise

                archive_path = substrate.archived_entity_vocabulary_path(archived_id)
                actor = AgentAttribution(kind="human", identifier="cli", role="human_supervisor")
                ReplayLog.for_mappings(workspace_path).append(
                    actor=actor,
                    activity="mapping-vocabulary-snapshot-extended",
                    inputs_hash=inputs_hash,
                    outputs_hash=inputs_hash,
                    cache_hit=False,
                    substrate_changes=[
                        str(archive_path.relative_to(workspace_path)),
                        str(snapshot_path.relative_to(workspace_path)),
                    ],
                    duration_seconds=0.0,
                    _lock_held=True,
                )
                typer.echo(
                    f"Extended entity-vocabulary snapshot; archived previous as {archived_id}"
                )

    except WorkspaceLockTimeout as exc:
        typer.secho(
            "workspace flock held by another process — wait or release .amanuensis-lock",
            err=True,
        )
        raise typer.Exit(code=2) from exc


# ---------------------------------------------------------------------------
# Phase 2b M7: cross-doc relation sub-commands (T7.1, T7.2, T7.3)
# ---------------------------------------------------------------------------


def _format_cross_doc_relation_line(rel: Any) -> str:
    """Render a single ``map relation list`` line.

    Mirrors the conventions of ``entity_list_command``: id-prefixed,
    space-separated key=value pairs for grep-ability, with the directed
    endpoint pair rendered in arrow form for human readability.
    """
    shared = ",".join(rel.shared_entities)
    return (
        f"{rel.id}  kind={rel.kind}  "
        f"{rel.from_source_id}/{rel.from_atom_id} -> "
        f"{rel.to_source_id}/{rel.to_atom_id}  "
        f"[shared: {shared}]"
    )


@relation_app.command("list")
@require_marker
def relation_list_command(
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            help="Filter to relations of the given kind (supports/attacks/undercuts).",
        ),
    ] = None,
    from_source: Annotated[
        str | None,
        typer.Option(
            "--from-source",
            help="Filter to relations originating from this source id.",
        ),
    ] = None,
    to_source: Annotated[
        str | None,
        typer.Option(
            "--to-source",
            help="Filter to relations terminating at this source id.",
        ),
    ] = None,
    touching_source: Annotated[
        str | None,
        typer.Option(
            "--touching-source",
            help="Filter to relations where the given source appears at either endpoint.",
        ),
    ] = None,
    shared_entity: Annotated[
        str | None,
        typer.Option(
            "--shared-entity",
            help="Filter to relations whose shared_entities list includes this entity id.",
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            help="Maximum number of relations to render (after filtering).",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """List cross-doc relations in the workspace (read-only; T7.1).

    Filters compose with AND semantics. The render line mirrors
    ``entity list`` — id-prefixed plus space-separated key=value pairs
    and the directed endpoint pair rendered in arrow form.
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    # Validate ``--kind`` against the known cross-doc relation kinds.
    if kind is not None and kind not in {"supports", "attacks", "undercuts"}:
        typer.secho(
            f"--kind must be one of supports/attacks/undercuts, got '{kind}'",
            err=True,
        )
        raise typer.Exit(code=2)

    # Validate ``--limit`` (Typer accepts negatives at parse time).
    if limit is not None and limit < 0:
        typer.secho(
            f"--limit must be a non-negative integer, got {limit}",
            err=True,
        )
        raise typer.Exit(code=2)

    relations = list(
        substrate.list_cross_doc_relations(
            kind=kind,  # type: ignore[arg-type]
            from_source=from_source,
            to_source=to_source,
            touching_source=touching_source,
            shared_entity=shared_entity,
        )
    )

    # ``list_cross_doc_relations`` already iterates ``sorted(...)`` by
    # filesystem path (lexicographic by id), giving us a deterministic
    # output order without an extra sort.
    if limit is not None:
        relations = relations[:limit]

    for rel in relations:
        typer.echo(_format_cross_doc_relation_line(rel))


@relation_app.command("show")
@require_marker
def relation_show_command(
    relation_id: Annotated[
        str,
        typer.Argument(help="CrossDocRelation id (e.g. x-<hash>)."),
    ],
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Print a cross-doc relation's detail view (read-only; T7.2).

    Sections rendered (mirrors ``entity show`` / ``resolution show``):

    - Raw on-disk YAML (id, endpoints, kind, warrant, warrant_basis,
      warrant_defensibility, confidence, shared_entities, provenance_id).
    - Supersede chain (forward + backward over
      ``CrossDocRelationSupersede`` records).
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    path = substrate.cross_doc_relation_path(relation_id)
    if not path.is_file():
        typer.secho(
            f"cross-doc relation '{relation_id}' not found in mappings/relations/",
            err=True,
        )
        raise typer.Exit(code=1)

    # Raw YAML body verbatim — keeps the supervisor view aligned with
    # what the substrate has on disk.
    typer.echo(path.read_text(encoding="utf-8"), nl=False)

    # Supersede chain section.
    #
    # Phase 2b cleanup-1 consolidated the cross-doc-relation supersede
    # walk into ``Substrate.list_supersedes(kind="cross-doc-relation")``.
    # The CLI renders both forward (``this -> X``) and backward
    # (``Y -> this``) edges to mirror ``latest_cross_doc_relation_for``.
    typer.echo("\n## Supersede chain")
    chain_entries: list[str] = []
    for record in substrate.list_supersedes(kind="cross-doc-relation"):
        if not isinstance(record, CrossDocRelationSupersede):
            continue  # type-narrowing for Pyright; runtime is already filtered
        if record.supersedes_id == relation_id:
            chain_entries.append(
                f"superseded by {record.id} -> relation {record.superseded_by_id}"
                f" (reason: {record.reason})"
            )
        if record.superseded_by_id == relation_id:
            chain_entries.append(f"supersedes {record.supersedes_id} (reason: {record.reason})")
    if chain_entries:
        for entry in chain_entries:
            typer.echo(entry)
    else:
        typer.echo("(no supersede chain)")

    # Latest-for-chain line (mirrors ``resolution show`` semantics).
    latest = substrate.latest_cross_doc_relation_for(relation_id)
    if latest is not None and latest.id == relation_id:
        typer.echo("(this relation is the latest in its chain)")
    elif latest is not None:
        typer.echo(f"Latest in chain: {latest.id}")


@relation_app.command("supersede")
@require_marker
def relation_supersede_command(
    old_id: Annotated[
        str,
        typer.Argument(help="CrossDocRelation id to supersede (e.g. x-<hash>)."),
    ],
    new_id: Annotated[
        str,
        typer.Argument(help="Replacement CrossDocRelation id (must already exist)."),
    ],
    reason: Annotated[
        str,
        typer.Option(
            "--reason",
            help="Human-readable reason for the correction (recorded in the supersede).",
        ),
    ],
    actor: Annotated[
        str,
        typer.Option(
            "--actor",
            help="Identifier of the human performing the correction.",
        ),
    ] = "cli",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Print what would be written without making any changes.",
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
    """Supersede a cross-doc relation with a replacement record (T7.3).

    Mirrors ``map entity merge`` for the flock + supervisor-PROV pattern:

    1. Validate that both ``<old-id>`` and ``<new-id>`` exist as
       ``CrossDocRelation`` records on disk.
    2. Refuse to write if ``<old-id>`` is already superseded (the chain
       walker resolves it past itself).
    3. Build a fresh ``CrossDocRelationSupersede`` + matching
       ``ProvenanceRecord`` for the supervisor action.
    4. Acquire the workspace flock and write the prov record first, then
       the supersede record. Append a mappings replay-log entry.

    The mutating path acquires the workspace flock for the duration of
    the write; the validation reads above run without the flock (they
    only touch path existence + an immutable supersede chain).
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    # --- Validate both ids resolve to on-disk CrossDocRelations -------
    if not substrate.cross_doc_relation_path(old_id).is_file():
        typer.secho(
            f"cross-doc relation '{old_id}' not found in mappings/relations/",
            err=True,
        )
        raise typer.Exit(code=1)
    if not substrate.cross_doc_relation_path(new_id).is_file():
        typer.secho(
            f"cross-doc relation '{new_id}' not found in mappings/relations/",
            err=True,
        )
        raise typer.Exit(code=1)

    # --- Refuse if ``old_id`` is already superseded -------------------
    latest = substrate.latest_cross_doc_relation_for(old_id)
    if latest is not None and latest.id != old_id:
        typer.secho(
            f"cross-doc relation '{old_id}' is already superseded by '{latest.id}'; "
            "supersede the latest in the chain",
            err=True,
        )
        raise typer.Exit(code=1)

    now = datetime.now(UTC)
    agent = AgentAttribution(kind="human", identifier=actor, role="human_supervisor")
    role_attr = RoleAttribution(agent=agent, activity="superseded", at=now)

    # --- Build the CrossDocRelationSupersede + matching PROV ----------
    #
    # Pattern mirrors ``entity_merge_command``: two compute_id passes
    # because both the supersede record and its PROV record cross-
    # reference each other's content hash.
    sup_draft = CrossDocRelationSupersede(
        id="v-" + "0" * 16,
        supersedes_id=old_id,
        superseded_by_id=new_id,
        kind="cross-doc-relation",
        reason=reason,
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attr],
        at=now,
        schema_version=1,
    )
    sup_id = compute_id(sup_draft)

    prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="cross-doc-relation-supersede",
        entity_id=sup_id,
        activity="cross-doc-relation-supersede",
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=[],
        was_attributed_to=agent,
        was_influenced_by=[],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov = prov_draft.model_copy(update={"id": prov_id})
    sup = sup_draft.model_copy(update={"id": sup_id, "provenance_id": prov_id})

    # --- Dry-run: print what would be written -------------------------
    if dry_run:
        typer.echo("[dry-run] No writes will be made.")
        typer.echo(f"Would write CrossDocRelationSupersede: {sup.id}")
        typer.echo(f"  supersedes_id:    {sup.supersedes_id}")
        typer.echo(f"  superseded_by_id: {sup.superseded_by_id}")
        typer.echo(f"  reason:           {sup.reason}")
        typer.echo(f"Would write ProvenanceRecord: {prov.id}")
        typer.echo(f"Resulting latest in chain for {old_id}: {new_id}")
        return

    # --- Mutating path: acquire flock and write -----------------------
    try:
        with acquire_workspace_lock(workspace_path, timeout=5.0):
            substrate_changes: list[str] = []

            # Write the PROV record first so the supersede record's
            # provenance pointer always points at an existing file.
            prov_path = substrate.mappings_provenance_path(prov.id)
            atomic_write_text(prov_path, serialize_yaml(prov))
            substrate_changes.append(str(prov_path.relative_to(workspace_path)))

            substrate.add_cross_doc_relation_supersede(sup)
            sup_path = substrate.supersede_path(sup.id)
            substrate_changes.append(str(sup_path.relative_to(workspace_path)))

            # Inputs hash for the replay-log entry — canonicalise the
            # tuple (old_id, new_id, reason) so byte-equivalent inputs
            # produce byte-equivalent hashes.
            inputs_payload = json.dumps(
                {
                    "new_id": new_id,
                    "old_id": old_id,
                    "reason": reason,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            inputs_hash = hashlib.sha256(inputs_payload).hexdigest()

            actor_attr = AgentAttribution(kind="human", identifier=actor, role="human_supervisor")
            ReplayLog.for_mappings(workspace_path).append(
                actor=actor_attr,
                activity="cross-doc-relation-supersede",
                inputs_hash=inputs_hash,
                outputs_hash=inputs_hash,
                cache_hit=False,
                substrate_changes=substrate_changes,
                duration_seconds=0.0,
                _lock_held=True,
            )

    except WorkspaceLockTimeout as exc:
        typer.secho(
            "workspace flock held by another process — wait or release .amanuensis-lock",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    typer.echo(
        f"Superseded cross-doc relation '{old_id}' -> '{new_id}'. "
        f"CrossDocRelationSupersede id: {sup.id}"
    )


# ---------------------------------------------------------------------------
# Phase 2c M9: probandum sub-commands (T9.1 / T9.2 / T9.3 / T9.4 / T9.5 / T9.6)
# ---------------------------------------------------------------------------


@probandum_app.command("add")
@require_marker
def probandum_add_command(
    statement: Annotated[
        str,
        typer.Argument(help="The probandum statement (a full proposition)."),
    ],
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help="One of ultimate / penultimate / interim (ACH discipline for non-ultimate).",
        ),
    ],
    scheme: Annotated[
        str,
        typer.Option(
            "--scheme",
            help="Walton-scheme id (must be present in the pinned snapshot — INV-18).",
        ),
    ],
    alternative: Annotated[
        list[str] | None,
        typer.Option(
            "--alternative",
            help=(
                "An alternative considered (repeatable). Required for "
                "penultimate / interim probanda (ACH discipline)."
            ),
        ),
    ] = None,
    confidence: Annotated[
        str,
        typer.Option(
            "--confidence",
            help="Confidence level for the probandum (high / medium / low).",
        ),
    ] = "medium",
    actor: Annotated[
        str,
        typer.Option(
            "--actor",
            help="Identifier of the human authoring the probandum.",
        ),
    ] = "cli",
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Add a Probandum (Phase 2c hierarchize node) to the workspace (T9.1).

    Marker preflight (INV-1) runs first. The write is wrapped in the
    workspace flock; the substrate's ``add_probandum`` enforces the
    ACH-alternatives gate (INV-19), the Walton-scheme closed-vocabulary
    gate (INV-18), id discipline, and INV-13 immutability.
    """
    from typing import Literal, cast

    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    # Validate kind + confidence enums upfront (Typer's enum support is
    # not used here so the error UX matches the rest of this module).
    if kind not in {"ultimate", "penultimate", "interim"}:
        typer.secho(
            f"--kind must be one of ultimate/penultimate/interim, got '{kind}'",
            err=True,
        )
        raise typer.Exit(code=2)
    if confidence not in {"high", "medium", "low"}:
        typer.secho(
            f"--confidence must be one of high/medium/low, got '{confidence}'",
            err=True,
        )
        raise typer.Exit(code=2)
    kind_lit = cast("Literal['ultimate', 'penultimate', 'interim']", kind)
    confidence_lit = cast("Literal['high', 'medium', 'low']", confidence)

    alternatives = list(alternative) if alternative else []

    now = datetime.now(UTC)
    agent = AgentAttribution(kind="human", identifier=actor, role="human_supervisor")
    role_attr = RoleAttribution(agent=agent, activity="proposed", at=now)

    # Build the Probandum + matching ProvenanceRecord via the two-pass
    # compute_id pattern (mirrors entity_merge_command). provenance_id
    # is volatile for the probandum's canonical hash, so the id is
    # stable across the pass that wires the prov_id in.
    prob_draft = Probandum(
        id="p-" + "0" * 16,
        statement=statement,
        kind=kind_lit,
        scheme=scheme,
        alternatives_considered=alternatives,
        confidence=confidence_lit,
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attr],
        schema_version=1,
    )
    prob_id = compute_id(prob_draft)

    prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="probandum",
        entity_id=prob_id,
        activity="probandum-add",
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=[],
        was_attributed_to=agent,
        was_influenced_by=[],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov = prov_draft.model_copy(update={"id": prov_id})
    prob = prob_draft.model_copy(update={"id": prob_id, "provenance_id": prov_id})

    # --- Mutating path: acquire flock and write ------------------------
    from amanuensis.fs._errors import (
        AchAlternativesGateViolation,
        SubstrateNotFound,
        WaltonSchemeGateViolation,
    )

    try:
        with acquire_workspace_lock(workspace_path, timeout=5.0):
            substrate_changes: list[str] = []
            prov_path = substrate.mappings_provenance_path(prov.id)
            atomic_write_text(prov_path, serialize_yaml(prov))
            substrate_changes.append(str(prov_path.relative_to(workspace_path)))

            try:
                prob_path = substrate.add_probandum(prob)
            except AchAlternativesGateViolation as exc:
                typer.secho(str(exc), err=True)
                raise typer.Exit(code=1) from exc
            except WaltonSchemeGateViolation as exc:
                typer.secho(str(exc), err=True)
                raise typer.Exit(code=1) from exc
            except SubstrateNotFound as exc:
                typer.secho(str(exc), err=True)
                raise typer.Exit(code=1) from exc
            substrate_changes.append(str(prob_path.relative_to(workspace_path)))

            inputs_payload = json.dumps(
                {
                    "alternatives": sorted(alternatives),
                    "confidence": confidence,
                    "kind": kind,
                    "scheme": scheme,
                    "statement": statement,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            inputs_hash = hashlib.sha256(inputs_payload).hexdigest()

            actor_attr = AgentAttribution(kind="human", identifier=actor, role="human_supervisor")
            ReplayLog.for_mappings(workspace_path).append(
                actor=actor_attr,
                activity="probandum-add",
                inputs_hash=inputs_hash,
                outputs_hash=inputs_hash,
                cache_hit=False,
                substrate_changes=substrate_changes,
                duration_seconds=0.0,
                _lock_held=True,
            )

    except WorkspaceLockTimeout as exc:
        typer.secho(
            "workspace flock held by another process — wait or release .amanuensis-lock",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    typer.echo(prob.id)


def _format_probandum_line(p: Probandum) -> str:
    """Render a single ``map probandum list`` line.

    Mirrors ``_format_cross_doc_relation_line``: id-prefixed,
    space-separated key=value pairs for grep-ability, with a truncated
    statement excerpt so wide statements do not blow up the terminal.
    """
    excerpt = p.statement.strip().splitlines()[0] if p.statement.strip() else ""
    if len(excerpt) > 80:
        excerpt = excerpt[:77] + "..."
    return f"{p.id}  kind={p.kind}  scheme={p.scheme}  {excerpt}"


@probandum_app.command("list")
@require_marker
def probandum_list_command(
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            help="Filter to probanda of the given kind (ultimate / penultimate / interim).",
        ),
    ] = None,
    scheme: Annotated[
        str | None,
        typer.Option(
            "--scheme",
            help="Filter to probanda using the given Walton-scheme id.",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """List Probandum records in the workspace (read-only; T9.2).

    Filters compose with AND semantics. Render order is lexicographic
    by id (the substrate's natural directory walk).
    """
    from typing import Literal, cast

    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    if kind is not None and kind not in {"ultimate", "penultimate", "interim"}:
        typer.secho(
            f"--kind must be one of ultimate/penultimate/interim, got '{kind}'",
            err=True,
        )
        raise typer.Exit(code=2)

    kind_lit = (
        cast("Literal['ultimate', 'penultimate', 'interim']", kind) if kind is not None else None
    )
    for p in substrate.list_probanda(kind=kind_lit, scheme=scheme):
        typer.echo(_format_probandum_line(p))
