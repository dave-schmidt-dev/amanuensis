"""Static-export additions for Phase 2c probandum hierarchy (M11).

T11.1 — A workspace-level appendix file ``probandum-tree.html`` is
produced under the export bundle directory, with one section per
ultimate probandum rendering the full subtree as nested ``<details>``.

T11.2 — One ``probanda/<id>.html`` page per Probandum showing
ancestry (incoming edges up to the ultimate) and descendants
(outgoing subtree).

T11.3 — INV-8 render purity extended to the new probandum-tree
fixture: two consecutive runs over the same substrate produce
byte-identical files for every emitted page. Self-containment is
re-asserted for the new pages (no CDN URLs, no inline JS, no external
network references).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from amanuensis.export import export_workspace_appendix
from amanuensis.fs import Substrate

_FROZEN_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

# Forbidden hosts mirror the M9 self-containment test set. Kept in sync
# so any future CDN attempt fails uniformly across the bundle.
_FORBIDDEN_HOSTS: tuple[str, ...] = (
    "unpkg.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "googleapis.com",
    "gstatic.com",
    "jsdelivr.net",
)


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
        # Statement excerpt — the first 60 chars of the statement at minimum
        # will appear (the heading uses an 80-char excerpt).
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


# ---------------------------------------------------------------------------
# T11.2 — Per-probandum lineage pages
# ---------------------------------------------------------------------------


def test_export_writes_per_probandum_page(
    tmp_workspace_with_probandum_tree_for_export: Path,
    tmp_path: Path,
) -> None:
    """Each Probandum gets its own ``probanda/<id>.html`` page."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_probandum_tree_for_export)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    probanda = list(substrate.list_probanda())
    assert len(probanda) >= 3, "fixture should plant at least 3 probanda"
    for p in probanda:
        page = out_dir / "probanda" / f"{p.id}.html"
        assert page.is_file(), f"per-probandum page missing at {page}"
        content = page.read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        # Statement body is in the page.
        assert p.statement in content, f"statement of {p.id} missing from per-probandum page"
        # Id is in the page.
        assert p.id in content


def test_per_probandum_page_renders_ancestry(
    tmp_workspace_with_probandum_tree_for_export: Path,
    tmp_path: Path,
) -> None:
    """The interim probandum's page shows its ancestors up to the ultimate.

    Walks the fixture tree: the interim's ancestry chain MUST contain
    the penultimate AND the ultimate. The page renders the chain
    explicitly under an "Ancestry" section.
    """
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_probandum_tree_for_export)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    probanda = list(substrate.list_probanda())
    interims = [p for p in probanda if p.kind == "interim"]
    ultimates = [p for p in probanda if p.kind == "ultimate"]
    penultimates = [p for p in probanda if p.kind == "penultimate"]
    assert interims and ultimates and penultimates

    interim_page = out_dir / "probanda" / f"{interims[0].id}.html"
    content = interim_page.read_text(encoding="utf-8")

    assert "Ancestry" in content, "Ancestry section missing from interim page"
    # Both upward-chain ids appear in the page (link href is
    # ``<id>.html`` which trivially contains the id).
    for ancestor in (ultimates[0], penultimates[0]):
        assert ancestor.id in content, (
            f"ancestor {ancestor.id} ({ancestor.kind}) missing from interim's page"
        )


def test_per_probandum_page_renders_descendants(
    tmp_workspace_with_probandum_tree_for_export: Path,
    tmp_path: Path,
) -> None:
    """The ultimate's page shows its descendants down to the leaves.

    The ultimate's descendants section MUST mention the penultimate and
    the interim (both probandum children, transitively). The atom and
    cross-doc-relation leaves attach to the interim.
    """
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_probandum_tree_for_export)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    probanda = list(substrate.list_probanda())
    ultimates = [p for p in probanda if p.kind == "ultimate"]
    penultimates = [p for p in probanda if p.kind == "penultimate"]
    interims = [p for p in probanda if p.kind == "interim"]
    assert ultimates and penultimates and interims

    ultimate_page = out_dir / "probanda" / f"{ultimates[0].id}.html"
    content = ultimate_page.read_text(encoding="utf-8")
    assert "Descendants" in content, "Descendants section missing from ultimate page"
    # Penultimate + interim ids appear (descended into via the nested
    # <details> blocks).
    for descendant in (penultimates[0], interims[0]):
        assert descendant.id in content, (
            f"descendant {descendant.id} ({descendant.kind}) missing from ultimate's page"
        )


# ---------------------------------------------------------------------------
# T11.3 — INV-8 render purity (byte-identical across two runs)
# ---------------------------------------------------------------------------


def test_render_purity_with_probandum_tree(
    tmp_workspace_with_probandum_tree_for_export: Path,
    tmp_path: Path,
) -> None:
    """Two consecutive export runs yield byte-identical bundle files.

    Mirrors the Phase 2b M9 ``test_render_purity_with_cross_doc_relation``
    but extended to the M11 probandum tree fixture: file set AND bytes
    must match across two runs of ``export_workspace_appendix`` with a
    frozen ``now``.
    """
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    substrate = Substrate(tmp_workspace_with_probandum_tree_for_export)

    export_workspace_appendix(substrate=substrate, out_dir=out_a, now=_FROZEN_NOW)
    export_workspace_appendix(substrate=substrate, out_dir=out_b, now=_FROZEN_NOW)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*") if p.is_file())
    assert files_a == files_b, f"bundle file set differs across runs:\n  a={files_a}\n  b={files_b}"
    # Sanity: both the new probandum-tree page and at least one per-probandum
    # page should be in the file set.
    relposix = [p.as_posix() for p in files_a]
    assert "probandum-tree.html" in relposix
    assert any(rp.startswith("probanda/") and rp.endswith(".html") for rp in relposix)

    for rel_path in files_a:
        bytes_a = (out_a / rel_path).read_bytes()
        bytes_b = (out_b / rel_path).read_bytes()
        assert bytes_a == bytes_b, f"{rel_path} differs across two render runs (INV-8)"


def test_probandum_tree_page_is_self_contained(
    tmp_workspace_with_probandum_tree_for_export: Path,
    tmp_path: Path,
) -> None:
    """No CDN URLs / external links leak into ``probandum-tree.html``.

    Matches the Phase 2a/2b self-contained-HTML discipline: the bundle
    must open offline, no external network references baked in.
    """
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_probandum_tree_for_export)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    content = (out_dir / "probandum-tree.html").read_text(encoding="utf-8")
    for host in _FORBIDDEN_HOSTS:
        assert host not in content, f"CDN reference to {host!r} leaked into probandum-tree.html"
    assert "https://" not in content, "external https:// URL leaked into probandum-tree.html"
    assert "http://" not in content, "external http:// URL leaked into probandum-tree.html"


def test_per_probandum_page_is_self_contained(
    tmp_workspace_with_probandum_tree_for_export: Path,
    tmp_path: Path,
) -> None:
    """No CDN URLs / external links leak into any ``probanda/<id>.html`` page."""
    out_dir = tmp_path / "export"
    substrate = Substrate(tmp_workspace_with_probandum_tree_for_export)
    export_workspace_appendix(substrate=substrate, out_dir=out_dir, now=_FROZEN_NOW)

    for page in (out_dir / "probanda").glob("*.html"):
        content = page.read_text(encoding="utf-8")
        for host in _FORBIDDEN_HOSTS:
            assert host not in content, f"CDN reference to {host!r} leaked into {page.name}"
        assert "https://" not in content, f"external https:// URL leaked into {page.name}"
        assert "http://" not in content, f"external http:// URL leaked into {page.name}"
