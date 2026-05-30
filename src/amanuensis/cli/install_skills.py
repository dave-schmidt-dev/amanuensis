"""``amanuensis install-skills`` — copy bundled skills into harness skill dirs.

Detects which agent-harness CLIs are installed on this host (via
``shutil.which``) and, for each detected harness, copies the bundled
skill files into the harness's conventional skills directory under
``~/<harness-suffix>/amanuensis/``. The ``amanuensis`` subdirectory
namespaces our skills so they cannot collide with user-authored skills
in the same harness root.

Behaviour
---------
- **Copy, not symlink.** Portable across systems / filesystems without
  symlink support (Windows defaults, network shares).
- **Idempotent.** A destination whose bytes already match the source
  is a no-op (no write, no mtime bump); the "installed:" line is still
  printed so re-runs produce a debuggable trace of what was considered.
- **Overwrites on drift.** A destination whose bytes differ from the
  source is overwritten. Re-running install-skills is how operators
  pick up shipped updates to the bundled skill files.
- **``--dry-run``** previews every action without writing. Output lines
  are prefixed with ``dry-run: would install:`` so they're greppable.
- **``--harness-target PATH``** (hidden test seam) overrides
  ``Path.home()`` so tests install into a tmpdir instead of polluting
  the real home directory.

For NOT-detected harnesses the original "not found" line is preserved
and no install is attempted.

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
from importlib import resources
from importlib.resources.abc import Traversable
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
# relative to ``~``). Each suffix is the conventional skills root
# documented by the corresponding tool's plugin / skill system; we then
# nest an ``amanuensis/`` subdirectory under it to namespace our files.
_HARNESS_TABLE: dict[str, tuple[str, str]] = {
    HarnessChoice.claude.value: ("claude", ".claude/skills"),
    HarnessChoice.codex.value: ("codex", ".codex/skills"),
    HarnessChoice.cursor.value: ("cursor-agent", ".cursor/skills"),
    HarnessChoice.gemini.value: ("gemini", ".gemini/skills"),
}

# The on-disk subdir under each harness's skills root that owns our files.
# Keeping it as a named constant makes it explicit in tests + docs.
_AMANUENSIS_NAMESPACE = "amanuensis"


def _iter_bundled_skills() -> list[Traversable]:
    """Enumerate every ``.md`` skill file bundled in ``amanuensis.skills``.

    Returned in deterministic (sorted) order so the per-file output is
    stable across runs / platforms. We use ``importlib.resources`` so
    the lookup works for wheel + editable installs alike.
    """
    skills_root = resources.files("amanuensis.skills")
    skills = [
        entry for entry in skills_root.iterdir() if entry.is_file() and entry.name.endswith(".md")
    ]
    skills.sort(key=lambda entry: entry.name)
    return skills


def _detect_one(harness: str, home: Path) -> tuple[bool, str, Path]:
    """Probe one harness; returns (detected, binary_name, install_dir).

    ``home`` is parameterised so the ``--harness-target`` test seam can
    redirect the install root without monkeypatching ``Path.home``.
    """
    binary, suffix = _HARNESS_TABLE[harness]
    detected = shutil.which(binary) is not None
    install_dir = home / suffix / _AMANUENSIS_NAMESPACE
    return detected, binary, install_dir


def _install_one_skill(
    *,
    harness: str,
    skill: Traversable,
    dest_dir: Path,
    dry_run: bool,
) -> Path:
    """Copy one bundled skill into ``dest_dir``; idempotent on byte match.

    Returns the destination path so the caller can include it in output.
    No-op when the destination already exists with identical bytes;
    overwrites otherwise. With ``dry_run=True`` no filesystem write
    happens regardless.
    """
    dest = dest_dir / skill.name
    if dry_run:
        return dest
    src_bytes = skill.read_bytes()
    if dest.exists() and dest.read_bytes() == src_bytes:
        # Idempotent path: bytes already match, leave the file (and its
        # mtime) untouched so re-runs don't churn timestamps.
        return dest
    dest.write_bytes(src_bytes)
    return dest


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
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show what would be installed without writing any files.",
        ),
    ] = False,
    harness_target: Annotated[
        Path | None,
        typer.Option(
            "--harness-target",
            help="(test only) override ~ for harness install roots.",
            hidden=True,
        ),
    ] = None,
) -> None:
    """Install bundled skill files into every detected harness's skills dir.

    For each detected harness, copies the six bundled skill files into
    ``<home>/<harness-suffix>/amanuensis/``. Existing files with
    matching bytes are left untouched; differing files are overwritten
    (re-run to pick up updates). ``--dry-run`` previews actions only.
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    home = harness_target if harness_target is not None else Path.home()

    typer.echo("amanuensis install-skills")
    typer.echo(f"workspace:  {workspace_path}")
    if dry_run:
        typer.echo("mode:       dry-run (no files will be written)")
    typer.echo("")

    if harness is HarnessChoice.all:
        targets = [h.value for h in HarnessChoice if h is not HarnessChoice.all]
    else:
        targets = [harness.value]

    skills = _iter_bundled_skills()
    detected_any = False

    for target in targets:
        detected, binary, install_dir = _detect_one(target, home)
        if not detected:
            typer.echo(f"not found: {target:8s}  binary={binary} (skipping)")
            continue

        detected_any = True
        typer.echo(f"detected: {target:8s}  binary={binary}  install_dir={install_dir}")
        if not dry_run:
            install_dir.mkdir(parents=True, exist_ok=True)

        installed_count = 0
        for skill in skills:
            dest = _install_one_skill(
                harness=target,
                skill=skill,
                dest_dir=install_dir,
                dry_run=dry_run,
            )
            prefix = "dry-run: would install:" if dry_run else "installed:"
            typer.echo(f"{prefix} {target}/{skill.name} -> {dest}")
            installed_count += 1

        summary_verb = "would install" if dry_run else "installed"
        typer.echo(f"{summary_verb} {installed_count} skills into {install_dir}")
        typer.echo("")

    if not detected_any:
        typer.echo("# no harness CLIs detected on PATH; nothing would be installed")
