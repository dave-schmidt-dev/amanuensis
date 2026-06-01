"""Workspace-level static export bundle — Phase 2b M9 + Phase 2c M11.

Phase 1's :func:`amanuensis.export.export_static_html` is a per-source
single-file exporter: one HTML file per distillation, with that
distillation's paragraphs / atoms / relations inline. Phase 2b adds
cross-document content (``CrossDocRelation`` records) that has no
single-source home — by definition each one touches two sources.
Phase 2c adds argument-hierarchy content (``Probandum`` /
``ProbandumEdge`` records) that lives in the mappings namespace and
likewise has no single-source home.

This module emits a workspace-level *bundle*: a directory containing

- ``cross-doc-relations.html`` — appendix listing every
  ``CrossDocRelation`` in the substrate, grouped by ``kind`` (one of
  ``supports`` / ``attacks`` / ``undercuts``). Each row anchors at
  ``#relation-<id>``.
- ``entities/<entity_id>.html`` — one page per canonical entity (the
  terminal node of every supersede chain), with a "Cross-doc edges
  touching this entity" section that mirrors the web app's
  ``entity_detail.html`` layout.
- ``probandum-tree.html`` (Phase 2c M11) — appendix rendering each
  ultimate probandum's subtree as nested HTML5 ``<details>`` blocks.
  Atoms link to ``../<source_id>.html#atom-<id>`` (Phase 1 per-source
  pages); cross-doc-relation leaves link to
  ``cross-doc-relations.html#relation-<id>``.
- ``probanda/<probandum_id>.html`` (Phase 2c M11) — one page per
  Probandum showing statement, scheme, alternatives, confidence,
  ancestry (incoming edges up to the ultimate), and descendants
  (outgoing edges down to the leaves).

The bundle is *self-contained*: same CSS-in-`<style>` discipline as
Phase 1, no CDN URLs, no external network references. Pages link to
sibling pages via relative paths (``entities/<id>.html`` from the
appendix; ``../cross-doc-relations.html#relation-<id>`` from the
entity pages; ``../probandum-tree.html#ultimate-<id>`` from the
per-probandum pages).

INV-8 (substrate is source of truth; renderings are pure functions of
state) is the load-bearing invariant: two runs over the same substrate
must produce byte-identical files. Tests in
``tests/export/test_static_export_cross_doc.py`` and
``tests/export/test_static_export_probandum.py`` assert this.

Output mode is ``0644`` to match the per-source exporter — bundles are
meant to be shared.
"""

from __future__ import annotations

import html
import os
import stat
from collections import defaultdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from amanuensis.fs import Substrate
from amanuensis.schemas import Atom, CrossDocRelation, Entity, Probandum, ProbandumEdge

# Output file mode — group / world readable; owner writable. Matches
# the per-source exporter so the bundle's files share a single mode.
_OUTPUT_MODE: int = 0o644

# The closed set of cross-doc kinds — mirrors the schema's Literal type.
# Rendering iterates this in a fixed order so the produced HTML is
# deterministic regardless of dict-iteration order.
_CROSS_DOC_KINDS: tuple[str, ...] = ("supports", "attacks", "undercuts")

# Maximum chars for excerpted probandum / atom statements in the tree
# view. Long statements are truncated at the nearest word boundary with
# an ellipsis suffix so the nested ``<details>`` summaries stay scannable.
_PROBANDUM_EXCERPT_CHARS: int = 140

# Defensive depth-cap on subtree traversal. Wigmore trees in practice
# are shallow; this guards against any pathological graph the write-time
# gates failed to catch (INV-16 acyclicity is already enforced, but the
# renderer must not lock up regardless).
_TREE_MAX_DEPTH: int = 100


def _package_version() -> str:
    """Best-effort amanuensis distribution version (or ``"unknown"``)."""
    try:
        return version("amanuensis")
    except PackageNotFoundError:  # pragma: no cover - dev-env glitch
        return "unknown"


def _esc(value: object) -> str:
    """HTML-escape any value via its ``str()`` form."""
    return html.escape(str(value), quote=True)


# The bundle uses the same neutral light/dark CSS as the per-source
# exporter, kept inline so each page is fully self-contained. Pages
# under ``entities/`` re-inline the same stylesheet — duplicating the
# CSS is the simplest path to "one HTML file, no external assets".
_BUNDLE_CSS = """\
:root {
  color-scheme: light dark;
  --bg: #0f1115;
  --fg: #e6e6e6;
  --muted: #9aa0a6;
  --accent: #7aa2f7;
  --border: #2a2f3a;
  --card: #161922;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #fafafa;
    --fg: #1a1a1a;
    --muted: #555;
    --accent: #1f6feb;
    --border: #d0d7de;
    --card: #ffffff;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg); }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, sans-serif;
  line-height: 1.5;
  padding: 1.5rem 2rem 4rem;
  max-width: 60rem;
  margin: 0 auto;
}
h1, h2, h3 { font-weight: 600; }
h1 { margin: 0 0 0.5rem; font-size: 1.6rem; }
h2 {
  margin: 2rem 0 0.75rem;
  font-size: 1.25rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.25rem;
}
h3 { margin: 1rem 0 0.5rem; font-size: 1rem; color: var(--muted); }
header.summary {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}
header.summary dl {
  margin: 0;
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.25rem 1rem;
}
header.summary dt { color: var(--muted); }
header.summary dd { margin: 0; word-break: break-all; }
ul.relations { list-style: none; padding: 0; }
ul.relations li {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.6rem 0.9rem;
  margin-bottom: 0.5rem;
}
.tag {
  display: inline-block;
  font-size: 0.75rem;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  border: 1px solid var(--border);
  color: var(--muted);
  margin-right: 0.4rem;
}
.predicate { color: var(--accent); font-weight: 600; }
.empty { color: var(--muted); font-style: italic; }
a { color: var(--accent); }
a.entity-link {
  color: #e07b39;
  text-decoration: none;
  border-bottom: 1px dashed #e07b39;
}
a.entity-link:hover { text-decoration: underline; }
a.probandum-link {
  color: #4fb286;
  text-decoration: none;
  border-bottom: 1px dashed #4fb286;
}
a.probandum-link:hover { text-decoration: underline; }
details.probandum-node {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.4rem 0.7rem;
  margin: 0.4rem 0;
}
details.probandum-node > summary {
  cursor: pointer;
  font-weight: 500;
  margin: 0.1rem 0;
}
details.probandum-node ul.children {
  list-style: none;
  padding-left: 0.8rem;
  margin: 0.3rem 0 0;
  border-left: 2px solid var(--border);
}
details.probandum-node ul.children > li {
  margin: 0.3rem 0;
}
.edge-meta {
  font-size: 0.8rem;
  color: var(--muted);
  margin: 0.2rem 0 0.2rem 0.2rem;
}
.kind-badge {
  display: inline-block;
  font-size: 0.7rem;
  padding: 0.05rem 0.4rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  margin-right: 0.4rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.kind-badge.ultimate { color: #c97aff; border-color: #c97aff; }
.kind-badge.penultimate { color: #7aa2f7; border-color: #7aa2f7; }
.kind-badge.interim { color: #4fb286; border-color: #4fb286; }
.kind-badge.atom { color: #e0b343; border-color: #e0b343; }
.kind-badge.cross-doc-relation { color: #e07b39; border-color: #e07b39; }
.probandum-statement { display: block; margin: 0.2rem 0; }
.lineage-chain {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0;
}
.lineage-chain > li {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.4rem 0.7rem;
  margin: 0.3rem 0;
}
.lineage-chain > li::before {
  content: "↑ ";
  color: var(--muted);
  margin-right: 0.3rem;
}
footer {
  margin-top: 3rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.8rem;
}
"""


def _render_footer(generated_at: datetime, version_string: str) -> str:
    """Render the standard "generated by amanuensis vX at TIMESTAMP" footer."""
    return (
        "<footer>Generated by amanuensis "
        f"v{_esc(version_string)} at "
        f"{_esc(generated_at.isoformat(timespec='seconds'))}</footer>"
    )


def _shared_entities_html(
    rel: CrossDocRelation,
    *,
    entity_page_prefix: str,
    canonical_entity_ids: set[str],
) -> str:
    """Render the ``shared_entities`` list as comma-separated links.

    Links targeting canonical entities (those with a per-entity bundle
    page) become ``<a href="entities/<id>.html" class="entity-link">``;
    non-canonical or superseded ids fall back to plain ``<code>``
    spans so superseded ids in a CrossDocRelation's ``shared_entities``
    list don't produce a broken anchor.

    ``entity_page_prefix`` lets entity-page renderings emit
    ``"../entities/<id>.html"`` while the appendix uses
    ``"entities/<id>.html"``. Both forms resolve to the same on-disk
    file from the page that contains them.
    """
    if not rel.shared_entities:
        return '<span class="empty">none</span>'
    parts: list[str] = []
    for ent_id in rel.shared_entities:
        if ent_id in canonical_entity_ids:
            parts.append(
                f'<a class="entity-link" href="{entity_page_prefix}{_esc(ent_id)}.html">'
                f"{_esc(ent_id)}</a>"
            )
        else:
            parts.append(f"<code>{_esc(ent_id)}</code>")
    return ", ".join(parts)


def _render_relation_row(
    rel: CrossDocRelation,
    *,
    entity_page_prefix: str,
    canonical_entity_ids: set[str],
) -> str:
    """Render one ``<li>`` row inside the appendix's per-kind ``<ul>``.

    Shape (mirrors the web app's cross-doc list, simplified for
    bundle-static):

      - id anchor (#relation-<id>)
      - kind / confidence tags
      - from atom → to atom
      - warrant text
      - shared-entity link list
    """
    kind_tag = f'<span class="tag">{_esc(rel.kind)}</span>'
    conf_tag = f'<span class="tag">conf={_esc(rel.confidence)}</span>'
    defens_tag = f'<span class="tag">defensibility={_esc(rel.warrant_defensibility)}</span>'
    shared_html = _shared_entities_html(
        rel,
        entity_page_prefix=entity_page_prefix,
        canonical_entity_ids=canonical_entity_ids,
    )
    return (
        f'<li id="relation-{_esc(rel.id)}">'
        f"{kind_tag}{conf_tag}{defens_tag}"
        f"<div><code>{_esc(rel.from_source_id)} / {_esc(rel.from_atom_id)}</code>"
        f' → <span class="predicate">{_esc(rel.kind)}</span> → '
        f"<code>{_esc(rel.to_source_id)} / {_esc(rel.to_atom_id)}</code></div>"
        f'<div class="warrant">warrant: {_esc(rel.warrant)}</div>'
        f'<div class="warrant-basis">basis: {_esc(rel.warrant_basis)}</div>'
        f'<div class="shared-entities">shared entities: {shared_html}</div>'
        f'<div class="relation-id"><code>{_esc(rel.id)}</code></div>'
        "</li>"
    )


def _canonical_entities(substrate: Substrate) -> list[Entity]:
    """Walk ``mappings/entities/`` and return only canonical entities.

    An entity is canonical iff ``latest_entity_for(e.id).id == e.id``.
    Ordering is by ``canonical_name`` then ``id`` for deterministic
    rendering across runs / platforms.
    """
    canonical: list[Entity] = []
    for entity in substrate.list_entities():
        try:
            terminus = substrate.latest_entity_for(entity.id)
        except Exception:
            continue
        if terminus.id == entity.id:
            canonical.append(entity)
    canonical.sort(key=lambda e: (e.canonical_name, e.id))
    return canonical


def _group_relations_by_kind(
    relations: list[CrossDocRelation],
) -> dict[str, list[CrossDocRelation]]:
    """Group relations by ``kind`` with deterministic per-group ordering."""
    grouped: dict[str, list[CrossDocRelation]] = defaultdict(list)
    for rel in relations:
        grouped[rel.kind].append(rel)
    for kind in grouped:
        grouped[kind].sort(key=lambda r: r.id)
    return grouped


def _render_appendix_page(
    *,
    relations: list[CrossDocRelation],
    canonical_entity_ids: set[str],
    generated_at: datetime,
    version_string: str,
) -> str:
    """Render the ``cross-doc-relations.html`` appendix page."""
    grouped = _group_relations_by_kind(relations)
    summary = (
        '<header class="summary">'
        "<h1>Cross-doc relations</h1>"
        "<dl>"
        f"<dt>total relations</dt><dd>{len(relations)}</dd>"
        f"<dt>kinds</dt><dd>{', '.join(_esc(k) for k in _CROSS_DOC_KINDS)}</dd>"
        "</dl>"
        "</header>"
    )

    sections: list[str] = []
    if not relations:
        sections.append('<p class="empty">No cross-doc relations in this workspace.</p>')
    else:
        for kind in _CROSS_DOC_KINDS:
            entries = grouped.get(kind, [])
            if not entries:
                # Render an explicit empty section so the page shape is
                # stable: every kind appears even when its count is 0.
                # This also gives supervisors a confirmation that the
                # absence is real, not a render glitch.
                sections.append(
                    f'<h2 id="kind-{_esc(kind)}">{_esc(kind)}</h2>'
                    f'<p class="empty">No {_esc(kind)} relations.</p>'
                )
                continue
            rows = "".join(
                _render_relation_row(
                    rel,
                    entity_page_prefix="entities/",
                    canonical_entity_ids=canonical_entity_ids,
                )
                for rel in entries
            )
            sections.append(
                f'<h2 id="kind-{_esc(kind)}">{_esc(kind)} '
                f'<span class="tag">{len(entries)}</span></h2>'
                f'<ul class="relations">{rows}</ul>'
            )

    footer = _render_footer(generated_at, version_string)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>amanuensis — cross-doc relations</title>\n"
        f"<style>{_BUNDLE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{summary}\n" + "\n".join(sections) + f"\n{footer}\n"
        "</body>\n"
        "</html>\n"
    )


def _render_entity_page(
    *,
    entity: Entity,
    relations: list[CrossDocRelation],
    canonical_entity_ids: set[str],
    generated_at: datetime,
    version_string: str,
) -> str:
    """Render one ``entities/<id>.html`` page for a canonical entity.

    The page shows entity metadata + a "Cross-doc edges touching this
    entity" section. Mirrors the web app's ``entity_detail.html``
    layout but trimmed: no resolutions table, no supersede chain
    annotation — those concerns belong on the web surface, not the
    bundle.
    """
    grouped = _group_relations_by_kind(relations)
    aliases_html: str
    if entity.aliases:
        aliases_html = ", ".join(_esc(a) for a in entity.aliases)
    else:
        aliases_html = '<span class="empty">none</span>'

    summary = (
        '<header class="summary">'
        f"<h1>{_esc(entity.canonical_name)}</h1>"
        "<dl>"
        f"<dt>id</dt><dd><code>{_esc(entity.id)}</code></dd>"
        f"<dt>kind</dt><dd>{_esc(entity.kind)}</dd>"
        f"<dt>aliases</dt><dd>{aliases_html}</dd>"
        f"<dt>cross-doc edges</dt><dd>{len(relations)}</dd>"
        "</dl>"
        "</header>"
    )

    sections: list[str] = ["<h2>Cross-doc edges touching this entity</h2>"]
    if not relations:
        sections.append(
            '<p class="empty">No cross-doc edges cite this entity in shared_entities.</p>'
        )
    else:
        for kind in _CROSS_DOC_KINDS:
            entries = grouped.get(kind, [])
            if not entries:
                continue
            rows = "".join(
                # The entity page links back to the appendix row anchor
                # so a reader can pivot to the full appendix context.
                # The row body re-renders the relation for self-containment.
                f'<li id="rel-{_esc(rel.id)}">'
                f'<span class="tag">{_esc(rel.kind)}</span>'
                f'<span class="tag">conf={_esc(rel.confidence)}</span>'
                f"<div><code>{_esc(rel.from_source_id)} / {_esc(rel.from_atom_id)}</code>"
                f' → <span class="predicate">{_esc(rel.kind)}</span> → '
                f"<code>{_esc(rel.to_source_id)} / {_esc(rel.to_atom_id)}</code></div>"
                f'<div class="warrant">warrant: {_esc(rel.warrant)}</div>'
                f'<div class="appendix-link">'
                f'<a href="../cross-doc-relations.html#relation-{_esc(rel.id)}">'
                f"view in appendix ({_esc(rel.id)})</a>"
                f"</div>"
                "</li>"
                for rel in entries
            )
            sections.append(
                f'<h3>{_esc(kind)} <span class="tag">{len(entries)}</span></h3>'
                f'<ul class="relations">{rows}</ul>'
            )

    appendix_link = (
        '<p><a href="../cross-doc-relations.html">← back to cross-doc relations appendix</a></p>'
    )
    footer = _render_footer(generated_at, version_string)
    # ``canonical_entity_ids`` is unused on the entity page itself
    # (we don't render the relation's full shared_entities list here),
    # but kept in the signature for symmetry with the appendix
    # renderer and to make the relationship explicit at call-sites.
    del canonical_entity_ids
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>amanuensis — {_esc(entity.canonical_name)}</title>\n"
        f"<style>{_BUNDLE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{summary}\n" + "\n".join(sections) + f"\n{appendix_link}\n{footer}\n"
        "</body>\n"
        "</html>\n"
    )


# ---------------------------------------------------------------------
# Phase 2c M11 — Probandum tree + per-probandum lineage page renderers
# ---------------------------------------------------------------------


def _excerpt(text: str, max_chars: int = _PROBANDUM_EXCERPT_CHARS) -> str:
    """Return ``text`` trimmed at the nearest word boundary near ``max_chars``.

    Empty or short strings pass through unchanged. Falls back to a hard
    cut if no whitespace appears in the first ``max_chars`` chars.
    Mirrors the web app's ``_statement_excerpt`` helper.
    """
    if len(text) <= max_chars:
        return text
    cutoff = text.rfind(" ", 0, max_chars)
    if cutoff <= 0:
        cutoff = max_chars
    return text[:cutoff].rstrip() + "…"


def _list_probanda(substrate: Substrate) -> list[Probandum]:
    """Return every probandum in the workspace, sorted by id.

    Sorting is by ``id`` for determinism — content-addressable hashes
    are unique per content, so this gives a stable order regardless of
    filesystem iteration. Same shape as ``_canonical_entities`` returns.
    """
    return sorted(substrate.list_probanda(), key=lambda p: p.id)


def _list_probandum_edges(substrate: Substrate) -> list[ProbandumEdge]:
    """Return every probandum-edge in the workspace, sorted by id.

    Sorting is by ``id`` so per-probandum child rows render in the same
    order on every run. Mirrors ``_list_probanda``.
    """
    return sorted(substrate.list_probandum_edges(), key=lambda e: e.id)


def _index_edges_by_parent(
    edges: list[ProbandumEdge],
) -> dict[str, list[ProbandumEdge]]:
    """Group edges by ``parent_probandum_id`` with deterministic per-parent order.

    Per-parent ordering is by edge ``id`` so the rendered tree is
    byte-identical across runs (INV-8). Empty groups are omitted; a
    parent with no edges is simply absent from the returned dict.
    """
    by_parent: dict[str, list[ProbandumEdge]] = defaultdict(list)
    for edge in edges:
        by_parent[edge.parent_probandum_id].append(edge)
    for parent_id in by_parent:
        by_parent[parent_id].sort(key=lambda e: e.id)
    return by_parent


def _index_edges_by_child(
    edges: list[ProbandumEdge],
) -> dict[str, list[ProbandumEdge]]:
    """Group edges by ``child_id`` (only ``child_kind == "probandum"``).

    The lineage walk only follows probandum→probandum edges (atom and
    cross-doc children are leaves and have no upward incoming edge in
    the probandum graph). Per-child ordering is by edge ``id`` so the
    "pick the first parent if multi-parent" tiebreaker is deterministic.
    """
    by_child: dict[str, list[ProbandumEdge]] = defaultdict(list)
    for edge in edges:
        if edge.child_kind != "probandum":
            continue
        by_child[edge.child_id].append(edge)
    for child_id in by_child:
        by_child[child_id].sort(key=lambda e: e.id)
    return by_child


def _kind_badge(label: str, css_class: str | None = None) -> str:
    """Render a ``<span class="kind-badge ...">`` tag for a probandum/edge kind."""
    classes = "kind-badge"
    if css_class:
        classes = f"{classes} {css_class}"
    return f'<span class="{classes}">{_esc(label)}</span>'


def _probandum_link(
    probandum_id: str,
    label: str,
    *,
    prefix: str,
) -> str:
    """Render an ``<a class="probandum-link">`` to ``probanda/<id>.html``.

    ``prefix`` lets the appendix page emit ``"probanda/<id>.html"``
    while the per-probandum pages use the empty prefix (siblings under
    the same directory).
    """
    return f'<a class="probandum-link" href="{prefix}{_esc(probandum_id)}.html">{_esc(label)}</a>'


def _render_edge_child_summary(
    edge: ProbandumEdge,
    *,
    probandum_by_id: dict[str, Probandum],
    atom_by_id: dict[str, Atom],
    cross_doc_by_id: dict[str, CrossDocRelation],
    probandum_link_prefix: str,
    atom_link_prefix: str,
    cross_doc_link_prefix: str,
) -> str:
    """Render the label cell for the child end of a probandum-edge.

    Picks a label per ``child_kind``:

    - ``probandum``: short statement excerpt + link to ``probanda/<id>.html``.
    - ``atom``: short narrative excerpt + link to
      ``<source_id>.html#atom-<id>`` (Phase 1 per-source export page).
    - ``cross-doc-relation``: short warrant excerpt + link to
      ``cross-doc-relations.html#relation-<id>``.

    Children that cannot be loaded (missing from substrate) render as
    plain ``<code>`` ids so a stale edge never disappears silently.
    """
    if edge.child_kind == "probandum":
        child = probandum_by_id.get(edge.child_id)
        if child is None:
            return (
                f"{_kind_badge('probandum', 'probandum')}"
                f"<code>&lt;missing: {_esc(edge.child_id)}&gt;</code>"
            )
        label = _excerpt(child.statement)
        link = _probandum_link(child.id, label, prefix=probandum_link_prefix)
        return f"{_kind_badge(child.kind, child.kind)}{link}"
    if edge.child_kind == "atom":
        atom = atom_by_id.get(edge.child_id)
        if atom is None or edge.child_source_id is None:
            return (
                f"{_kind_badge('atom', 'atom')}<code>&lt;missing: {_esc(edge.child_id)}&gt;</code>"
            )
        label = _excerpt(atom.narrative)
        href = f"{atom_link_prefix}{_esc(edge.child_source_id)}.html#atom-{_esc(atom.id)}"
        return f'{_kind_badge("atom", "atom")}<a class="atom-link" href="{href}">{_esc(label)}</a>'
    # cross-doc-relation
    rel = cross_doc_by_id.get(edge.child_id)
    if rel is None:
        return (
            f"{_kind_badge('cross-doc-relation', 'cross-doc-relation')}"
            f"<code>&lt;missing: {_esc(edge.child_id)}&gt;</code>"
        )
    label = _excerpt(rel.warrant)
    href = f"{cross_doc_link_prefix}cross-doc-relations.html#relation-{_esc(rel.id)}"
    return (
        f"{_kind_badge('cross-doc-relation', 'cross-doc-relation')}"
        f'<a href="{href}">{_esc(label)}</a>'
    )


def _render_subtree(
    *,
    probandum: Probandum,
    edges_by_parent: dict[str, list[ProbandumEdge]],
    probandum_by_id: dict[str, Probandum],
    atom_by_id: dict[str, Atom],
    cross_doc_by_id: dict[str, CrossDocRelation],
    probandum_link_prefix: str,
    atom_link_prefix: str,
    cross_doc_link_prefix: str,
    visited: set[str] | None = None,
    depth: int = 0,
) -> str:
    """Recursively render ``probandum`` + its subtree as nested ``<details>`` blocks.

    Each level is a ``<details open>`` so the bundle renders fully
    expanded by default; users can collapse subtrees interactively. The
    HTML5 ``<details>`` element requires no JavaScript — fits the
    bundle's "no external deps" discipline.

    ``visited`` defends against pathological graphs (cycles would have
    been gated at write-time by INV-16, but the renderer must not lock
    up if a stale edge leaks through). ``depth`` enforces
    ``_TREE_MAX_DEPTH`` as a belt-and-braces guard.
    """
    if visited is None:
        visited = set()
    if probandum.id in visited or depth > _TREE_MAX_DEPTH:
        return (
            f'<details class="probandum-node"><summary>'
            f"{_kind_badge(probandum.kind, probandum.kind)}"
            f"<code>&lt;cycle or depth-cap at {_esc(probandum.id)}&gt;</code>"
            "</summary></details>"
        )
    visited = visited | {probandum.id}

    statement = _excerpt(probandum.statement)
    summary = (
        f"<summary>{_kind_badge(probandum.kind, probandum.kind)}"
        f'<span class="probandum-statement">'
        f"{_probandum_link(probandum.id, statement, prefix=probandum_link_prefix)}"
        f"</span></summary>"
    )

    child_edges = edges_by_parent.get(probandum.id, [])
    if not child_edges:
        body = '<p class="empty">No outgoing edges.</p>'
    else:
        items: list[str] = []
        for edge in child_edges:
            edge_meta = (
                f'<div class="edge-meta">'
                f'<span class="tag">{_esc(edge.kind)}</span>'
                f'<span class="tag">defensibility={_esc(edge.warrant_defensibility)}</span>'
                f'<span class="tag">conf={_esc(edge.confidence)}</span>'
                f" warrant: {_esc(edge.warrant)}"
                f"</div>"
            )
            child_summary = _render_edge_child_summary(
                edge,
                probandum_by_id=probandum_by_id,
                atom_by_id=atom_by_id,
                cross_doc_by_id=cross_doc_by_id,
                probandum_link_prefix=probandum_link_prefix,
                atom_link_prefix=atom_link_prefix,
                cross_doc_link_prefix=cross_doc_link_prefix,
            )
            # Recurse only into probandum children. Atoms and cross-doc
            # relations are leaves in the probandum graph.
            if edge.child_kind == "probandum":
                child = probandum_by_id.get(edge.child_id)
                if child is not None:
                    nested = _render_subtree(
                        probandum=child,
                        edges_by_parent=edges_by_parent,
                        probandum_by_id=probandum_by_id,
                        atom_by_id=atom_by_id,
                        cross_doc_by_id=cross_doc_by_id,
                        probandum_link_prefix=probandum_link_prefix,
                        atom_link_prefix=atom_link_prefix,
                        cross_doc_link_prefix=cross_doc_link_prefix,
                        visited=visited,
                        depth=depth + 1,
                    )
                    items.append(f"<li>{child_summary}{edge_meta}{nested}</li>")
                    continue
            items.append(f"<li>{child_summary}{edge_meta}</li>")
        body = '<ul class="children">' + "".join(items) + "</ul>"

    return f'<details open class="probandum-node">{summary}{body}</details>'


def _gather_atoms_for_edges(substrate: Substrate, edges: list[ProbandumEdge]) -> dict[str, Atom]:
    """Return a dict mapping atom-child-id → Atom for every atom-leaf edge.

    Missing atoms (e.g. stale edge to a removed atom) are simply absent
    from the dict; the renderer falls back to a ``<missing>`` label.
    Done in one pass so the recursive renderer does not re-hit disk per
    child.
    """
    atoms: dict[str, Atom] = {}
    for edge in edges:
        if edge.child_kind != "atom":
            continue
        if edge.child_source_id is None:
            continue  # schema-impossible but be defensive
        if edge.child_id in atoms:
            continue
        try:
            atoms[edge.child_id] = substrate.get_atom(edge.child_source_id, edge.child_id)
        except Exception:
            continue
    return atoms


def _gather_cross_doc_for_edges(
    substrate: Substrate, edges: list[ProbandumEdge]
) -> dict[str, CrossDocRelation]:
    """Return a dict mapping cross-doc-child-id → CrossDocRelation."""
    rels: dict[str, CrossDocRelation] = {}
    for edge in edges:
        if edge.child_kind != "cross-doc-relation":
            continue
        if edge.child_id in rels:
            continue
        try:
            rels[edge.child_id] = substrate.get_cross_doc_relation(edge.child_id)
        except Exception:
            continue
    return rels


def _render_probandum_tree_page(
    *,
    probanda: list[Probandum],
    edges: list[ProbandumEdge],
    atom_by_id: dict[str, Atom],
    cross_doc_by_id: dict[str, CrossDocRelation],
    generated_at: datetime,
    version_string: str,
) -> str:
    """Render the ``probandum-tree.html`` appendix page.

    For each ``ultimate`` probandum (sorted by id) render a section
    anchored ``#ultimate-<id>`` containing the full subtree as nested
    ``<details>`` blocks. If no ultimate exists, render a placeholder
    section pointing the supervisor at the CLI command that creates one.
    """
    probandum_by_id = {p.id: p for p in probanda}
    edges_by_parent = _index_edges_by_parent(edges)
    ultimates = sorted([p for p in probanda if p.kind == "ultimate"], key=lambda p: p.id)

    summary = (
        '<header class="summary">'
        "<h1>Probandum tree</h1>"
        "<dl>"
        f"<dt>total probanda</dt><dd>{len(probanda)}</dd>"
        f"<dt>ultimate probanda</dt><dd>{len(ultimates)}</dd>"
        f"<dt>probandum-edges</dt><dd>{len(edges)}</dd>"
        "</dl>"
        "</header>"
    )

    sections: list[str] = []
    if not ultimates:
        sections.append(
            '<section id="no-ultimate">'
            "<h2>No probandum tree yet</h2>"
            '<p class="empty">'
            "No ultimate probandum has been declared in this workspace. "
            "A supervisor must declare one via "
            "<code>amanuensis map probandum add --kind ultimate</code> "
            "before the tree can be rendered."
            "</p>"
            "</section>"
        )
    else:
        for ultimate in ultimates:
            tree_html = _render_subtree(
                probandum=ultimate,
                edges_by_parent=edges_by_parent,
                probandum_by_id=probandum_by_id,
                atom_by_id=atom_by_id,
                cross_doc_by_id=cross_doc_by_id,
                # Page sits at bundle root: links to probanda/<id>.html
                # use the ``probanda/`` prefix; atom links go to
                # ``../<source>.html`` (per-source pages live one dir up
                # from the appendix bundle by convention); cross-doc
                # link is a sibling, no prefix needed.
                probandum_link_prefix="probanda/",
                atom_link_prefix="../",
                cross_doc_link_prefix="",
            )
            sections.append(
                f'<section id="ultimate-{_esc(ultimate.id)}">'
                f"<h2>Ultimate: {_esc(_excerpt(ultimate.statement, 80))}</h2>"
                f'<p class="probandum-id">id: <code>{_esc(ultimate.id)}</code></p>'
                f"{tree_html}"
                "</section>"
            )

    footer = _render_footer(generated_at, version_string)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>amanuensis — probandum tree</title>\n"
        f"<style>{_BUNDLE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{summary}\n" + "\n".join(sections) + f"\n{footer}\n"
        "</body>\n"
        "</html>\n"
    )


def _walk_ancestry(
    probandum_id: str,
    *,
    edges_by_child: dict[str, list[ProbandumEdge]],
    probandum_by_id: dict[str, Probandum],
) -> list[Probandum]:
    """Walk INCOMING probandum-edges up to the ultimate.

    Returns ancestors in order: nearest parent first, ultimate last (or
    whatever the walk reaches). Multi-parent forks (rare; Wigmore trees
    are typically single-parent) are tie-broken by edge id so the chain
    is deterministic.
    """
    chain: list[Probandum] = []
    visited: set[str] = {probandum_id}
    current = probandum_id
    for _ in range(_TREE_MAX_DEPTH):
        parents = edges_by_child.get(current, [])
        if not parents:
            break
        parent_id = parents[0].parent_probandum_id
        if parent_id in visited:
            break
        visited.add(parent_id)
        parent = probandum_by_id.get(parent_id)
        if parent is None:
            break
        chain.append(parent)
        if parent.kind == "ultimate":
            break
        current = parent_id
    return chain


def _render_lineage_chain(
    chain: list[Probandum],
    *,
    probandum_link_prefix: str,
) -> str:
    """Render the ancestry walk as an ordered list of upward steps.

    Empty chains render an explicit "no ancestors" placeholder so the
    section's shape stays stable.
    """
    if not chain:
        return '<p class="empty">No ancestors — this probandum has no incoming probandum-edges.</p>'
    items = "".join(
        f"<li>{_kind_badge(p.kind, p.kind)}"
        f"{_probandum_link(p.id, _excerpt(p.statement), prefix=probandum_link_prefix)}"
        f'<div class="probandum-id-small"><code>{_esc(p.id)}</code></div>'
        "</li>"
        for p in chain
    )
    return f'<ul class="lineage-chain">{items}</ul>'


def _render_alternatives(alternatives: list[str]) -> str:
    """Render the ACH alternatives list as a ``<ul>`` (or an empty placeholder)."""
    if not alternatives:
        return '<p class="empty">No alternatives considered.</p>'
    items = "".join(f"<li>{_esc(a)}</li>" for a in alternatives)
    return f"<ul>{items}</ul>"


def _render_per_probandum_page(
    *,
    probandum: Probandum,
    edges_by_parent: dict[str, list[ProbandumEdge]],
    edges_by_child: dict[str, list[ProbandumEdge]],
    probandum_by_id: dict[str, Probandum],
    atom_by_id: dict[str, Atom],
    cross_doc_by_id: dict[str, CrossDocRelation],
    generated_at: datetime,
    version_string: str,
) -> str:
    """Render one ``probanda/<id>.html`` page.

    Sections: header (statement + kind + scheme + alternatives +
    confidence) → Ancestry → Descendants → Provenance link.
    """
    summary = (
        '<header class="summary">'
        f"<h1>{_kind_badge(probandum.kind, probandum.kind)}"
        f"{_esc(_excerpt(probandum.statement, 200))}</h1>"
        "<dl>"
        f"<dt>id</dt><dd><code>{_esc(probandum.id)}</code></dd>"
        f"<dt>kind</dt><dd>{_esc(probandum.kind)}</dd>"
        f"<dt>scheme</dt><dd><code>{_esc(probandum.scheme)}</code></dd>"
        f"<dt>confidence</dt><dd>{_esc(probandum.confidence)}</dd>"
        f"<dt>provenance</dt><dd><code>{_esc(probandum.provenance_id)}</code></dd>"
        "</dl>"
        "</header>"
    )

    statement_section = f"<h2>Statement</h2><p>{_esc(probandum.statement)}</p>"

    alternatives_section = (
        f"<h2>Alternatives considered</h2>{_render_alternatives(probandum.alternatives_considered)}"
    )

    chain = _walk_ancestry(
        probandum.id,
        edges_by_child=edges_by_child,
        probandum_by_id=probandum_by_id,
    )
    # Per-probandum pages sit under ``probanda/`` so sibling probandum
    # links use the empty prefix; atom links go up two levels
    # (``../../<source>.html``); the cross-doc-relations appendix lives
    # one directory up.
    ancestry_section = f"<h2>Ancestry</h2>{_render_lineage_chain(chain, probandum_link_prefix='')}"

    descendants_html = _render_subtree(
        probandum=probandum,
        edges_by_parent=edges_by_parent,
        probandum_by_id=probandum_by_id,
        atom_by_id=atom_by_id,
        cross_doc_by_id=cross_doc_by_id,
        probandum_link_prefix="",
        atom_link_prefix="../../",
        cross_doc_link_prefix="../",
    )
    descendants_section = f"<h2>Descendants</h2>{descendants_html}"

    back_link = '<p><a href="../probandum-tree.html">← back to probandum tree</a></p>'
    footer = _render_footer(generated_at, version_string)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>amanuensis — {_esc(_excerpt(probandum.statement, 60))}</title>\n"
        f"<style>{_BUNDLE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{summary}\n"
        f"{statement_section}\n"
        f"{alternatives_section}\n"
        f"{ancestry_section}\n"
        f"{descendants_section}\n"
        f"{back_link}\n"
        f"{footer}\n"
        "</body>\n"
        "</html>\n"
    )


# --- Public API -------------------------------------------------------


def export_workspace_appendix(
    *,
    substrate: Substrate,
    out_dir: Path,
    now: datetime | None = None,
) -> Path:
    """Render a workspace-level bundle of cross-doc + per-entity + probandum pages.

    Emits a directory at ``out_dir`` containing:

    - ``cross-doc-relations.html`` — appendix listing every
      ``CrossDocRelation`` in the substrate, grouped by ``kind``.
    - ``entities/<id>.html`` — one page per canonical entity, with a
      "Cross-doc edges touching this entity" section.
    - ``probandum-tree.html`` (Phase 2c M11) — per-ultimate-probandum
      subtree rendered as nested ``<details>`` blocks.
    - ``probanda/<id>.html`` (Phase 2c M11) — one page per Probandum
      with ancestry (incoming edges up to ultimate) and descendants
      (outgoing subtree).

    Args:
        substrate: Bound Substrate for the workspace.
        out_dir: Destination directory. Created (with parents) if it
            does not exist. Existing files at the same paths are
            overwritten.
        now: Override the "generated at" timestamp — used by tests to
            produce byte-identical output across runs. Defaults to
            ``datetime.now(UTC)``.

    Returns:
        ``out_dir`` for caller convenience.

    Notes
    -----
    - **Render purity (INV-8)** is the load-bearing invariant: two
      runs over the same substrate must produce byte-identical files.
      Relation ordering is by ``id``; kind ordering is the fixed
      ``_CROSS_DOC_KINDS`` tuple; entity ordering is by
      ``(canonical_name, id)``; probandum + probandum-edge ordering is
      by ``id``.
    - **Self-contained**: no CDN URLs, no inline JavaScript, no
      external network references. CSS is inlined in a ``<style>``
      block per page (duplicated; the bundle is small enough that
      this is fine and lets each page be opened standalone). The
      probandum tree uses native HTML5 ``<details>`` for collapsing
      so no JS is required.
    - **Mode 0644**: every file is chmod'd 0644 so the bundle is
      shareable (emailed, posted, archived).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    entities_dir = out_dir / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    probanda_dir = out_dir / "probanda"
    probanda_dir.mkdir(parents=True, exist_ok=True)

    generated_at = now if now is not None else datetime.now(UTC)
    version_string = _package_version()

    # Substrate reads — all sorted for determinism.
    relations: list[CrossDocRelation] = sorted(
        substrate.list_cross_doc_relations(), key=lambda r: r.id
    )
    canonical = _canonical_entities(substrate)
    canonical_ids: set[str] = {e.id for e in canonical}

    # 1. Appendix page.
    appendix_html = _render_appendix_page(
        relations=relations,
        canonical_entity_ids=canonical_ids,
        generated_at=generated_at,
        version_string=version_string,
    )
    appendix_path = out_dir / "cross-doc-relations.html"
    appendix_path.write_text(appendix_html, encoding="utf-8")
    os.chmod(appendix_path, stat.S_IMODE(_OUTPUT_MODE))

    # 2. Per-entity pages. Iterate the canonical list so file order
    # is deterministic — the rglob in render-purity tests sorts
    # paths, so order matters less than CONTENT, but file count must
    # match across runs.
    for entity in canonical:
        per_entity_relations = sorted(
            substrate.list_cross_doc_relations(shared_entity=entity.id),
            key=lambda r: r.id,
        )
        page_html = _render_entity_page(
            entity=entity,
            relations=per_entity_relations,
            canonical_entity_ids=canonical_ids,
            generated_at=generated_at,
            version_string=version_string,
        )
        page_path = entities_dir / f"{entity.id}.html"
        page_path.write_text(page_html, encoding="utf-8")
        os.chmod(page_path, stat.S_IMODE(_OUTPUT_MODE))

    # 3. Probandum tree + per-probandum pages (Phase 2c M11).
    probanda = _list_probanda(substrate)
    probandum_edges = _list_probandum_edges(substrate)
    edges_by_parent = _index_edges_by_parent(probandum_edges)
    edges_by_child = _index_edges_by_child(probandum_edges)
    probandum_by_id = {p.id: p for p in probanda}
    atom_by_id = _gather_atoms_for_edges(substrate, probandum_edges)
    cross_doc_by_edges = _gather_cross_doc_for_edges(substrate, probandum_edges)

    tree_html = _render_probandum_tree_page(
        probanda=probanda,
        edges=probandum_edges,
        atom_by_id=atom_by_id,
        cross_doc_by_id=cross_doc_by_edges,
        generated_at=generated_at,
        version_string=version_string,
    )
    tree_path = out_dir / "probandum-tree.html"
    tree_path.write_text(tree_html, encoding="utf-8")
    os.chmod(tree_path, stat.S_IMODE(_OUTPUT_MODE))

    # Per-probandum pages. Iteration order matches ``probanda`` (id-sorted)
    # so file count + content is deterministic across runs.
    for probandum in probanda:
        page_html = _render_per_probandum_page(
            probandum=probandum,
            edges_by_parent=edges_by_parent,
            edges_by_child=edges_by_child,
            probandum_by_id=probandum_by_id,
            atom_by_id=atom_by_id,
            cross_doc_by_id=cross_doc_by_edges,
            generated_at=generated_at,
            version_string=version_string,
        )
        page_path = probanda_dir / f"{probandum.id}.html"
        page_path.write_text(page_html, encoding="utf-8")
        os.chmod(page_path, stat.S_IMODE(_OUTPUT_MODE))

    return out_dir
