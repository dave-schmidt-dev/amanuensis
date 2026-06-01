"""Static-export additions for Phase 2b cross-doc relations (M9).

T9.1 — A workspace-level appendix file ``cross-doc-relations.html`` is
produced under the export bundle directory, listing every
``CrossDocRelation`` in the substrate grouped by ``kind``.

T9.4 — Self-containment: no CDN URLs in the rendered pages. Verified
inline here for the appendix; T9.2's per-entity tests verify the same
for the entity bundle pages.

Implementation note
-------------------

Phase 1's ``export_static_html`` is a per-source single-file exporter.
Phase 2b M9 adds a complementary workspace-level bundle exporter,
``export_workspace_appendix``, that emits the cross-doc relations
appendix and per-entity pages into a directory. The single-file
exporter is unchanged; the new bundle is the home of any cross-source
content (which by definition has no single "source" home).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from amanuensis.export import export_workspace_appendix
from amanuensis.fs import Substrate

_FROZEN_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# T9.1 — cross-doc-relations.html appendix page
# ---------------------------------------------------------------------------


def test_export_writes_cross_doc_relations_page(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """Bundle directory contains a ``cross-doc-relations.html`` appendix."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    page = out_dir / "cross-doc-relations.html"
    assert page.is_file(), f"cross-doc-relations.html missing under {out_dir}"
    content = page.read_text(encoding="utf-8")
    assert content.startswith("<!DOCTYPE html>")
    # At least one kind label rendered.
    assert "supports" in content
    assert "attacks" in content
    # x- prefix tells us at least one relation id is rendered.
    assert "x-" in content


def test_export_page_lists_all_relations(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """Every CrossDocRelation in the substrate appears on the appendix page."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    page = out_dir / "cross-doc-relations.html"
    content = page.read_text(encoding="utf-8")
    relations = list(substrate.list_cross_doc_relations())
    assert len(relations) == 2, "fixture should plant exactly 2 cross-doc relations"
    for rel in relations:
        assert rel.id in content, f"relation {rel.id} missing from appendix page"
        # Warrant text is rendered as well so a supervisor can read the
        # bundle without round-tripping to the web app.
        assert rel.warrant in content, f"warrant of {rel.id} missing from appendix page"


def test_appendix_page_renders_kind_groups(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """Each Phase 2b ``kind`` (supports / attacks / undercuts) gets a section heading."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    content = (out_dir / "cross-doc-relations.html").read_text(encoding="utf-8")
    # Two kinds present in the fixture (supports + attacks); the third
    # kind (undercuts) has no records but its section may still render
    # with an empty placeholder — implementation is free either way, but
    # the two present kinds MUST appear as headings.
    assert "supports" in content
    assert "attacks" in content


def test_appendix_page_links_shared_entities(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """Each appendix entry links its shared entities to the per-entity pages."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    content = (out_dir / "cross-doc-relations.html").read_text(encoding="utf-8")
    # The fixture's shared entity is ``e-smith``; the appendix should
    # link to ``entities/e-smith.html``.
    assert 'href="entities/e-smith.html"' in content


# ---------------------------------------------------------------------------
# T9.4 — Self-contained HTML (no CDN URLs) — absorbed here per spec
# ---------------------------------------------------------------------------


def test_appendix_page_is_self_contained(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """No external network references in the appendix page."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    text = (out_dir / "cross-doc-relations.html").read_text(encoding="utf-8")
    forbidden_hosts = (
        "unpkg.com",
        "cdn.jsdelivr.net",
        "cdnjs.cloudflare.com",
        "googleapis.com",
        "gstatic.com",
        "jsdelivr.net",
    )
    for host in forbidden_hosts:
        assert host not in text, f"CDN reference to {host!r} leaked into appendix page"
    # Belt-and-braces: no stray http(s):// resource link.
    assert "https://" not in text, "external https:// URL leaked into appendix page"
    assert "http://" not in text, "external http:// URL leaked into appendix page"
