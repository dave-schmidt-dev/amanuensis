"""``amanuensis map`` — entity resolution registry (Phase 2a).

Commands
--------
- ``amanuensis map [OPTIONS]`` (orchestrator callback) — run the full
  map warp-plan cycle; enqueues the map-resolve role.  T7.2.
- ``amanuensis map status`` — read-only workspace summary.  T7.4.
- ``amanuensis map entity {list,show,merge}`` — entity CRUD; T7.5-T7.6.
- ``amanuensis map resolution {show,supersede}`` — resolution inspection; T7.8-T7.9 stubs.
- ``amanuensis map vocabulary {show,snapshot}`` — vocabulary registry; T7.10 stubs.

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

from amanuensis.dispatch.queue import enqueue
from amanuensis.fs import ReplayLog, Substrate, WorkspaceLockTimeout, acquire_workspace_lock
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import serialize_yaml
from amanuensis.llm.queue import DispatchQueueEntry
from amanuensis.schemas import (
    AgentAttribution,
    EntitySupersede,
    ProvenanceRecord,
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
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Run the full map warp-plan cycle (T7.2).

    Enqueues the map-resolve role for dispatch.  Run
    ``amanuensis dispatch --once`` afterwards to drive it.

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
    # ------------------------------------------------------------------
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
    # Acquire workspace flock (5 s timeout).
    # ------------------------------------------------------------------
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
# resolution sub-commands (stubs — T7.8-T7.9)
# ---------------------------------------------------------------------------


@resolution_app.command("show")
def resolution_show_command() -> None:
    """Show a resolution record (stub; T7.8)."""
    typer.echo("TODO: show")


@resolution_app.command("supersede")
def resolution_supersede_command() -> None:
    """Supersede a resolution record (stub; T7.9)."""
    typer.echo("TODO: supersede")


# ---------------------------------------------------------------------------
# vocabulary sub-commands (stubs — T7.10)
# ---------------------------------------------------------------------------


@vocabulary_app.command("show")
def vocabulary_show_command() -> None:
    """Show the active entity-kind vocabulary (stub; T7.10)."""
    typer.echo("TODO: show")


@vocabulary_app.command("snapshot")
def vocabulary_snapshot_command() -> None:
    """Snapshot the entity-kind vocabulary (stub; T7.10)."""
    typer.echo("TODO: snapshot")
