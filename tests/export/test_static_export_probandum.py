"""Static-export additions for Phase 2c probandum hierarchy (M11).

T11.1 — A workspace-level appendix file ``probandum-tree.html`` is
produced under the export bundle directory, with one section per
ultimate probandum rendering the full subtree as nested ``<details>``.
Edges to atom leaves link to the Phase 1 per-source export page;
edges to cross-doc-relation leaves link to the Phase 2b appendix
anchor.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from amanuensis.export import export_workspace_appendix
from amanuensis.fs import Substrate

_FROZEN_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# T11.1 — probandum-tree.html appendix page
# ---------------------------------------------------------------------------


def test_export_writes_probandum_tree_page(
    tmp_workspace_with_probandum_tree_for_export: Path,
    tmp_path: Path,
) -> None:
    """Bundle directory contains a ``probandum-tree.html`` page that lists the tree."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_probandum_tree_for_export)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    page = out_dir / "probandum-tree.html"
    assert page.is_file(), f"probandum-tree.html missing under {out_dir}"
    content = page.read_text(encoding="utf-8")
    assert content.startswith("<!DOCTYPE html>")

    probanda = list(substrate.list_probanda())
    ultimates = [p for p in probanda if p.kind == "ultimate"]
    assert ultimates, "fixture should plant at least one ultimate probandum"
    interims = [p for p in probanda if p.kind == "interim"]
    assert interims, "fixture should plant at least one interim probandum"

    # Ultimate id is present (as anchor + as <code> body) and so is its
    # statement excerpt.
    for ultimate in ultimates:
        assert f"ultimate-{ultimate.id}" in content, f"missing #ultimate-{ultimate.id} anchor"
        # Statement excerpt — the first 40 chars of the statement will
        # appear (the heading uses an 80-char excerpt).
        assert ultimate.statement[:40] in content, (
            "ultimate statement excerpt missing from probandum-tree.html"
        )

    # Interim statements appear in the rendered subtree.
    for interim in interims:
        assert interim.statement[:40] in content, (
            "interim statement excerpt missing from probandum-tree.html"
        )


def test_export_writes_empty_placeholder_when_no_ultimate(
    tmp_path: Path,
) -> None:
    """Workspaces with no ultimate probandum get a placeholder section.

    A fresh workspace (no probanda, no edges) MUST still emit a
    ``probandum-tree.html`` page so the bundle's file-shape is stable;
    the page renders an explicit "no ultimate probandum yet"
    placeholder so the supervisor knows what to do next.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: m11-empty\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_path)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    page = out_dir / "probandum-tree.html"
    assert page.is_file(), "probandum-tree.html should exist even with no probanda"
    content = page.read_text(encoding="utf-8")
    assert "No probandum tree yet" in content
    assert "amanuensis map probandum add" in content
    # The placeholder should be a recognisable section anchor for tests
    # and for the empty-state UX itself.
    assert 'id="no-ultimate"' in content


def test_export_links_to_atom_pages(
    tmp_workspace_with_probandum_tree_for_export: Path,
    tmp_path: Path,
) -> None:
    """Atom-child edges link to ``../<source_id>.html#atom-<id>`` (Phase 1 per-source page).

    The probandum-tree appendix lives at the bundle root; the per-source
    static export pages live one directory up by convention, so atom
    links are rendered as ``../<source>.html#atom-<id>``.
    """
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_probandum_tree_for_export)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    content = (out_dir / "probandum-tree.html").read_text(encoding="utf-8")
    # The fixture's atom-child has id ``a-m11atom00000001`` under
    # ``src-A``; the appendix must link to it.
    assert "../src-A.html#atom-a-m11atom00000001" in content, (
        "probandum-tree should link atom-children to "
        "../<source>.html#atom-<id> (Phase 1 per-source export page)"
    )


def test_export_links_to_cross_doc_relations(
    tmp_workspace_with_probandum_tree_for_export: Path,
    tmp_path: Path,
) -> None:
    """Cross-doc-relation child edges link to ``cross-doc-relations.html#relation-<id>``."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_probandum_tree_for_export)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    content = (out_dir / "probandum-tree.html").read_text(encoding="utf-8")
    relations = list(substrate.list_cross_doc_relations())
    assert relations, "fixture should plant one cross-doc-relation"
    rel = relations[0]
    # The fixture's sole cross-doc-relation must be linked from the
    # probandum-tree page via the bundle convention.
    assert f"cross-doc-relations.html#relation-{rel.id}" in content, (
        f"cross-doc-relation {rel.id} not linked from probandum-tree.html"
    )
