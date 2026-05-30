"""``amanuensis clarification <subcommand>`` — list / resolve.

Subcommands
-----------
- ``clarification list [--status]`` — read-only; no flock.
- ``clarification resolve <id> --resolution TEXT`` — mutating;
  acquires workspace flock. Writes a paired ``clarification-resolved``
  PROV record and flips the on-disk file from ``open/`` to ``resolved/``
  by writing the updated record then removing the open variant.

The clarification id alone is enough to locate the open file because
``Substrate.clarification_path`` derives the path from
``(source_id, clarification_id, resolved=bool)`` — but the source_id
is needed too, so it's a required argument on ``resolve``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from amanuensis.fs import Substrate, acquire_workspace_lock
from amanuensis.fs._serialize import parse_clarification_md
from amanuensis.schemas import AgentAttribution, Clarification, ProvenanceRecord, compute_id

from ._common import list_distillations
from ._marker import fatal, require_marker, workspace_from_kwargs

app = typer.Typer(
    name="clarification",
    help="List and resolve clarifications in a distillation.",
    no_args_is_help=True,
    add_completion=False,
)


class Status(StrEnum):
    """Closed status filter for ``clarification list``."""

    open = "open"
    resolved = "resolved"


def _iter_clarifications(
    substrate: Substrate, *, status_filter: Status | None
) -> list[tuple[str, Clarification]]:
    """Walk every distillation; yield ``(source_id, clarification)`` pairs.

    Lex-sorted by source_id then by clarification id (filesystem order).
    Skips ``.tmp.*`` writer leftovers. Returns a materialized list so
    the caller can take a count cheaply.
    """
    out: list[tuple[str, Clarification]] = []
    buckets: tuple[str, ...]
    if status_filter is None:
        buckets = ("open", "resolved")
    else:
        buckets = (status_filter.value,)
    for source_id in list_distillations(substrate):
        for bucket in buckets:
            dir_path = substrate.root / "distillations" / source_id / "clarifications" / bucket
            if not dir_path.is_dir():
                continue
            for path in sorted(dir_path.iterdir()):
                if not path.is_file() or not path.name.endswith(".md"):
                    continue
                if ".tmp." in path.name:
                    continue
                try:
                    clar = parse_clarification_md(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                out.append((source_id, clar))
    return out


@app.command("list")
@require_marker
def list_clarifications_command(
    status_filter: Annotated[
        Status | None,
        typer.Option(
            "--status",
            help="Filter by status (default: list both open and resolved).",
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
    """List clarifications across all distillations (read-only)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)
    rows = _iter_clarifications(substrate, status_filter=status_filter)
    if not rows:
        typer.echo("# no clarifications")
        return
    for source_id, clar in rows:
        typer.echo(
            f"{clar.status:8s}  {source_id}/{clar.id}  raised_by={clar.raised_by.identifier}  "
            f"q={clar.question[:80]!r}"
        )
    typer.echo(f"# {len(rows)} clarification(s)")


def _find_clarification(
    substrate: Substrate, *, clarification_id: str
) -> tuple[str, Clarification, Path]:
    """Locate an open clarification by id.

    Searches every distillation's ``clarifications/open/`` for the
    matching id. Errors with a clear message if not found (or if the
    clarification has already been resolved — that file lives in
    ``resolved/`` and is not eligible for re-resolution).
    """
    for source_id in list_distillations(substrate):
        open_path = substrate.clarification_path(source_id, clarification_id, resolved=False)
        if open_path.is_file():
            clar = parse_clarification_md(open_path.read_text(encoding="utf-8"))
            return source_id, clar, open_path
    fatal(f"no open clarification with id {clarification_id!r} found in any distillation")
    raise AssertionError("unreachable")  # pragma: no cover - fatal raises


@app.command("resolve")
@require_marker
def resolve_clarification_command(
    clarification_id: Annotated[
        str,
        typer.Argument(help="Clarification id (e.g. c-<hash>) to resolve."),
    ],
    resolution: Annotated[
        str,
        typer.Option("--resolution", help="The resolution text to record."),
    ],
    resolver: Annotated[
        str,
        typer.Option(
            "--resolver",
            help="Identifier of the human resolving (recorded on the resolved-by agent).",
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
    """Resolve an open clarification, writing the resolved record + PROV.

    Acquires the workspace flock for the duration of the write.
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)
    with acquire_workspace_lock(workspace_path):
        source_id, original, open_path = _find_clarification(
            substrate, clarification_id=clarification_id
        )
        if original.status == "resolved":  # pragma: no cover - guarded above
            fatal(f"clarification {clarification_id!r} is already resolved")
            return

        now = datetime.now(UTC)
        resolved_by = AgentAttribution(
            kind="human",
            identifier=resolver,
            role="human_supervisor",
        )

        # 1. Build the resolved provenance record. ``entity_id`` is the
        #    clarification's id (the PROV-O subject is the clarification
        #    artifact itself).
        prov_draft = ProvenanceRecord(
            id="p-" + "0" * 16,
            entity_type="clarification-resolved",
            entity_id=original.id,
            activity="clarification-resolve",
            activity_started_at=now,
            activity_ended_at=now,
            used_entity_ids=[original.raised_provenance_id],
            was_attributed_to=resolved_by,
            was_influenced_by=[],
            schema_version=1,
        )
        prov_id = compute_id(prov_draft)
        prov = prov_draft.model_copy(update={"id": prov_id})
        substrate.add_provenance(source_id, prov)

        # 2. Build the updated clarification (status flip + resolution +
        #    pointer to the resolved PROV). The identity of a
        #    ``Clarification`` excludes the volatile lifecycle fields
        #    (status, resolved_*, *_provenance_id), so the id is stable.
        resolved_clar = original.model_copy(
            update={
                "status": "resolved",
                "resolved_at": now,
                "resolved_by": resolved_by,
                "resolution": resolution,
                "resolved_provenance_id": prov.id,
            }
        )
        # The substrate's add_clarification routes by ``status`` to the
        # correct bucket (open/ vs resolved/) — see substrate.py.
        new_path = substrate.add_clarification(source_id, resolved_clar)

        # 3. Remove the open-bucket file so the read paths see exactly
        #    one canonical location. unlink first; the substrate has
        #    already persisted the resolved variant atomically.
        try:
            open_path.unlink()
        except FileNotFoundError:  # pragma: no cover - already gone
            pass

    typer.echo(f"resolved: {clarification_id}")
    typer.echo(f"source_id:   {source_id}")
    typer.echo(f"resolved at: {new_path}")
    typer.echo(f"provenance:  {substrate.provenance_path(source_id, prov.id)}")
