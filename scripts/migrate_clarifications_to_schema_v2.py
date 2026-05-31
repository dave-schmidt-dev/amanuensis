"""Migrate v1 Clarification on-disk records to v2 (adds kind + bumps schema_version).

v1 records have no `kind` field; v2 added it (T1.8) as a required identity-bearing
discriminator. Backward-compat strategy: default v1 records to
`kind: warrant-defensibility-contested` (the Phase 1 catch-all activity).

This script is idempotent: already-v2 records are no-ops (byte-identical input/output).

Usage:
    python scripts/migrate_clarifications_to_schema_v2.py <workspace-root>

Or programmatically (called from Substrate.__init__ via T1.11):
    from scripts.migrate_clarifications_to_schema_v2 import migrate_workspace
    migrate_workspace(Path("/path/to/workspace"))
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


class MigrationFailed(Exception):
    """Raised when a clarification file cannot be parsed (malformed YAML frontmatter)."""


def migrate_workspace(workspace_root: Path) -> None:
    """Walk distillations/*/clarifications/{open,resolved}/c-*.md; migrate v1 records to v2.

    Args:
        workspace_root: amanuensis workspace root (containing `amanuensis.yaml`).

    Raises:
        MigrationFailed: if any clarification file has malformed YAML frontmatter.

    Notes:
        - Idempotent: already-v2 records are not modified (byte-identical).
        - File writes are atomic via `pathlib.Path.write_text` (overwrite in place).
          The full v1 → v2 transition for any single file is single-threaded —
          flock acquisition is the caller's responsibility (T1.11 acquires the
          workspace lock around the `Substrate.__init__` auto-trigger).
    """
    for c_path in workspace_root.glob("distillations/*/clarifications/*/c-*.md"):
        try:
            _migrate_one(c_path)
        except MigrationFailed:
            raise
        except Exception as exc:
            raise MigrationFailed(f"failed to migrate {c_path}: {exc}") from exc


def _migrate_one(c_path: Path) -> None:
    """Migrate a single clarification file in place. Idempotent.

    Steps:
    1. Read text.
    2. If no ``---\\n`` frontmatter delimiter, raise MigrationFailed (malformed).
    3. Parse YAML frontmatter to a dict.
    4. If ``schema_version == 2`` and ``kind`` present: no-op, return.
    5. Otherwise: inject ``kind: warrant-defensibility-contested``,
       set ``schema_version: 2``.
    6. Re-serialize with stable key order (sort_keys=False).
    7. Write back in place.
    """
    text = c_path.read_text(encoding="utf-8")

    # Frontmatter must start with --- and contain a closing ---
    if not text.startswith("---\n"):
        raise MigrationFailed(f"{c_path}: missing YAML frontmatter opening delimiter '---'")

    # Find closing delimiter. Match "\n---" (newline-prefixed) so a YAML
    # block-scalar value containing "---" mid-content cannot be mistaken
    # for the frontmatter terminator.
    rest = text[4:]  # skip opening "---\n"
    closing_idx = rest.find("\n---")
    if closing_idx == -1:
        raise MigrationFailed(f"{c_path}: missing YAML frontmatter closing delimiter '---'")

    fm_text = rest[: closing_idx + 1]  # include the trailing newline before "---"
    body_after = rest[closing_idx + 4 :]  # everything after "\n---"

    try:
        data: Any = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        raise MigrationFailed(f"{c_path}: YAML parse error: {exc}") from exc

    if not isinstance(data, dict):
        raise MigrationFailed(f"{c_path}: frontmatter did not parse to a mapping")

    fm: dict[str, Any] = data

    # Already v2 with kind present — no-op, preserve byte-equality
    if fm.get("schema_version") == 2 and "kind" in fm:
        return

    # Inject kind and bump schema_version
    fm["kind"] = "warrant-defensibility-contested"
    fm["schema_version"] = 2

    serialized_fm = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False)
    # yaml.safe_dump always appends a trailing newline; keep it as-is
    new_text = f"---\n{serialized_fm}---{body_after}"

    c_path.write_text(new_text, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "Usage: migrate_clarifications_to_schema_v2.py <workspace-root>",
            file=sys.stderr,
        )
        sys.exit(2)
    migrate_workspace(Path(sys.argv[1]))
    print("Migration complete.")
