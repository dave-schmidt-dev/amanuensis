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
# T9.2 — Per-entity edge listing on entity pages
# ---------------------------------------------------------------------------


def test_entity_page_exists_per_canonical_entity(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """One ``entities/<id>.html`` page per canonical entity."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    entity_page = out_dir / "entities" / "e-smith.html"
    assert entity_page.is_file(), f"per-entity page missing at {entity_page}"
    content = entity_page.read_text(encoding="utf-8")
    assert content.startswith("<!DOCTYPE html>")


def test_entity_page_lists_cross_doc_edges(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """Entity page has a 'Cross-doc edges' section listing each relation touching it."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    content = (out_dir / "entities" / "e-smith.html").read_text(encoding="utf-8")
    # Section heading present.
    assert "Cross-doc edges" in content or "cross-doc edges" in content.lower()
    # Each relation citing e-smith in shared_entities appears on the page.
    for rel in substrate.list_cross_doc_relations(shared_entity="e-smith"):
        assert rel.id in content, (
            f"relation {rel.id} missing from per-entity page despite "
            "citing e-smith in shared_entities"
        )


def test_entity_page_links_back_to_appendix(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """Entity page links its cross-doc edges to anchored rows on the appendix page."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    content = (out_dir / "entities" / "e-smith.html").read_text(encoding="utf-8")
    # At least one relation link points back to the appendix page anchor.
    relations = list(substrate.list_cross_doc_relations(shared_entity="e-smith"))
    assert relations, "fixture should produce at least one e-smith edge"
    first = relations[0]
    assert f"../cross-doc-relations.html#relation-{first.id}" in content


def test_entity_page_canonical_name_present(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """Entity page shows the canonical name as a heading."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    content = (out_dir / "entities" / "e-smith.html").read_text(encoding="utf-8")
    assert "Smith" in content


def test_entity_page_is_self_contained(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """Per-entity page has no CDN URLs (T9.4 coverage for entity bundle pages)."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    text = (out_dir / "entities" / "e-smith.html").read_text(encoding="utf-8")
    forbidden_hosts = (
        "unpkg.com",
        "cdn.jsdelivr.net",
        "cdnjs.cloudflare.com",
        "googleapis.com",
        "gstatic.com",
        "jsdelivr.net",
    )
    for host in forbidden_hosts:
        assert host not in text, f"CDN reference to {host!r} leaked into entity page"
    assert "https://" not in text, "external https:// URL leaked into entity page"
    assert "http://" not in text, "external http:// URL leaked into entity page"


# ---------------------------------------------------------------------------
# T9.3 — INV-8 render-purity (byte-identical across two runs)
# ---------------------------------------------------------------------------


def test_render_purity_with_cross_doc_relation(
    tmp_workspace_with_two_cross_doc_relations: Path,
    tmp_path: Path,
) -> None:
    """Two consecutive runs produce byte-identical files in the bundle.

    Walks every emitted file (appendix + every per-entity page),
    asserting that the file set AND the bytes of every file are
    identical across two runs of ``export_workspace_appendix`` with
    a frozen timestamp.
    """
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    substrate = Substrate(tmp_workspace_with_two_cross_doc_relations)

    export_workspace_appendix(substrate=substrate, out_dir=out_a, now=_FROZEN_NOW)
    export_workspace_appendix(substrate=substrate, out_dir=out_b, now=_FROZEN_NOW)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*") if p.is_file())
    assert files_a == files_b, f"bundle file set differs across runs:\n  a={files_a}\n  b={files_b}"
    for rel_path in files_a:
        bytes_a = (out_a / rel_path).read_bytes()
        bytes_b = (out_b / rel_path).read_bytes()
        assert bytes_a == bytes_b, f"{rel_path} differs across two render runs (INV-8)"


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
