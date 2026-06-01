"""CLI tests for ``amanuensis map relation`` sub-commands (Phase 2b M7).

The verbs exercised here mirror Phase 2a's ``map entity`` and
``map resolution`` sub-apps for the new Phase 2b ``CrossDocRelation``
records:

- ``relation list`` — read-only listing with optional filters (T7.1).
- ``relation show`` — record detail view (T7.2).
- ``relation supersede`` — supervisor correction (T7.3).

The fixture ``tmp_workspace_with_two_cross_doc_relations`` (see
``tests/cli/conftest.py``) plants two committed ``CrossDocRelation``
records (one ``supports`` + one ``attacks``) on top of a workspace that
already satisfies INV-1, INV-13, and INV-15.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli.map import map_app
from amanuensis.fs import Substrate

runner = CliRunner()


# ---------------------------------------------------------------------------
# T7.1: amanuensis map relation list
# ---------------------------------------------------------------------------


def test_list_lists_all_cross_doc_relations(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """Workspace with two CrossDocRelation records → both appear in output."""
    result = runner.invoke(
        map_app,
        ["relation", "list", "--workspace", str(tmp_workspace_with_two_cross_doc_relations)],
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if "x-" in line]
    # Both committed relations are visible.
    assert len(lines) >= 2


def test_list_filters_by_kind(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """``--kind supports`` filters down to one of the two planted relations."""
    result = runner.invoke(
        map_app,
        [
            "relation",
            "list",
            "--kind",
            "supports",
            "--workspace",
            str(tmp_workspace_with_two_cross_doc_relations),
        ],
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if "x-" in line]
    assert len(lines) == 1
    assert "supports" in lines[0]


def test_list_filters_by_from_source(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """``--from-source src-A`` returns both relations (both originate there)."""
    result = runner.invoke(
        map_app,
        [
            "relation",
            "list",
            "--from-source",
            "src-A",
            "--workspace",
            str(tmp_workspace_with_two_cross_doc_relations),
        ],
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if "x-" in line]
    assert len(lines) == 2


def test_list_filters_by_to_source_no_match(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """``--to-source src-A`` matches nothing (both edges go to src-B)."""
    result = runner.invoke(
        map_app,
        [
            "relation",
            "list",
            "--to-source",
            "src-A",
            "--workspace",
            str(tmp_workspace_with_two_cross_doc_relations),
        ],
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if "x-" in line]
    assert len(lines) == 0


def test_list_filters_by_touching_source(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """``--touching-source src-B`` matches both (both edges land there)."""
    result = runner.invoke(
        map_app,
        [
            "relation",
            "list",
            "--touching-source",
            "src-B",
            "--workspace",
            str(tmp_workspace_with_two_cross_doc_relations),
        ],
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if "x-" in line]
    assert len(lines) == 2


def test_list_filters_by_shared_entity(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """``--shared-entity e-smith`` matches both relations."""
    result = runner.invoke(
        map_app,
        [
            "relation",
            "list",
            "--shared-entity",
            "e-smith",
            "--workspace",
            str(tmp_workspace_with_two_cross_doc_relations),
        ],
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if "x-" in line]
    assert len(lines) == 2


def test_list_respects_limit(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """``--limit 1`` truncates output to one record."""
    result = runner.invoke(
        map_app,
        [
            "relation",
            "list",
            "--limit",
            "1",
            "--workspace",
            str(tmp_workspace_with_two_cross_doc_relations),
        ],
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if "x-" in line]
    assert len(lines) == 1


def test_list_empty_workspace_prints_nothing(tmp_path: Path) -> None:
    """An empty (marker-only) workspace produces no relation lines."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: empty\n", encoding="utf-8")
    result = runner.invoke(map_app, ["relation", "list", "--workspace", str(tmp_path)])
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if "x-" in line]
    assert lines == []


# ---------------------------------------------------------------------------
# T7.2: amanuensis map relation show <id>
# ---------------------------------------------------------------------------


def test_show_renders_endpoints_warrant_supersede_chain(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """``relation show <id>`` prints endpoints, warrant, shared entities."""
    workspace = tmp_workspace_with_two_cross_doc_relations
    rel = next(iter(Substrate(workspace).list_cross_doc_relations()))
    result = runner.invoke(
        map_app,
        ["relation", "show", rel.id, "--workspace", str(workspace)],
    )
    assert result.exit_code == 0, result.output
    assert rel.from_atom_id in result.stdout
    assert rel.to_atom_id in result.stdout
    assert rel.warrant in result.stdout
    for entity_id in rel.shared_entities:
        assert entity_id in result.stdout


def test_show_returns_error_for_unknown_id(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """``relation show`` on an unknown id exits non-zero with a 'not found' message."""
    workspace = tmp_workspace_with_two_cross_doc_relations
    result = runner.invoke(
        map_app,
        ["relation", "show", "x-nonexistent", "--workspace", str(workspace)],
    )
    assert result.exit_code != 0
    haystack = (result.stdout or "") + (result.stderr or "")
    assert "not found" in haystack.lower()


def test_show_renders_supersede_chain_section(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """The supersede-chain section header always appears on the detail view."""
    workspace = tmp_workspace_with_two_cross_doc_relations
    rel = next(iter(Substrate(workspace).list_cross_doc_relations()))
    result = runner.invoke(
        map_app,
        ["relation", "show", rel.id, "--workspace", str(workspace)],
    )
    assert result.exit_code == 0, result.output
    assert "Supersede chain" in result.stdout


# ---------------------------------------------------------------------------
# T7.3: amanuensis map relation supersede <old-id> <new-id> --reason "..."
# ---------------------------------------------------------------------------


def test_supersede_writes_supersede_record(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """The supersede verb commits a CrossDocRelationSupersede and re-routes the chain."""
    workspace = tmp_workspace_with_two_cross_doc_relations
    sub = Substrate(workspace)
    rels = list(sub.list_cross_doc_relations())
    old, new = rels[0], rels[1]
    result = runner.invoke(
        map_app,
        [
            "relation",
            "supersede",
            old.id,
            new.id,
            "--reason",
            "test correction",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code == 0, result.output
    terminus = sub.latest_cross_doc_relation_for(old.id)
    assert terminus is not None
    assert terminus.id == new.id


def test_supersede_requires_reason_flag(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """Omitting ``--reason`` exits non-zero (Typer required-option error)."""
    workspace = tmp_workspace_with_two_cross_doc_relations
    sub = Substrate(workspace)
    rels = list(sub.list_cross_doc_relations())
    result = runner.invoke(
        map_app,
        [
            "relation",
            "supersede",
            rels[0].id,
            rels[1].id,
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code != 0


def test_supersede_rejects_unknown_old_id(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """An unknown ``<old-id>`` is rejected before any write happens."""
    workspace = tmp_workspace_with_two_cross_doc_relations
    result = runner.invoke(
        map_app,
        [
            "relation",
            "supersede",
            "x-nonexistent",
            "x-also-nonexistent",
            "--reason",
            "r",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code != 0


def test_supersede_rejects_unknown_new_id(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """An unknown ``<new-id>`` is rejected before any write happens."""
    workspace = tmp_workspace_with_two_cross_doc_relations
    sub = Substrate(workspace)
    rels = list(sub.list_cross_doc_relations())
    result = runner.invoke(
        map_app,
        [
            "relation",
            "supersede",
            rels[0].id,
            "x-nonexistent",
            "--reason",
            "r",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code != 0


def test_supersede_already_superseded_rejected(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """Once a relation is superseded, a second supersede on the old id is refused."""
    workspace = tmp_workspace_with_two_cross_doc_relations
    sub = Substrate(workspace)
    rels = list(sub.list_cross_doc_relations())
    old, new = rels[0], rels[1]
    # First supersede succeeds.
    first = runner.invoke(
        map_app,
        [
            "relation",
            "supersede",
            old.id,
            new.id,
            "--reason",
            "first",
            "--workspace",
            str(workspace),
        ],
    )
    assert first.exit_code == 0, first.output
    # Second supersede on the same already-superseded id fails.
    second = runner.invoke(
        map_app,
        [
            "relation",
            "supersede",
            old.id,
            new.id,
            "--reason",
            "second",
            "--workspace",
            str(workspace),
        ],
    )
    assert second.exit_code != 0


def test_supersede_dry_run_writes_nothing(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """``--dry-run`` prints the plan without touching the substrate."""
    workspace = tmp_workspace_with_two_cross_doc_relations
    sub = Substrate(workspace)
    rels = list(sub.list_cross_doc_relations())
    old, new = rels[0], rels[1]
    result = runner.invoke(
        map_app,
        [
            "relation",
            "supersede",
            old.id,
            new.id,
            "--reason",
            "dry",
            "--dry-run",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.stdout.lower()
    # No supersede record was written.
    terminus = sub.latest_cross_doc_relation_for(old.id)
    assert terminus is not None
    assert terminus.id == old.id


# ---------------------------------------------------------------------------
# Help discoverability — sanity check on the new sub-app
# ---------------------------------------------------------------------------


def test_map_relation_help_lists_verbs() -> None:
    """``map relation --help`` lists the three new verbs."""
    result = runner.invoke(map_app, ["relation", "--help"])
    assert result.exit_code == 0, result.output
    for verb in ("list", "show", "supersede"):
        assert verb in result.stdout
