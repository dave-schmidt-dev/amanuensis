"""Probanda routes — list browser + detail page (Phase 2c M10).

Routes:

- ``GET /probanda`` — table of all Probandum records with optional
  ``?kind=`` and ``?scheme=`` filters. Sort order is lex-id (mirrors
  ``Substrate.list_probanda``). Headers: ``Cache-Control: no-store``.

- ``GET /probanda/<id>`` — single-probandum detail page. Renders
  statement, scheme, alternatives, confidence, lineage (walking
  INCOMING probandum-edges up to the terminal ``ultimate``), outgoing
  edges, provenance, and the supersede chain. Returns 404 on unknown
  id. Headers: ``Cache-Control: no-store``.

Read-only per Phase 2c spec: probandum mutations are CLI-only. T10.4
will add the Cytoscape tree view routes to this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate, SubstrateNotFound
from amanuensis.schemas import Probandum, ProbandumSupersede

from ..dependencies import get_substrate

router = APIRouter()


@dataclass
class _SupersedeChainEntry:
    """One line in the supersede-chain section on the detail page.

    Mirrors the cross-doc-relation route's helper (Phase 2b M8 T8.3).
    ``direction='forward'`` means this probandum has been superseded by
    ``other_id`` (rendered as "Superseded by <other>"). ``'backward'``
    means this probandum supersedes ``other_id``.
    """

    direction: Literal["forward", "backward"]
    other_id: str
    reason: str


def _walk_supersede_chain(
    substrate: Substrate,
    probandum_id: str,
) -> list[_SupersedeChainEntry]:
    """Return both forward and backward supersede neighbours for ``probandum_id``.

    Mirrors the cross-doc-relation route's helper. Filters the unified
    supersedes dispatch to ``kind="probandum"`` records.
    """
    entries: list[_SupersedeChainEntry] = []
    for record in substrate.list_supersedes(kind="probandum"):
        if not isinstance(record, ProbandumSupersede):
            continue  # type-narrowing for Pyright; runtime is already filtered
        if record.supersedes_id == probandum_id:
            entries.append(
                _SupersedeChainEntry(
                    direction="forward",
                    other_id=record.superseded_by_id,
                    reason=record.reason,
                )
            )
        if record.superseded_by_id == probandum_id:
            entries.append(
                _SupersedeChainEntry(
                    direction="backward",
                    other_id=record.supersedes_id,
                    reason=record.reason,
                )
            )
    return entries


def _statement_excerpt(statement: str, max_chars: int = 100) -> str:
    """Return a short excerpt of a probandum statement for table rendering.

    Trims at a word boundary near ``max_chars`` and appends an ellipsis.
    Used by the list view's "statement excerpt" column so wide tables
    stay scannable. Empty / short statements pass through unchanged.
    """
    if len(statement) <= max_chars:
        return statement
    # Find a word boundary near the cap. Falls back to a hard cut if
    # no whitespace appears in the first ``max_chars`` chars.
    cutoff = statement.rfind(" ", 0, max_chars)
    if cutoff <= 0:
        cutoff = max_chars
    return statement[:cutoff].rstrip() + "…"


# ---------------------------------------------------------------------------
# T10.1 — list route
# ---------------------------------------------------------------------------


@router.get("/probanda", response_class=HTMLResponse)
async def probanda_list(
    request: Request,
    substrate: Annotated[Substrate, Depends(get_substrate)],
    kind: Annotated[
        str | None,
        Query(description="Filter by probandum kind (ultimate / penultimate / interim)."),
    ] = None,
    scheme: Annotated[
        str | None,
        Query(description="Filter by Walton scheme (exact match)."),
    ] = None,
) -> HTMLResponse:
    """Render the probanda browser with optional filters.

    ``kind`` is validated against the schema's allowed values; an
    unrecognized value short-circuits to an empty list because
    ``Substrate.list_probanda`` has a ``Literal``-typed filter and
    will reject anything else.
    """
    allowed_kinds = {"ultimate", "penultimate", "interim"}
    if kind is not None and kind not in allowed_kinds:
        probanda: list[Probandum] = []
    else:
        probanda = list(
            substrate.list_probanda(
                kind=kind,  # type: ignore[arg-type]
                scheme=scheme,
            )
        )

    # Statement excerpts are computed server-side to keep the template
    # free of Jinja substring-slicing logic.
    rendered = [
        {
            "id": p.id,
            "kind": p.kind,
            "scheme": p.scheme,
            "statement_excerpt": _statement_excerpt(p.statement),
            "confidence": p.confidence,
        }
        for p in probanda
    ]

    # Distinct kinds for the filter dropdown (always the full vocabulary
    # — we cannot enumerate from disk when the list is empty post-filter).
    kinds = ["ultimate", "penultimate", "interim"]

    templates = request.app.state.templates
    response = templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "probanda_list.html",
        {
            "probanda": rendered,
            "filtered_count": len(rendered),
            "kinds": kinds,
            "kind": kind or "",
            "scheme": scheme or "",
        },
    )
    response.headers["cache-control"] = "no-store"
    return response  # pyright: ignore[reportReturnType]


# ---------------------------------------------------------------------------
# T10.2 — detail route
# ---------------------------------------------------------------------------


@dataclass
class _LineageStep:
    """One ancestor in the lineage walk from this probandum up to ``ultimate``."""

    probandum_id: str
    statement: str
    kind: str


def _walk_lineage_to_ultimate(
    substrate: Substrate, probandum_id: str, max_depth: int = 100
) -> list[_LineageStep]:
    """Walk INCOMING probandum-edges (where this is the child) up to ``ultimate``.

    Returns a list of ancestors in order: the first entry is the
    immediate parent, the last entry is the terminal ``ultimate`` (or
    whatever the walk reaches when no further parent exists). The
    starting node itself is NOT included.

    Defensive depth-cap mirrors the substrate's BFS guards. If the
    upward walk forks (multi-parent — unusual for a Wigmore tree but
    not gated at the schema layer), the first lex-ordered parent is
    followed.
    """
    lineage: list[_LineageStep] = []
    current = probandum_id
    visited: set[str] = {current}
    for _ in range(max_depth):
        # Find an incoming edge whose ``child_id`` is the current node
        # and ``child_kind == "probandum"`` (atom/cross-doc children
        # cannot have parents above them in this graph).
        parents: list[str] = []
        for edge in substrate.list_probandum_edges():
            if edge.child_kind != "probandum":
                continue
            if edge.child_id != current:
                continue
            parents.append(edge.parent_probandum_id)
        if not parents:
            break
        # Pick the first lex-ordered parent for determinism.
        parents.sort()
        next_id = parents[0]
        if next_id in visited:
            # Defensive: a cycle would have been gated at write-time
            # (INV-16), but the walk is depth-capped anyway. Stop.
            break
        visited.add(next_id)
        try:
            parent = substrate.get_probandum(next_id)
        except SubstrateNotFound:
            break
        lineage.append(
            _LineageStep(probandum_id=parent.id, statement=parent.statement, kind=parent.kind)
        )
        if parent.kind == "ultimate":
            break
        current = next_id
    return lineage


def _build_outgoing_edges(substrate: Substrate, probandum_id: str) -> list[dict[str, str | None]]:
    """Return outgoing probandum-edges from ``probandum_id`` for rendering.

    Each item carries the fields the template needs to render a child
    row: edge id, edge kind, child id, child kind, child source id (for
    atoms), and a label hint (the child's statement / narrative when
    we can load it; ``None`` otherwise — the template renders a
    ``<missing>`` placeholder so a broken edge does not vanish).
    """
    items: list[dict[str, str | None]] = []
    for edge in substrate.list_probandum_edges(parent_probandum_id=probandum_id):
        item: dict[str, str | None] = {
            "edge_id": edge.id,
            "edge_kind": edge.kind,
            "child_id": edge.child_id,
            "child_kind": edge.child_kind,
            "child_source_id": edge.child_source_id,
            "label": None,
        }
        # Best-effort label: probandum statement, atom narrative,
        # cross-doc-relation warrant. Missing children stay None.
        try:
            if edge.child_kind == "probandum":
                child = substrate.get_probandum(edge.child_id)
                item["label"] = _statement_excerpt(child.statement, max_chars=80)
            elif edge.child_kind == "atom" and edge.child_source_id is not None:
                atom = substrate.get_atom(edge.child_source_id, edge.child_id)
                item["label"] = _statement_excerpt(atom.narrative, max_chars=80)
            elif edge.child_kind == "cross-doc-relation":
                rel = substrate.get_cross_doc_relation(edge.child_id)
                item["label"] = _statement_excerpt(rel.warrant, max_chars=80)
        except SubstrateNotFound:
            item["label"] = None
        items.append(item)
    return items


@router.get("/probanda/{probandum_id}", response_class=HTMLResponse)
async def probandum_detail(
    request: Request,
    probandum_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """Render the per-probandum detail page.

    Sections: header (id + kind), statement, scheme, alternatives,
    confidence, lineage (incoming edges up to ``ultimate``), outgoing
    edges, provenance, and the supersede chain.
    """
    try:
        probandum = substrate.get_probandum(probandum_id)
    except SubstrateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"probandum {probandum_id!r} not found",
        ) from exc

    lineage = _walk_lineage_to_ultimate(substrate, probandum_id)
    outgoing = _build_outgoing_edges(substrate, probandum_id)
    chain_entries = _walk_supersede_chain(substrate, probandum_id)

    templates = request.app.state.templates
    response = templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "probandum_detail.html",
        {
            "probandum": probandum,
            "lineage": lineage,
            "outgoing": outgoing,
            "chain_entries": chain_entries,
        },
    )
    response.headers["cache-control"] = "no-store"
    return response  # pyright: ignore[reportReturnType]
