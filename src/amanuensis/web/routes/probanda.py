"""Probanda routes — list browser (Phase 2c M10).

Routes:

- ``GET /probanda`` — table of all Probandum records with optional
  ``?kind=`` and ``?scheme=`` filters. Sort order is lex-id (mirrors
  ``Substrate.list_probanda``). Headers: ``Cache-Control: no-store``.

Read-only per Phase 2c spec: probandum mutations are CLI-only. T10.2+
will add detail + Cytoscape tree routes to this module.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate
from amanuensis.schemas import Probandum

from ..dependencies import get_substrate

router = APIRouter()


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
