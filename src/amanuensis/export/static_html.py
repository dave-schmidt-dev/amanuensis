"""Static-HTML export — Phase 1 stub (M9.1).

Render one distillation (manifest + paragraphs + atoms + relations)
into a single self-contained HTML file. Phase 4 will replace this stub
with the full audit-HTML bundle; the stub establishes the file shape
and CLI surface those later milestones depend on.

Design constraints
------------------
- **Self-contained**: no CDN links, no external network references, no
  inline JavaScript beyond ``<script type="application/json">`` data
  blocks. The output file MUST be openable in a browser without a
  network connection.
- **Read-only**: this module never writes to the substrate. It reads
  the source-mirror manifest, the per-paragraph ``.md`` bodies, every
  atom under the distillation, and every relation file directly off
  disk via the Substrate handle's path helpers.
- **Mode 0644**: the output file is meant to be shared (emailed,
  posted, archived). Group / world readable, owner writable.
- **Deterministic ordering**: paragraphs are sorted by
  ``paragraph_index``; atoms / relations are sorted by their canonical
  id. The on-disk JSON is emitted with ``sort_keys=True`` so byte-
  equal regeneration round-trips cleanly.

Relation walking mirrors the pattern in
``amanuensis.web.routes._substrate_counts`` /
``amanuensis.web.routes.relations._list_relations``: read each
``relations/*.yaml`` directly, skip ``.tmp.*`` writer leftovers, parse
through Pydantic for validation. A future ``Substrate.list_relations``
API will fold this into the substrate class; M9.1 keeps the walker
local to avoid expanding the substrate surface for a stub consumer.
"""

from __future__ import annotations

import html
import json
import os
import stat
from collections import defaultdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import yaml

from amanuensis.fs import Substrate
from amanuensis.fs._serialize import parse_paragraph_md
from amanuensis.schemas import Atom, Entity, Relation, SourceMirrorManifest

# Output file mode — group / world readable; owner writable. The
# exported HTML is meant to be shared (emailed, posted, archived).
_OUTPUT_MODE: int = 0o644


def _package_version() -> str:
    """Best-effort amanuensis distribution version (or ``"unknown"``)."""
    try:
        return version("amanuensis")
    except PackageNotFoundError:  # pragma: no cover - dev-env glitch
        return "unknown"


def _load_manifest(manifest_path: Path) -> SourceMirrorManifest:
    """Parse + validate a source-mirror manifest from its on-disk YAML."""
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return SourceMirrorManifest.model_validate(raw)


def _read_paragraph_bodies(
    substrate: Substrate, source_id: str, manifest: SourceMirrorManifest
) -> dict[str, str]:
    """Return a ``{paragraph_id: body_text}`` map for every manifest entry.

    Bodies are read from the per-paragraph ``.md`` files under
    ``source-mirror/paragraphs/``. A missing file yields an empty string
    (the export is a best-effort render, not a substrate validator).
    """
    bodies: dict[str, str] = {}
    for entry in manifest.paragraphs:
        path = substrate.paragraph_path(source_id, entry.paragraph_id)
        if not path.is_file():
            bodies[entry.paragraph_id] = ""
            continue
        _frontmatter, body = parse_paragraph_md(path.read_text(encoding="utf-8"))
        bodies[entry.paragraph_id] = body
    return bodies


def _list_relations(substrate: Substrate, source_id: str) -> list[Relation]:
    """Walk ``relations/*.yaml`` and parse each entry; lex-sorted.

    Mirrors the pattern used by ``web/routes/relations._list_relations``
    and ``web/routes/_substrate_counts``: skip ``.tmp.*`` writer
    leftovers; ignore subdirectories; sort for deterministic output.
    """
    relations_dir = substrate.root / "distillations" / source_id / "relations"
    if not relations_dir.is_dir():
        return []
    out: list[Relation] = []
    for path in sorted(relations_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if not name.endswith(".yaml"):
            continue
        if ".tmp." in name:
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        out.append(Relation.model_validate(raw))
    return out


# --- HTML rendering ---------------------------------------------------


_CSS = """\
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
section.paragraph {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  margin-bottom: 0.75rem;
}
section.paragraph .breadcrumb {
  color: var(--muted);
  font-size: 0.85rem;
  margin-bottom: 0.25rem;
}
section.paragraph .body { white-space: pre-wrap; word-wrap: break-word; }
ul.atoms, ul.relations { list-style: none; padding: 0; }
ul.atoms li, ul.relations li {
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
footer {
  margin-top: 3rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.8rem;
}
/* Entity sidebar (Phase 2a M9) */
aside.entity-sidebar {
  background: var(--card);
  border: 1px solid var(--border);
  border-left: 3px solid #e07b39;
  border-radius: 6px;
  padding: 0.75rem 1rem;
  margin-bottom: 1.5rem;
  font-size: 0.88rem;
}
aside.entity-sidebar h2 {
  margin: 0 0 0.5rem;
  font-size: 1rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.25rem;
  color: #e07b39;
}
aside.entity-sidebar .entity-kind-group { margin-bottom: 0.5rem; }
aside.entity-sidebar .entity-kind-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #e07b39;
  opacity: 0.8;
  margin-bottom: 0.2rem;
}
aside.entity-sidebar ul { list-style: none; padding: 0; margin: 0; }
aside.entity-sidebar li {
  padding: 0.15rem 0;
  border-bottom: none;
  background: none;
  border-radius: 0;
  border: none;
  margin: 0;
}
aside.entity-sidebar a {
  color: var(--fg);
  text-decoration: none;
}
aside.entity-sidebar a:hover { text-decoration: underline; color: #e07b39; }
/* Inline resolution annotations */
a.resolved-entity {
  color: #e07b39;
  text-decoration: none;
  border-bottom: 1px dashed #e07b39;
}
a.resolved-entity:hover { text-decoration: underline; }
span.unresolved-entity {
  color: var(--muted);
  border-bottom: 1px dotted var(--muted);
}
span.operand { color: var(--muted); font-size: 0.88em; }
div.operands { margin-top: 0.3rem; }
"""


def _esc(value: object) -> str:
    """HTML-escape any value via its ``str()`` form."""
    return html.escape(str(value), quote=True)


def _render_breadcrumb(section_path: list[str]) -> str:
    if not section_path:
        return "(no heading)"
    return " / ".join(_esc(part) for part in section_path)


def _render_summary(
    manifest: SourceMirrorManifest,
    *,
    paragraph_count: int,
    atom_count: int,
    relation_count: int,
) -> str:
    short_sha = manifest.source_sha256[:12]
    return (
        '<header class="summary">'
        f"<h1>{_esc(manifest.source_id)}</h1>"
        "<dl>"
        f"<dt>source filename</dt><dd>{_esc(manifest.source_filename)}</dd>"
        f"<dt>source sha256</dt><dd><code>{_esc(short_sha)}…</code></dd>"
        f"<dt>paragraphs</dt><dd>{paragraph_count}</dd>"
        f"<dt>atoms</dt><dd>{atom_count}</dd>"
        f"<dt>relations</dt><dd>{relation_count}</dd>"
        "</dl>"
        "</header>"
    )


def _render_paragraphs(manifest: SourceMirrorManifest, bodies: dict[str, str]) -> str:
    if not manifest.paragraphs:
        return '<p class="empty">No paragraphs in this source-mirror.</p>'
    ordered = sorted(manifest.paragraphs, key=lambda p: p.paragraph_index)
    parts: list[str] = []
    for entry in ordered:
        body = bodies.get(entry.paragraph_id, "")
        parts.append(
            '<section class="paragraph" '
            f'id="paragraph-{_esc(entry.paragraph_id)}">'
            f'<div class="breadcrumb">'
            f'<span class="tag">{_esc(entry.paragraph_id)}</span>'
            f"{_render_breadcrumb(entry.section_path)}"
            "</div>"
            f'<div class="body">{_esc(body)}</div>'
            "</section>"
        )
    return "\n".join(parts)


def _render_operands(
    atom: Atom,
    *,
    substrate: Substrate,
    include_mappings: bool,
) -> str:
    """Render an atom's operands as inline spans/links.

    For ``kind=="entity"`` operands:
    - With ``include_mappings=True`` and a resolved entity: renders as
      ``<a href="#entity-<canonical_id>" class="resolved-entity" ...>``.
    - Otherwise: renders as ``<span class="unresolved-entity">value</span>``.

    Non-entity operands render as ``<span class="operand">value (role: …)</span>``.
    """
    if not atom.operands:
        return ""
    parts: list[str] = []
    for idx, operand in enumerate(atom.operands):
        if operand.kind == "entity":
            resolved_link = ""
            if include_mappings:
                resolution = substrate.latest_resolution_for(atom.source_id, atom.id, idx)
                if resolution is not None:
                    try:
                        canonical = substrate.latest_entity_for(resolution.entity_id)
                        resolved_link = (
                            f'<a href="#entity-{_esc(canonical.id)}" '
                            f'class="resolved-entity" '
                            f'title="Canonical: {_esc(canonical.canonical_name)}">'
                            f"{_esc(operand.value)}</a>"
                        )
                    except Exception:
                        pass
            if resolved_link:
                parts.append(resolved_link)
            else:
                parts.append(f'<span class="unresolved-entity">{_esc(operand.value)}</span>')
        else:
            parts.append(
                f'<span class="operand">{_esc(operand.value)} (role: {_esc(operand.role)})</span>'
            )
    return " ".join(parts)


def _render_atoms(
    atoms: list[Atom],
    *,
    substrate: Substrate,
    include_mappings: bool,
) -> str:
    if not atoms:
        return '<p class="empty">No atoms extracted for this source.</p>'
    parts: list[str] = []
    for atom in atoms:
        # Find a stable paragraph anchor. We can't always derive
        # paragraph_id from paragraph_index alone (the manifest's id
        # format is p-NNNN zero-padded; we mirror that).
        paragraph_id = f"p-{atom.paragraph_index:04d}"
        scale_tag = f'<span class="tag">scale={_esc(atom.scale_anchor)}</span>'
        kind_tag = f'<span class="tag">kind={_esc(atom.kind)}</span>'
        backref = (
            f'<a class="tag" href="#paragraph-{_esc(paragraph_id)}">↑ {_esc(paragraph_id)}</a>'
        )
        operands_html = _render_operands(
            atom, substrate=substrate, include_mappings=include_mappings
        )
        operands_block = f'<div class="operands">{operands_html}</div>' if operands_html else ""
        parts.append(
            f'<li id="atom-{_esc(atom.id)}">'
            f"{kind_tag}{scale_tag}{backref}"
            f'<span class="predicate">{_esc(atom.predicate)}</span>'
            f"<div>{_esc(atom.narrative)}</div>"
            f"{operands_block}"
            "</li>"
        )
    return f'<ul class="atoms">{"".join(parts)}</ul>'


def _render_relations(relations: list[Relation]) -> str:
    if not relations:
        return '<p class="empty">No relations recorded for this source.</p>'
    parts: list[str] = []
    for rel in relations:
        kind_tag = f'<span class="tag">{_esc(rel.kind)}</span>'
        conf_tag = f'<span class="tag">conf={_esc(rel.confidence)}</span>'
        parts.append(
            f'<li id="relation-{_esc(rel.id)}">'
            f"{kind_tag}{conf_tag}"
            f"<code>{_esc(rel.from_atom_id)}</code> "
            f'→ <span class="predicate">{_esc(rel.kind)}</span> → '
            f"<code>{_esc(rel.to_atom_id)}</code>"
            f'<div class="breadcrumb">warrant: {_esc(rel.warrant)}</div>'
            "</li>"
        )
    return f'<ul class="relations">{"".join(parts)}</ul>'


def _json_block(block_id: str, payload: list[dict[str, Any]]) -> str:
    """Emit a ``<script type="application/json">`` block.

    The JSON itself is escaped against ``</script`` injection by
    splitting any literal ``</`` sequence — a defensive measure since
    the data we embed comes from validated Pydantic models but could
    contain user-supplied narrative text.
    """
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    safe = encoded.replace("</", "<\\/")
    return f'<script type="application/json" id="{block_id}">\n{safe}\n</script>'


def _render_entity_sidebar(substrate: Substrate, *, include_mappings: bool) -> str:
    """Render the entity sidebar ``<aside>`` block.

    When ``include_mappings=False``: returns an empty string (no sidebar).

    When ``include_mappings=True`` and ``mappings/entities/`` is empty or
    absent: returns an empty-state aside with the literal text
    ``"No mappings yet — run `amanuensis map` to populate."``.

    When ``include_mappings=True`` and entities exist: returns an
    ``<aside class="entity-sidebar">`` grouping canonical entities by
    kind. Each entry gets an ``id="entity-<id>"`` anchor so inline
    annotations can deep-link here. Superseded entities are excluded by
    walking via ``latest_entity_for`` and comparing ids.
    """
    if not include_mappings:
        return ""

    # Collect all entity ids from disk.
    all_entities = list(substrate.list_entities())

    if not all_entities:
        return (
            '<aside class="entity-sidebar">'
            '<p class="empty">No mappings yet — run `amanuensis map` to populate.</p>'
            "</aside>"
        )

    # Walk to canonical. An entity is canonical iff latest_entity_for(e.id).id == e.id.
    canonical_entities: list[Entity] = []
    for entity in all_entities:
        try:
            canonical = substrate.latest_entity_for(entity.id)
        except Exception:
            continue
        if canonical.id == entity.id:
            canonical_entities.append(canonical)

    if not canonical_entities:
        return (
            '<aside class="entity-sidebar">'
            '<p class="empty">No mappings yet — run `amanuensis map` to populate.</p>'
            "</aside>"
        )

    # Group by kind; sort groups and entries within each group for determinism.
    groups: dict[str, list[Entity]] = defaultdict(list)
    for entity in sorted(canonical_entities, key=lambda e: e.canonical_name):
        groups[entity.kind].append(entity)

    parts: list[str] = ['<aside class="entity-sidebar">', "<h2>Entities</h2>"]
    for kind in sorted(groups):
        entries: list[Entity] = groups[kind]
        items = "".join(
            f'<li id="entity-{_esc(e.id)}">'
            f'<a href="#entity-{_esc(e.id)}">{_esc(e.canonical_name)}</a>'
            f"</li>"
            for e in entries
        )
        parts.append(
            f'<div class="entity-kind-group">'
            f'<div class="entity-kind-label">{_esc(kind)}</div>'
            f"<ul>{items}</ul>"
            f"</div>"
        )
    parts.append("</aside>")
    return "\n".join(parts)


def _render_document(
    *,
    manifest: SourceMirrorManifest,
    paragraphs_payload: list[dict[str, Any]],
    atoms_payload: list[dict[str, Any]],
    relations_payload: list[dict[str, Any]],
    atoms: list[Atom],
    relations: list[Relation],
    paragraph_bodies: dict[str, str],
    generated_at: datetime,
    version_string: str,
    substrate: Substrate,
    include_mappings: bool,
) -> str:
    summary = _render_summary(
        manifest,
        paragraph_count=len(manifest.paragraphs),
        atom_count=len(atoms),
        relation_count=len(relations),
    )
    paragraphs_html = _render_paragraphs(manifest, paragraph_bodies)
    atoms_html = _render_atoms(atoms, substrate=substrate, include_mappings=include_mappings)
    relations_html = _render_relations(relations)
    sidebar_html = _render_entity_sidebar(substrate, include_mappings=include_mappings)
    footer = (
        "<footer>Generated by amanuensis "
        f"v{_esc(version_string)} at "
        f"{_esc(generated_at.isoformat(timespec='seconds'))}</footer>"
    )
    json_blocks = "\n".join(
        [
            _json_block("paragraphs-data", paragraphs_payload),
            _json_block("atoms-data", atoms_payload),
            _json_block("relations-data", relations_payload),
        ]
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>amanuensis — {_esc(manifest.source_id)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{sidebar_html}\n"
        f"{summary}\n"
        "<h2>Paragraphs</h2>\n"
        f"{paragraphs_html}\n"
        "<h2>Atoms</h2>\n"
        f"{atoms_html}\n"
        "<h2>Relations</h2>\n"
        f"{relations_html}\n"
        f"{json_blocks}\n"
        f"{footer}\n"
        "</body>\n"
        "</html>\n"
    )


# --- Public API -------------------------------------------------------


def export_static_html(
    *,
    substrate: Substrate,
    source_id: str,
    output_path: Path,
    include_mappings: bool = True,
    now: datetime | None = None,
) -> Path:
    """Render one distillation as a single self-contained HTML file.

    Reads the source-mirror manifest, every paragraph body, every atom,
    and every relation under ``source_id``; emits one HTML document at
    ``output_path`` with three embedded JSON sidecar blocks so a
    downstream consumer (or Phase 4's audit-HTML bundler) can rebuild
    the substrate slice without re-walking the workspace.

    Args:
        substrate: Bound Substrate for the workspace.
        source_id: Per-distillation source id to render.
        output_path: Destination for the output file (created or overwritten).
        include_mappings: When ``True`` (default), includes the entity
            sidebar and inline resolution annotations driven by the
            ``mappings/`` registry.  When ``False``, reverts to Phase-1-
            style rendering with no sidebar and no annotations.
        now: Override the "generated at" timestamp — used by tests to
            produce byte-identical output across runs.  Defaults to
            ``datetime.now(UTC)``.

    Returns ``output_path`` for caller convenience.

    The output is written via ``Path.write_text`` (not the atomic-write
    helper) because exports are workspace-EXTERNAL artifacts; the
    atomic-write helper is reserved for substrate writes. The file is
    chmod'd to 0644 so it is shareable.
    """
    manifest_path = substrate.manifest_path(source_id)
    manifest = _load_manifest(manifest_path)
    paragraph_bodies = _read_paragraph_bodies(substrate, source_id, manifest)
    atoms: list[Atom] = sorted(substrate.list_atoms(source_id), key=lambda a: a.id)
    relations: list[Relation] = _list_relations(substrate, source_id)

    # JSON sidecar payloads — round-trippable via the schemas' own
    # ``model_validate``. ``mode="json"`` keeps every leaf JSON-friendly
    # (datetimes serialize to ISO-8601 strings, tuples to lists).
    paragraphs_payload: list[dict[str, Any]] = [
        {**p.model_dump(mode="json"), "body": paragraph_bodies.get(p.paragraph_id, "")}
        for p in sorted(manifest.paragraphs, key=lambda p: p.paragraph_index)
    ]
    atoms_payload: list[dict[str, Any]] = [a.model_dump(mode="json") for a in atoms]
    relations_payload: list[dict[str, Any]] = [r.model_dump(mode="json") for r in relations]

    generated_at = now if now is not None else datetime.now(UTC)

    document = _render_document(
        manifest=manifest,
        paragraphs_payload=paragraphs_payload,
        atoms_payload=atoms_payload,
        relations_payload=relations_payload,
        atoms=atoms,
        relations=relations,
        paragraph_bodies=paragraph_bodies,
        generated_at=generated_at,
        version_string=_package_version(),
        substrate=substrate,
        include_mappings=include_mappings,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    # ``chmod`` is explicit because ``write_text`` honors the process
    # umask, which on a typical workstation gives 0644 but on a CI box
    # or a tightened user shell may produce 0600 / 0640.
    os.chmod(output_path, stat.S_IMODE(_OUTPUT_MODE))
    return output_path
