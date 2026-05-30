"""``amanuensis install-skills`` — STUB implementation (M4.3).

Stub-level discovery only. M4.3 detects which agent-harness CLIs are
installed on this host (via ``shutil.which``) and emits "Would install
N skills into <path>" placeholders. The actual six skill files do not
exist yet (M7.1 writes them); M7.6 finalises this command to do real
file installation. Until then this command is idempotent and side-
effect-free.

Why a stub now? The CLI surface needs to enumerate every command in M4
so downstream documentation (M4.5), CI smoke tests (M11.1), and the
INV-4 read-only / mutating gate (M4.4) can audit the full command set.

Harness CLIs detected
---------------------
- ``claude`` (Claude Code)
- ``codex`` (Codex)
- ``cursor-agent`` (Cursor)
- ``gemini`` (Gemini CLI)
"""

from __future__ import annotations

import shutil
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from ._marker import require_marker, workspace_from_kwargs


class HarnessChoice(StrEnum):
    """Closed set of harness targets the CLI accepts.

    ``all`` is treated as "every detected harness"; unknown CLI strings
    are rejected by Typer's enum-aware parsing before the command body
    runs.
    """

    claude = "claude"
    codex = "codex"
    cursor = "cursor"
    gemini = "gemini"
    all = "all"


# Map harness option value -> (cli binary name, default install dir suffix
# relative to ``~``). Install paths are NOT created in M4.3 — they are
# only echoed back to the operator so M7.1's skill author knows where
# the harness expects skills. Each suffix is the conventional location
# documented by the corresponding tool's plugin / skill system.
_HARNESS_TABLE: dict[str, tuple[str, str]] = {
    HarnessChoice.claude.value: ("claude", ".claude/skills"),
    HarnessChoice.codex.value: ("codex", ".codex/skills"),
    HarnessChoice.cursor.value: ("cursor-agent", ".cursor/skills"),
    HarnessChoice.gemini.value: ("gemini", ".gemini/skills"),
}

# Number of skills the M7.1 milestone will write. Used in the placeholder
# message so operators see the intent now.
_PLANNED_SKILL_COUNT = 6


def _detect_one(harness: str) -> tuple[bool, str, str]:
    """Probe one harness; returns (detected, binary_name, install_dir)."""
    binary, suffix = _HARNESS_TABLE[harness]
    detected = shutil.which(binary) is not None
    install_dir = str(Path.home() / suffix)
    return detected, binary, install_dir


@require_marker
def install_skills_command(
    harness: Annotated[
        HarnessChoice,
        typer.Option(
            "--harness",
            help=(
                "Which harness to target. 'all' iterates every supported harness; "
                "unrecognised values are rejected before the command runs."
            ),
        ),
    ] = HarnessChoice.all,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Detect installed harness CLIs and print where skills WOULD install.

    M4.3 stub: no files are written. M7.1 ships the skill files and
    M7.6 finalises this command to actually copy them. Idempotent and
    side-effect-free until then.
    """
    # ``workspace`` is consumed by @require_marker via workspace_from_kwargs;
    # we resolve it here too to echo the project root we activated against.
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    typer.echo("amanuensis install-skills (stub: M4.3)")
    typer.echo(f"workspace:  {workspace_path}")
    typer.echo("")

    if harness is HarnessChoice.all:
        targets = [h.value for h in HarnessChoice if h is not HarnessChoice.all]
    else:
        targets = [harness.value]

    detected_any = False
    for target in targets:
        detected, binary, install_dir = _detect_one(target)
        if detected:
            typer.echo(
                f"detected: {target:8s}  binary={binary}  "
                f"Would install {_PLANNED_SKILL_COUNT} skills into {install_dir}"
            )
            detected_any = True
        else:
            typer.echo(f"not found: {target:8s}  binary={binary} (skipping)")

    if not detected_any:
        typer.echo("")
        typer.echo("# no harness CLIs detected on PATH; nothing would be installed")
