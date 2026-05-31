"""Lint tests for map_audit.md skill (Phase 2a M5 T5.4)."""

from __future__ import annotations

from pathlib import Path

from amanuensis.skills._frontmatter import split_frontmatter

SKILL = Path(__file__).parent.parent.parent / "src" / "amanuensis" / "skills" / "map_audit.md"


def _frontmatter(p: Path) -> dict[str, object]:
    """Parse and extract frontmatter from skill markdown."""
    fm, _ = split_frontmatter(p.read_text(encoding="utf-8"))
    return fm


REQUIRED_FIELDS = (
    "name",
    "description",
    "role",
    "version",
    "active",
    "stub",
    "expects_substrate",
    "phase",
    "cli_commands_invoked",
)


def test_skill_exists() -> None:
    """Verify the skill file exists."""
    assert SKILL.exists(), f"skill file missing: {SKILL}"


def test_frontmatter_required_fields() -> None:
    """All required frontmatter fields are present."""
    fm = _frontmatter(SKILL)
    for k in REQUIRED_FIELDS:
        assert k in fm, f"missing required frontmatter key: {k}"


def test_stub_false_implies_active_true() -> None:
    """Non-stub skills must have active=true."""
    fm = _frontmatter(SKILL)
    if not fm.get("stub"):
        assert fm.get("active") is True, "non-stub skill must have active=true"


def test_body_has_conventional_sections() -> None:
    """Body contains all four conventional skill sections."""
    body = SKILL.read_text(encoding="utf-8")
    for section in ("## Purpose", "## Inputs", "## Output contract", "## Rules"):
        assert section in body, f"skill missing section: {section}"


def test_cli_commands_invoked_are_real() -> None:
    """Every cli_commands_invoked entry maps to a real CLI command."""
    fm = _frontmatter(SKILL)
    invoked = fm.get("cli_commands_invoked")
    assert isinstance(invoked, list), "cli_commands_invoked must be a list"

    # Import the CLI app for introspection.
    from amanuensis.cli import app

    # Extract all resolvable commands and groups.
    top_level_commands = {cmd.name for cmd in app.registered_commands}
    all_commands: set[str] = {c for c in top_level_commands if c is not None}

    # Recursively add subcommand group commands (two levels deep to cover
    # nested sub-apps like ``map entity show``).
    for group in app.registered_groups:
        group_name = group.name
        typer_app = group.typer_instance
        if typer_app is None:
            continue
        if hasattr(typer_app, "registered_commands"):
            for cmd in typer_app.registered_commands:
                all_commands.add(f"{group_name} {cmd.name}")
        if hasattr(typer_app, "registered_groups"):
            for subgroup in typer_app.registered_groups:
                subgroup_name = subgroup.name
                sub_typer_app = subgroup.typer_instance
                if sub_typer_app is not None and hasattr(sub_typer_app, "registered_commands"):
                    for cmd in sub_typer_app.registered_commands:
                        all_commands.add(f"{group_name} {subgroup_name} {cmd.name}")

    # Validate every invoked command against the registered CLI surface.
    for cmd_str in invoked:  # pyright: ignore[reportUnknownVariableType]
        if not cmd_str.startswith("amanuensis "):
            raise AssertionError(f"invalid cli_commands_invoked format: {cmd_str}")

        cmd_path = cmd_str.replace("amanuensis ", "")
        assert cmd_path in all_commands, f"cli command not found in app: {cmd_path}"
