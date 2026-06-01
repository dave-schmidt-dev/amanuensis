"""``amanuensis export`` — Phase 1 per-source HTML + Phase 2b workspace bundle.

Read-only command. Two operating modes:

1. **Per-source single-file** (Phase 1, M9.1):
   ``amanuensis export <source-id> --output FILE.html`` — wraps
   :func:`amanuensis.export.export_static_html`.

2. **Workspace-level appendix bundle** (Phase 2b, M9 + T10.0):
   ``amanuensis export --workspace-appendix --out-dir DIR`` — wraps
   :func:`amanuensis.export.export_workspace_appendix`. Emits a directory
   containing ``cross-doc-relations.html`` plus one per-entity page under
   ``entities/<id>.html``.

Both modes are marker-protected (INV-1), accept ``--workspace``, and are
read-only (no flock acquisition, no replay-log writes). Mutual-exclusion
of the two modes is enforced before any substrate read.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from amanuensis.export import export_static_html, export_workspace_appendix
from amanuensis.fs import Substrate, SubstrateNotFound

from ._marker import fatal, require_marker, workspace_from_kwargs


class ExportFormat(StrEnum):
    """Closed set of export formats. Phase 1 ships ``static-html`` only."""

    static_html = "static-html"


@require_marker
def export_command(
    source_id: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Per-distillation source id to export. Required for the "
                "Phase 1 single-file mode; must be OMITTED when "
                "--workspace-appendix is set."
            ),
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "Destination path for the single-file export. Required "
                "for the Phase 1 per-source mode."
            ),
        ),
    ] = None,
    workspace_appendix: Annotated[
        bool,
        typer.Option(
            "--workspace-appendix",
            help=(
                "Emit the Phase 2b workspace-level cross-doc appendix bundle "
                "to --out-dir instead of a single per-source HTML file. "
                "Mutually exclusive with the positional source-id argument."
            ),
        ),
    ] = False,
    out_dir: Annotated[
        Path | None,
        typer.Option(
            "--out-dir",
            help=(
                "Destination directory for --workspace-appendix. Created "
                "(with parents) if missing; existing files at the same "
                "paths are overwritten."
            ),
        ),
    ] = None,
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
    """Export the substrate as static HTML.

    Two modes:

    * **Per-source** (Phase 1, M9.1): ``amanuensis export <source-id>
      --output FILE.html`` produces a single self-contained HTML file
      for one distillation.
    * **Workspace appendix** (Phase 2b, M9 + T10.0): ``amanuensis export
      --workspace-appendix --out-dir DIR`` produces a directory bundle
      with ``cross-doc-relations.html`` and per-entity pages covering
      every canonical entity touched by a cross-doc relation. Useful
      for share-or-archive when the supervisor wants the cross-doc
      reasoning rendered in static form.

    Phase 2a (M9) adds the entity sidebar and inline resolution
    annotations to the per-source mode when ``--include-mappings`` is
    set (the default). Pass ``--no-include-mappings`` to produce a
    Phase-1-compatible output.
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})

    # Mutual-exclusion preflight — runs before any substrate read so a
    # bad invocation fails fast with a clear message.
    if workspace_appendix:
        if source_id is not None:
            fatal(
                "--workspace-appendix is mutually exclusive with the "
                "positional source-id argument; pass one or the other, "
                "not both.",
                code=2,
            )
            return
        if out_dir is None:
            fatal(
                "--workspace-appendix requires --out-dir DIR.",
                code=2,
            )
            return
        _run_workspace_appendix(workspace_path, out_dir)
        return

    # Single-file mode requires both source_id and output.
    if source_id is None:
        fatal(
            "missing required argument: source-id (or pass "
            "--workspace-appendix --out-dir DIR for the bundle mode).",
            code=2,
        )
        return
    if output is None:
        fatal(
            "missing required option: --output PATH (Phase 1 single-file mode).",
            code=2,
        )
        return

    # The ExportFormat enum already constrains valid values; this guard
    # exists so adding a new variant in the future without wiring it up
    # produces a clean error rather than a silent no-op.
    if fmt is not ExportFormat.static_html:  # pragma: no cover - defensive
        fatal(f"unsupported export format {fmt.value!r}; Phase 1 supports static-html only")
        return

    substrate = Substrate(workspace_path)
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


def _run_workspace_appendix(workspace_path: Path, out_dir: Path) -> None:
    """Drive the workspace-level appendix exporter and print a summary line.

    Factored out of the main command body to keep the dispatch above
    purely about routing the two modes.
    """
    substrate = Substrate(workspace_path)
    # ``list_cross_doc_relations`` returns an iterator; materialize so we
    # can both count and confirm the exporter ran over the same handle.
    n_relations = sum(1 for _ in substrate.list_cross_doc_relations())
    # The exporter writes one entity page per canonical entity, not just
    # those touched by a relation — so a workspace with no relations can
    # still produce entity pages. Count after the write completes.
    export_workspace_appendix(substrate=substrate, out_dir=out_dir)
    entities_dir = out_dir / "entities"
    n_entity_pages = sum(1 for _ in entities_dir.glob("*.html")) if entities_dir.is_dir() else 0
    typer.echo(
        f"wrote bundle to {out_dir}/ "
        f"({n_relations} cross-doc relations, {n_entity_pages} entity pages)"
    )
