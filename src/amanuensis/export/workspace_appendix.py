"""Workspace-level static export bundle — Phase 2b M9.

Phase 1's :func:`amanuensis.export.export_static_html` is a per-source
single-file exporter: one HTML file per distillation, with that
distillation's paragraphs / atoms / relations inline. Phase 2b adds
cross-document content (``CrossDocRelation`` records) that has no
single-source home — by definition each one touches two sources.

This module emits a workspace-level *bundle*: a directory containing

- ``cross-doc-relations.html`` — appendix listing every
  ``CrossDocRelation`` in the substrate, grouped by ``kind`` (one of
  ``supports`` / ``attacks`` / ``undercuts``). Each row anchors at
  ``#relation-<id>``.
- ``entities/<entity_id>.html`` — one page per canonical entity (the
  terminal node of every supersede chain), with a "Cross-doc edges
  touching this entity" section that mirrors the web app's
  ``entity_detail.html`` layout.

The bundle is *self-contained*: same CSS-in-`<style>` discipline as
Phase 1, no CDN URLs, no external network references. Pages link to
sibling pages via relative paths (``entities/<id>.html`` from the
appendix; ``../cross-doc-relations.html#relation-<id>`` from the
entity pages).

INV-8 (substrate is source of truth; renderings are pure functions of
state) is the load-bearing invariant: two runs over the same substrate
must produce byte-identical files. Tests in
``tests/export/test_static_export_cross_doc.py`` assert this.

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
from amanuensis.schemas import CrossDocRelation, Entity

# Output file mode — group / world readable; owner writable. Matches
# the per-source exporter so the bundle's files share a single mode.
_OUTPUT_MODE: int = 0o644

# The closed set of cross-doc kinds — mirrors the schema's Literal type.
# Rendering iterates this in a fixed order so the produced HTML is
# deterministic regardless of dict-iteration order.
_CROSS_DOC_KINDS: tuple[str, ...] = ("supports", "attacks", "undercuts")


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


# --- Public API -------------------------------------------------------


def export_workspace_appendix(
    *,
    substrate: Substrate,
    out_dir: Path,
    now: datetime | None = None,
) -> Path:
    """Render a workspace-level bundle of cross-doc + per-entity pages.

    Emits a directory at ``out_dir`` containing:

    - ``cross-doc-relations.html`` — appendix listing every
      ``CrossDocRelation`` in the substrate, grouped by ``kind``.
    - ``entities/<id>.html`` — one page per canonical entity, with a
      "Cross-doc edges touching this entity" section.

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
      ``(canonical_name, id)``.
    - **Self-contained**: no CDN URLs, no inline JavaScript, no
      external network references. CSS is inlined in a ``<style>``
      block per page (duplicated; the bundle is small enough that
      this is fine and lets each page be opened standalone).
    - **Mode 0644**: every file is chmod'd 0644 so the bundle is
      shareable (emailed, posted, archived).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    entities_dir = out_dir / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)

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

    return out_dir
