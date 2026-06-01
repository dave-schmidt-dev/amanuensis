"""Probandum-edge routes — detail page (Phase 2c M10 T10.3).

Single route:

- ``GET /probandum-edges/<id>`` — detail page for one ProbandumEdge.
  Renders the parent probandum (linked), child (linked appropriately
  by kind), edge kind badge, warrant block (warrant text,
  defensibility, basis, confidence), provenance id, and the supersede
  chain. Returns 404 on unknown id. Headers: ``Cache-Control: no-store``.

Detail-only by design — there is no list browser. Probandum edges are
plumbing in the argument tree; the supervisor browses them by drilling
from a probandum-detail page or via the tree view (T10.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate, SubstrateNotFound
from amanuensis.schemas import ProbandumEdgeSupersede

from ..dependencies import get_substrate

router = APIRouter()


@dataclass
class _EdgeSupersedeChainEntry:
    """One line in the supersede-chain section on the edge detail page.

    Mirrors the cross-doc-relation route's helper and the
    ``_SupersedeChainEntry`` shape used by ``probanda.py``.
    """

    direction: Literal["forward", "backward"]
    other_id: str
    reason: str


def _walk_edge_supersede_chain(
    substrate: Substrate,
    edge_id: str,
) -> list[_EdgeSupersedeChainEntry]:
    """Return both forward and backward supersede neighbours for ``edge_id``.

    Filters the unified supersedes dispatch to
    ``kind="probandum-edge"`` records (id prefix ``o-``).
    """
    entries: list[_EdgeSupersedeChainEntry] = []
    for record in substrate.list_supersedes(kind="probandum-edge"):
        if not isinstance(record, ProbandumEdgeSupersede):
            continue  # type-narrowing for Pyright
        if record.supersedes_id == edge_id:
            entries.append(
                _EdgeSupersedeChainEntry(
                    direction="forward",
                    other_id=record.superseded_by_id,
                    reason=record.reason,
                )
            )
        if record.superseded_by_id == edge_id:
            entries.append(
                _EdgeSupersedeChainEntry(
                    direction="backward",
                    other_id=record.supersedes_id,
                    reason=record.reason,
                )
            )
    return entries


@router.get("/probandum-edges/{edge_id}", response_class=HTMLResponse)
async def probandum_edge_detail(
    request: Request,
    edge_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """Render the per-edge detail page.

    Sections: header (id + kind), parent (linked to its probandum
    detail page), child (linked appropriately by child_kind), warrant
    block, provenance, and supersede chain.
    """
    try:
        edge = substrate.get_probandum_edge(edge_id)
    except SubstrateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"probandum edge {edge_id!r} not found",
        ) from exc

    chain_entries = _walk_edge_supersede_chain(substrate, edge_id)

    # Best-effort labels for parent + child so the page is readable
    # even when the rendered ids are opaque hashes. Missing records
    # fall through to None — the template renders the bare id only.
    parent_label: str | None = None
    try:
        parent = substrate.get_probandum(edge.parent_probandum_id)
        parent_label = parent.statement
    except SubstrateNotFound:
        parent_label = None

    child_label: str | None = None
    if edge.child_kind == "probandum":
        try:
            child = substrate.get_probandum(edge.child_id)
            child_label = child.statement
        except SubstrateNotFound:
            child_label = None
    elif edge.child_kind == "atom" and edge.child_source_id is not None:
        try:
            atom = substrate.get_atom(edge.child_source_id, edge.child_id)
            child_label = atom.narrative
        except SubstrateNotFound:
            child_label = None
    elif edge.child_kind == "cross-doc-relation":
        try:
            rel = substrate.get_cross_doc_relation(edge.child_id)
            child_label = rel.warrant
        except SubstrateNotFound:
            child_label = None

    templates = request.app.state.templates
    response = templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "probandum_edge_detail.html",
        {
            "edge": edge,
            "parent_label": parent_label,
            "child_label": child_label,
            "chain_entries": chain_entries,
        },
    )
    response.headers["cache-control"] = "no-store"
    return response  # pyright: ignore[reportReturnType]
