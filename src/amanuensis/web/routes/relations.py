"""Relation-graph route: ``GET /distillations/<source-id>/relations``.

Renders a Cytoscape.js-driven visualisation of every atom (node) and
every relation (edge) in a single distillation. The page emits two
adjacent DOM blocks:

- A STABLE ``<div id="cy">`` canvas that Cytoscape mounts into. This
  div is deliberately NOT swappable by HTMX so the cytoscape instance
  survives subsequent partial updates.
- A SWAPPABLE ``<script type="application/json" id="cy-data">`` block
  containing the Cytoscape elements payload. An Alpine.js binding on
  the parent listens for ``htmx:afterSwap`` events targeting
  ``#cy-data`` and re-feeds the payload into the existing Cytoscape
  instance via ``cy.json({elements: ...})`` rather than rebuilding it.

M8.4 implements the structural separation only; the HTMX-swap behaviour
itself is exercised by the Playwright suite in M8.9.

Substrate walking
-----------------
- Nodes come from ``substrate.list_atoms(source_id)``.
- Edges are read directly off-disk from
  ``<workspace>/distillations/<source-id>/relations/*.yaml``. We do not
  go through ``Substrate.list_relations`` because that method does not
  exist yet (mirrors the same compromise the dashboard's
  ``_substrate_counts`` helper makes for counts). A follow-up will
  promote a real ``list_relations`` API onto :class:`Substrate`.

Both reads are tolerant of substrate states that are valid but
incomplete: a distillation with zero atoms and zero relations renders a
page with an empty payload (``{"elements": []}``) rather than 404.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import ValidationError

from amanuensis.fs import Substrate, SubstrateInvalidId
from amanuensis.schemas import Relation

from ..dependencies import get_substrate

router = APIRouter()


def _list_relations(substrate: Substrate, source_id: str) -> list[Relation]:
    """Walk ``relations/*.yaml`` for ``source_id`` and parse each entry.

    Order is lex-sorted (filesystem-iteration order with explicit sort)
    for deterministic node/edge ordering across runs. Skips ``.tmp.*``
    writer leftovers the same way ``Substrate.list_atoms`` does.

    A YAML parse error or schema-validation failure for a single
    relation file is logged into the returned payload as an error
    sentinel — *but* M8.4 does not yet have a logger plumbed into the
    web package, so for now we re-raise as a 500 with the offending
    path. Tightening this to a per-file skip + warning lives in M8.9
    when the Playwright suite exercises the unhappy paths.
    """
    relations_dir: Path = substrate.root / "distillations" / source_id / "relations"
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
        try:
            out.append(Relation.model_validate(raw))
        except ValidationError as exc:  # pragma: no cover - defensive
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"relation file {path.name} is not valid: {exc}",
            ) from exc
    return out


def _ensure_distillation_exists(substrate: Substrate, source_id: str) -> None:
    """Translate ``SubstrateInvalidId`` and missing-dir into a 404.

    Mirrors the helper in ``atoms.py`` and ``source.py``. Duplicated
    rather than refactored upward to keep the M8.4 patch surface
    bounded; an extract-to-shared-helper pass lives in M8.9.
    """
    try:
        distillation_root = substrate.root / "distillations" / source_id
        substrate.manifest_path(source_id)
    except SubstrateInvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"distillation {source_id!r} not found",
        ) from exc
    if not distillation_root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"distillation {source_id!r} not found",
        )


def _build_cytoscape_payload(
    atoms: list[Any],
    relations: list[Relation],
) -> dict[str, list[dict[str, dict[str, str]]]]:
    """Return the Cytoscape ``{"elements": [...]}`` payload.

    Nodes carry ``id``, ``label`` (truncated narrative), and
    ``kind="atom"``. Edges carry ``id``, ``source``, ``target``, and
    ``label`` (the relation kind: supports / attacks / undercuts).

    The narrative label is truncated to a sensible width so the
    Cytoscape graph stays legible; the full text is still available on
    the atom-detail page.
    """
    elements: list[dict[str, dict[str, str]]] = []
    for atom in atoms:
        narrative: str = getattr(atom, "narrative", "") or ""
        label = narrative if len(narrative) <= 64 else narrative[:61] + "..."
        elements.append(
            {
                "data": {
                    "id": atom.id,
                    "label": label,
                    "kind": "atom",
                },
            }
        )
    for relation in relations:
        elements.append(
            {
                "data": {
                    "id": relation.id,
                    "source": relation.from_atom_id,
                    "target": relation.to_atom_id,
                    "label": relation.kind,
                },
            }
        )
    return {"elements": elements}


@router.get(
    "/distillations/{source_id}/relations",
    response_class=HTMLResponse,
)
async def relation_graph(
    request: Request,
    source_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """Render the relation-graph page for a single distillation."""
    _ensure_distillation_exists(substrate, source_id)

    atoms = list(substrate.list_atoms(source_id))
    relations = _list_relations(substrate, source_id)
    payload = _build_cytoscape_payload(atoms, relations)
    # Pre-serialize to JSON here so the template can drop it verbatim
    # into the ``<script type="application/json">`` block. Pre-rendering
    # in Python (rather than via Jinja's ``tojson``) keeps the template
    # free of escaping subtleties — the script tag's body is opaque to
    # HTML parsing as long as it does not contain the literal
    # ``</script>`` sequence, which our atom/relation ids and short
    # labels cannot produce.
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    atom_entity_index = _build_atom_entity_index(substrate, source_id)
    atom_entity_index_json = json.dumps(atom_entity_index, ensure_ascii=False, sort_keys=True)

    templates = request.app.state.templates
    return templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "relation_graph.html",
        {
            "source_id": source_id,
            "node_count": len(atoms),
            "edge_count": len(relations),
            "cy_data_json": payload_json,
            "atom_entity_index_json": atom_entity_index_json,
        },
    )


def _build_atom_entity_index(substrate: Substrate, source_id: str) -> dict[str, list[str]]:
    """Build the atom→entity-ids index for the hover-by-entity feature.

    For each Resolution under ``source_id``, the entity_id is resolved
    through the EntitySupersede chain via ``latest_entity_for`` so the
    returned ids are CANONICAL (CV-9). Deduplicates per-list. Keys are
    sorted for deterministic output; lists preserve insertion order after
    dedup (first occurrence wins).

    Atoms with no resolutions are absent from the returned dict.
    """
    index: dict[str, list[str]] = {}
    for resolution in substrate.list_resolutions(source_id=source_id):
        atom_id = resolution.atom_id
        try:
            canonical_entity = substrate.latest_entity_for(resolution.entity_id)
            entity_id = canonical_entity.id
        except Exception:
            # Defensive: broken supersede chain or missing entity — skip.
            entity_id = resolution.entity_id
        if atom_id not in index:
            index[atom_id] = []
        if entity_id not in index[atom_id]:
            index[atom_id].append(entity_id)
    return dict(sorted(index.items()))


@router.get(
    "/distillations/{source_id}/relations/atom-entity-index",
    response_class=JSONResponse,
)
async def atom_entity_index(
    source_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
    include_cross_doc: Annotated[
        int,
        Query(
            description=(
                "If truthy (1), envelope the atom→entity index in a JSON "
                "object that also carries a ``cross_doc_edges`` key listing "
                "every CrossDocRelation touching this distillation (Phase "
                "2b T8.5). Defaults to 0 — legacy shape (bare dict)."
            ),
        ),
    ] = 0,
) -> JSONResponse:
    """Return the atom→entity index for the given distillation.

    Legacy shape (``include_cross_doc=0``, default): bare
    ``dict[atom_id, list[entity_id]]``. Entity ids are canonical (CV-9:
    passed through ``latest_entity_for``). Atoms with no resolutions
    are absent from the dict. Keys are sorted for deterministic output.

    Extended shape (``include_cross_doc=1``, Phase 2b T8.5): a
    two-key object — the original dict is moved under ``atom_entity``
    and a new ``cross_doc_edges`` list carries every cross-doc edge
    where ``from_source_id == source_id`` OR ``to_source_id ==
    source_id``. Each edge is a flat dict with ``id``,
    ``from_source_id``, ``from_atom_id``, ``to_source_id``,
    ``to_atom_id``, ``kind``, and ``shared_entities``. Order follows
    ``Substrate.list_cross_doc_relations`` (lex-id).

    Headers:
        Cache-Control: no-store — resolutions and cross-doc relations
        both change during a session.
    """
    _ensure_distillation_exists(substrate, source_id)
    index = _build_atom_entity_index(substrate, source_id)
    if not include_cross_doc:
        return JSONResponse(
            content=index,
            headers={"Cache-Control": "no-store"},
        )
    cross_doc_edges = _build_cross_doc_edges_for_source(substrate, source_id)
    # Envelope shape: keep the atom→entity dict under ``atom_entity`` so
    # the cross-doc-edges payload can ride along without colliding with
    # any user-supplied atom-id keys. The cytoscape overlay JS will
    # read ``cross_doc_edges`` and feed each edge into the canvas.
    payload: dict[str, object] = {
        "atom_entity": index,
        "cross_doc_edges": cross_doc_edges,
    }
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "no-store"},
    )


def _build_cross_doc_edges_for_source(
    substrate: Substrate,
    source_id: str,
) -> list[dict[str, object]]:
    """Return cross-doc edges touching ``source_id`` as flat dicts.

    Filters via ``Substrate.list_cross_doc_relations(touching_source=...)``
    so the returned set contains every edge incident to the distillation
    regardless of direction. Each entry is a JSON-serializable dict
    suitable for the Cytoscape overlay JS to consume verbatim.

    Order follows the substrate iterator (lex-id), which is
    deterministic across runs.
    """
    edges: list[dict[str, object]] = []
    for rel in substrate.list_cross_doc_relations(touching_source=source_id):
        edges.append(
            {
                "id": rel.id,
                "from_source_id": rel.from_source_id,
                "from_atom_id": rel.from_atom_id,
                "to_source_id": rel.to_source_id,
                "to_atom_id": rel.to_atom_id,
                "kind": rel.kind,
                "shared_entities": list(rel.shared_entities),
            }
        )
    return edges
