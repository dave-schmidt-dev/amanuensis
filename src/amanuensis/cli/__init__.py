"""Amanuensis CLI — root Typer application.

The ``app`` exported here is the entry point registered in
``[project.scripts]``. Each top-level command (``init``, ``ingest``,
``status``, ``install-skills``) registers as a Typer command; the
subcommand groups (``atom``, ``clarification``, ``iteration``,
``vocabulary``) register via ``app.add_typer``.

Each command is implemented in its own module under
``amanuensis.cli.<name>`` so the public surface stays grep-able and so
each module owns one concern. Mutating commands acquire the workspace
flock (``amanuensis.fs.lock.acquire_workspace_lock``) within their own
body; read-only commands do not.

Hard rules upheld here
----------------------
- INV-1: every command except ``init`` is wrapped in
  ``@require_marker`` (see ``_marker.py``).
- INV-8: substrate access is mediated through the ``Substrate`` class
  exclusively — the CLI never reads / writes substrate paths directly.

The ``--version`` flag is provided as an eager callback so it can be
invoked before any subcommand routing.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

import typer

from . import (
    atom,
    clarification,
    dispatch,
    ingest,
    init,
    install_skills,
    iteration,
    status,
    vocabulary,
)

# ``no_args_is_help=True`` makes ``amanuensis`` (no args) print help
# instead of silently succeeding. ``add_completion=False`` keeps the
# surface minimal for Phase 1; shell completion can be added once the
# command surface is stable.
app = typer.Typer(
    name="amanuensis",
    help="Agent-consumable workspace for legal-quality document distillation.",
    no_args_is_help=True,
    add_completion=False,
)


def _package_version() -> str:
    """Return the installed amanuensis distribution version, or ``"unknown"``.

    Mirrors the same pattern as ``ingest.docling_ingester._docling_version``.
    The pragma-no-cover branch fires only when the package is somehow
    importable without metadata (development checkouts that bypass
    ``pip install -e .`` entirely — uv's editable install always
    populates the metadata, so this is defensive only).
    """
    try:
        return version("amanuensis")
    except PackageNotFoundError:  # pragma: no cover - dev-env glitch
        return "unknown"


def _version_callback(value: bool) -> None:
    """Eager ``--version`` callback.

    Implemented as an ``is_eager`` Typer option so users can run
    ``amanuensis --version`` without supplying a subcommand. Typer
    raises ``typer.Exit`` after the callback runs (cleanly).
    """
    if value:
        typer.echo(_package_version())
        raise typer.Exit()


@app.callback()
def _root(  # pyright: ignore[reportUnusedFunction]
    version_flag: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the amanuensis version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Amanuensis CLI — see ``amanuensis --help`` for commands."""
    # version_flag is consumed by the eager callback (`_version_callback`)
    # before this body runs; reference it here so static analysis (vulture)
    # sees it as used. The body itself is intentionally a no-op.
    _ = version_flag


# --- Top-level commands ----------------------------------------------
#
# ``init`` registers without the marker decorator (it CREATES the
# marker). Every other top-level command is marker-protected inside
# its own module.
app.command(name="init")(init.init_command)
app.command(name="ingest")(ingest.ingest_command)
app.command(name="status")(status.status_command)
app.command(name="install-skills")(install_skills.install_skills_command)
app.command(name="dispatch")(dispatch.dispatch_command)


# --- Subcommand groups -----------------------------------------------
app.add_typer(atom.app, name="atom", help="List, show, and validate atoms in a distillation.")
app.add_typer(
    clarification.app,
    name="clarification",
    help="List and resolve clarifications in a distillation.",
)
app.add_typer(
    iteration.app,
    name="iteration",
    help="List and add workspace-level iteration directives.",
)
app.add_typer(
    vocabulary.app,
    name="vocabulary",
    help="Inspect the active vocabulary registry and per-distillation snapshots.",
)


__all__ = ["app"]
