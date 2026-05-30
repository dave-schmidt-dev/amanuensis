"""``amanuensis ingest [--engine] [--source-id] <pdf-path>`` — run an ingester.

Mutating command (writes source-mirror manifest, paragraphs, PROV,
vocabulary snapshot). Acquires the workspace flock for the duration of
the ingest call so concurrent CLI ingest / web POST / dispatch runs
serialize.

Engine selection
----------------
- ``--engine docling`` (default): high-fidelity, section-aware.
- ``--engine pdfplumber``: lighter fallback with no section_path.

The source_id defaults to the PDF stem (``Path(pdf).stem``); the
operator can override for collision-avoidance or naming consistency
across runs.

The agent attribution is recorded as
``AgentAttribution(kind="human", identifier="cli", role="extractor")``:
``human`` reflects that a supervisor explicitly invoked the CLI
(not an LLM acting autonomously), and the ``extractor`` role matches
the substrate's role taxonomy for the artifact being produced.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from amanuensis.fs import Substrate, acquire_workspace_lock
from amanuensis.ingest import ingest_pdf, ingest_pdf_pdfplumber
from amanuensis.schemas import AgentAttribution

from ._common import load_active_vocabulary
from ._marker import fatal, require_marker, workspace_from_kwargs


class Engine(StrEnum):
    """Closed set of ingest engines exposed to the CLI."""

    docling = "docling"
    pdfplumber = "pdfplumber"


@require_marker
def ingest_command(
    pdf_path: Annotated[
        Path,
        typer.Argument(
            help="Path to the PDF to ingest.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    engine: Annotated[
        Engine,
        typer.Option(
            "--engine",
            "-e",
            help="Ingest engine: docling (default, section-aware) or pdfplumber (fallback).",
        ),
    ] = Engine.docling,
    source_id: Annotated[
        str | None,
        typer.Option(
            "--source-id",
            "-s",
            help="Per-distillation id (path-safe). Defaults to the PDF stem.",
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
    """Ingest a PDF into the workspace's source-mirror substrate.

    Writes ``distillations/<source-id>/{source-mirror/, provenance/,
    vocabulary-snapshot.yaml}``. Refuses to re-ingest an existing
    source_id (the substrate raises ``SourceMirrorExists``); delete the
    distillation's ``source-mirror/`` to re-run.
    """
    workspace_path = workspace_from_kwargs(
        {
            "workspace": workspace,
        }
    )
    substrate = Substrate(workspace_path)
    resolved_source_id = source_id or pdf_path.stem

    vocabulary = load_active_vocabulary(workspace_path)

    agent = AgentAttribution(
        kind="human",
        identifier="cli",
        role="extractor",
    )

    try:
        with acquire_workspace_lock(workspace_path):
            if engine is Engine.docling:
                manifest = ingest_pdf(
                    substrate=substrate,
                    source_id=resolved_source_id,
                    pdf_path=pdf_path,
                    vocabulary=vocabulary,
                    agent_attribution=agent,
                )
            else:
                manifest = ingest_pdf_pdfplumber(
                    substrate=substrate,
                    source_id=resolved_source_id,
                    pdf_path=pdf_path,
                    vocabulary=vocabulary,
                    agent_attribution=agent,
                )
    except Exception as exc:
        fatal(f"ingest failed: {exc}")
        return  # unreachable; ``fatal`` raises typer.Exit

    manifest_path = substrate.manifest_path(resolved_source_id)
    typer.echo(f"ingest engine:        {manifest.ingest_engine}")
    typer.echo(f"source_id:            {resolved_source_id}")
    typer.echo(f"paragraphs ingested:  {len(manifest.paragraphs)}")
    typer.echo(f"manifest:             {manifest_path}")
    typer.echo(f"vocabulary snapshot:  {substrate.vocabulary_snapshot_path(resolved_source_id)}")
