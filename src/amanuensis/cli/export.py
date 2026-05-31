"""``amanuensis export <source-id>`` — Phase 1 static-HTML stub (M9.1).

Read-only command. Wraps :func:`amanuensis.export.export_static_html`
in the standard CLI shell: marker-protected (INV-1), accepts
``--workspace``, no flock acquisition, no replay-log writes.

The ``--format`` option defaults to ``static-html``; that is the only
Phase 1 format. Phase 4 will add ``audit-html`` (full bundle) and
possibly ``pdf``; the option exists today to lock the surface so
callers do not need to be updated when a new format ships.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from amanuensis.export import export_static_html
from amanuensis.fs import Substrate, SubstrateNotFound

from ._marker import fatal, require_marker, workspace_from_kwargs


class ExportFormat(StrEnum):
    """Closed set of export formats. Phase 1 ships ``static-html`` only."""

    static_html = "static-html"


@require_marker
def export_command(
    source_id: Annotated[
        str,
        typer.Argument(help="Per-distillation source id to export."),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Destination path for the exported file (will be created / overwritten).",
        ),
    ],
    fmt: Annotated[
        ExportFormat,
        typer.Option(
            "--format",
            "-f",
            help="Export format. Phase 1 ships static-html only.",
        ),
    ] = ExportFormat.static_html,
    include_mappings: Annotated[
        bool,
        typer.Option(
            "--include-mappings/--no-include-mappings",
            help=(
                "Include entity sidebar and inline resolution annotations "
                "driven by the mappings/ registry (Phase 2a). "
                "Use --no-include-mappings to revert to Phase-1-style rendering."
            ),
        ),
    ] = True,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Export one distillation as a single self-contained HTML file.

    Phase 1 (M9.1) is a stub: the produced HTML contains the source-
    mirror summary, every paragraph body, every atom, every relation,
    and three embedded JSON sidecar blocks (``paragraphs-data``,
    ``atoms-data``, ``relations-data``) so a downstream consumer can
    rebuild the substrate slice. Phase 4 will replace this with the
    full audit-HTML bundle.

    Phase 2a (M9) adds the entity sidebar and inline resolution
    annotations when ``--include-mappings`` is set (the default).  Pass
    ``--no-include-mappings`` to produce a Phase-1-compatible output.
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    # The ExportFormat enum already constrains valid values; this guard
    # exists so adding a new variant in the future without wiring it up
    # produces a clean error rather than a silent no-op.
    if fmt is not ExportFormat.static_html:  # pragma: no cover - defensive
        fatal(f"unsupported export format {fmt.value!r}; Phase 1 supports static-html only")
        return

    try:
        written = export_static_html(
            substrate=substrate,
            source_id=source_id,
            output_path=output,
            include_mappings=include_mappings,
        )
    except SubstrateNotFound as exc:
        fatal(f"cannot export {source_id!r}: {exc}")
        return
    except FileNotFoundError as exc:
        # Raised by ``_load_manifest`` when the manifest is missing; the
        # source-mirror has not been ingested yet (or was deleted).
        fatal(
            f"no source-mirror manifest for {source_id!r}: {exc} "
            "(run `amanuensis ingest <pdf>` first)"
        )
        return

    typer.echo(f"wrote {written}")
