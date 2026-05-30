"""``amanuensis init [PATH]`` — bootstrap a workspace.

Mutating command — but does NOT acquire the workspace flock (the
flock lives under the workspace root that this command is creating;
acquiring it before the directory exists would be incoherent). The
race window is brief and the operation is idempotent: a re-run of
``init`` against a partially-created workspace simply fills in what is
missing.

Files written
-------------
- ``<path>/amanuensis.yaml`` — INV-1 marker, with ``schema_version: 1``
  and ``project_name: <basename>``. Idempotent: if the file exists,
  nothing is written and the command exits 0 with a friendly message.
- ``<path>/docs/`` — created if missing. (INV-2 keeps documentation
  out of the project root.)
- ``<path>/.gitignore`` — created with sensible defaults if missing;
  if present, left alone (operator may have curated it).

Marker contents
---------------
Intentionally minimal. M4.5's docs/cli-reference.md will document the
full schema; for now the marker only needs ``schema_version`` and
``project_name`` for INV-1 to be satisfied. Operators can flesh it out
(domain config, posture, etc.) with their editor of choice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

DEFAULT_GITIGNORE = """# amanuensis workspace
__pycache__/
.venv/
*.tmp.*
.amanuensis-lock
"""


def _marker_text(project_name: str) -> str:
    """Render the minimal valid ``amanuensis.yaml`` body."""
    # Single-line strings keep YAML hand-edit-friendly. Operators add
    # domain config / posture later.
    return f"schema_version: 1\nproject_name: {project_name}\n"


def init_command(
    path: Annotated[
        Path | None,
        typer.Argument(
            help="Workspace directory to initialize. Defaults to the current directory.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Initialize an amanuensis workspace at PATH (default: current directory).

    Idempotent: re-running on an existing workspace is a no-op for the
    marker but will still create ``docs/`` and ``.gitignore`` if either
    is missing. The marker file is the INV-1 anchor; downstream commands
    refuse to run without it.
    """
    workspace = (path if path is not None else Path.cwd()).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    marker = workspace / "amanuensis.yaml"
    if marker.is_file():
        typer.echo(f"amanuensis.yaml already exists at {marker}; leaving in place.")
    else:
        marker.write_text(_marker_text(workspace.name), encoding="utf-8")
        typer.echo(f"wrote marker: {marker}")

    docs = workspace / "docs"
    if not docs.exists():
        docs.mkdir(parents=True, exist_ok=False)
        typer.echo(f"created directory: {docs}")

    gitignore = workspace / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(DEFAULT_GITIGNORE, encoding="utf-8")
        typer.echo(f"wrote .gitignore: {gitignore}")

    typer.echo(f"workspace ready at {workspace}")
