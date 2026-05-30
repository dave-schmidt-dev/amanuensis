"""``@require_marker`` — enforce INV-1 on a Typer command body.

INV-1 (``amanuensis.yaml`` marker required at the workspace root):
every CLI command except ``init`` must refuse to operate outside a
marked directory. The decorator here is the single source of that
refusal: subcommands wrap their body in ``@require_marker`` rather than
each open-coding the check.

Activation rules
----------------
- The decorator looks at the Typer command's first parameter for the
  workspace path. Per the CLI design, every marker-protected command
  accepts ``--workspace PATH`` (default ``Path.cwd()``); the decorator
  reads that parameter by name (``workspace``) at call time.
- If the resolved path is not an existing directory OR does not contain
  ``amanuensis.yaml``, the decorator prints a clear error to stderr and
  exits with ``typer.Exit(code=2)``. Exit code 2 is the canonical
  "usage / preflight" error code (distinct from 1 = command-body
  failure).
- ``Substrate.__init__`` itself raises ``SubstrateMarkerMissing``; we
  convert that exception into the typed exit + stderr message so the
  Typer ``CliRunner`` and human users get a uniform UX.

Design notes
------------
- The decorator does NOT construct a ``Substrate`` for the wrapped
  function. It only validates that one CAN be constructed; command
  bodies build their own substrate handle so they retain full control
  over error handling for downstream operations.
- ``functools.wraps`` preserves the wrapped function's name + signature
  so Typer's introspection-driven help / argument parsing keeps working.
"""

from __future__ import annotations

import functools
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from amanuensis.fs import Substrate, SubstrateMarkerMissing


def _resolve_workspace(workspace: Path | str | None) -> Path:
    """Coerce the ``workspace`` parameter to a ``Path``, defaulting to CWD."""
    if workspace is None:
        return Path.cwd()
    return Path(workspace)


def require_marker[F: Callable[..., Any]](func: F) -> F:
    """Decorate a Typer command so it refuses to run without the INV-1 marker.

    The wrapped function must accept a keyword-or-positional parameter
    named ``workspace``. If absent / ``None``, the current working
    directory is used (matches Typer's default for an optional path).

    On INV-1 failure: emits a clear error to stderr (naming the path
    that was checked) and raises ``typer.Exit(code=2)``. On success:
    delegates to ``func`` unchanged.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        workspace_value = kwargs.get("workspace")
        workspace_path = _resolve_workspace(workspace_value)
        try:
            Substrate(workspace_path)
        except SubstrateMarkerMissing as exc:
            typer.secho(
                f"error: {exc}",
                err=True,
                fg=typer.colors.RED,
            )
            typer.secho(
                "Run `amanuensis init` to create a workspace, or pass "
                "`--workspace PATH` to point at an existing one.",
                err=True,
            )
            raise typer.Exit(code=2) from exc
        # Marker present: proceed with the real command body. We do not
        # construct a Substrate here — the command builds its own handle
        # so it owns downstream error handling.
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def workspace_from_kwargs(kwargs: dict[str, Any]) -> Path:
    """Helper for command bodies: pull the resolved workspace from kwargs.

    Mirrors the resolution rule used by ``require_marker`` so command
    bodies do not have to re-derive it. Returns the absolute resolved
    path so substrate / lock operations get a canonical handle.
    """
    return _resolve_workspace(kwargs.get("workspace")).resolve()


def echo_error(message: str) -> None:
    """Stderr error emitter shared across CLI modules.

    Centralised so error formatting (red, ``error:`` prefix) is uniform;
    a future change to make the prefix machine-parseable (JSON, etc.)
    happens here once.
    """
    typer.secho(f"error: {message}", err=True, fg=typer.colors.RED)


def fatal(message: str, *, code: int = 1) -> None:
    """Emit an error message and exit. Wraps the common ``echo_error`` + ``Exit`` pair."""
    echo_error(message)
    # ``flush`` keeps stderr ordering deterministic in CI capture.
    sys.stderr.flush()
    raise typer.Exit(code=code)
