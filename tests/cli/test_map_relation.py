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
# Help discoverability — sanity check on the new sub-app
# ---------------------------------------------------------------------------


def test_map_relation_help_lists_list_verb() -> None:
    """``map relation --help`` lists the ``list`` verb (T7.1)."""
    result = runner.invoke(map_app, ["relation", "--help"])
    assert result.exit_code == 0, result.output
    assert "list" in result.stdout
