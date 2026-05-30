"""Atom routes — browser (with HTMX-driven filters) + detail-with-highlight.

Two routes:

- ``GET /distillations/<source-id>/atoms`` — table of every atom in the
  distillation, with three optional filters (``scale``, ``predicate``,
  ``paragraph_index``). HTMX-driven: the filter form swaps just the
  ``#atom-list`` fragment via ``hx-get="."`` + ``hx-target``. The route
  detects HTMX requests via the ``HX-Request`` header and returns just
  the fragment template; full page renders otherwise.

- ``GET /distillations/<source-id>/atoms/<atom-id>`` — single-atom
  detail page. Renders every atom field plus the source paragraph the
  atom anchors to, with the atom's ``char_span`` slice wrapped in a
  ``<mark>`` tag. Unknown atom ids return 404.

Filtering is done in Python (the substrate is small in Phase 1; query
optimization is Phase 4). Paragraph lookup uses the M3.1 width-4
zero-padded ``p-NNNN`` convention.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate, SubstrateInvalidId, SubstrateNotFound
from amanuensis.fs._serialize import parse_paragraph_md
from amanuensis.schemas import Atom

from ..dependencies import get_substrate

router = APIRouter()

# Width-4 zero-pad for paragraph ids (mirrors M3.1 ``_PARAGRAPH_ID_WIDTH``
# in the ingester modules — duplicated here rather than imported to keep
# the web package free of an ingest-package dependency).
_PARAGRAPH_ID_WIDTH = 4


def _paragraph_id_for_index(index: int) -> str:
    """Return ``p-NNNN`` for a paragraph index (M3.1 width-4 convention)."""
    return f"p-{index:0{_PARAGRAPH_ID_WIDTH}d}"


def _filter_atoms(
    atoms: list[Atom],
    *,
    scale: str | None,
    predicate: str | None,
    paragraph_index: int | None,
) -> list[Atom]:
    """Apply the three filter clauses in Python.

    Each clause is independently optional. ``predicate`` is a
    case-sensitive substring match (the supervisor types fragments to
    narrow); ``scale`` is exact-match; ``paragraph_index`` is exact-match.
    """
    filtered = atoms
    if scale is not None:
        filtered = [a for a in filtered if a.scale_anchor == scale]
    if predicate:
        filtered = [a for a in filtered if predicate in a.predicate]
    if paragraph_index is not None:
        filtered = [a for a in filtered if a.paragraph_index == paragraph_index]
    return filtered


def _ensure_distillation_exists(substrate: Substrate, source_id: str) -> None:
    """Translate Substrate id/path errors into a 404 for the route layer."""
    try:
        distillation_root = substrate.root / "distillations" / source_id
        # Touching ``manifest_path`` runs the id-validator — same trick
        # the source-overview route uses.
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


@router.get("/distillations/{source_id}/atoms", response_class=HTMLResponse)
async def atom_browser(
    request: Request,
    source_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
    scale: Annotated[
        Literal["sentence", "paragraph", "section", "document"] | None,
        Query(description="Filter atoms by scale_anchor"),
    ] = None,
    predicate: Annotated[
        str | None,
        Query(description="Substring match against atom.predicate"),
    ] = None,
    paragraph_index: Annotated[
        int | None,
        Query(description="Exact-match filter on atom.paragraph_index"),
    ] = None,
) -> HTMLResponse:
    """Render the atom browser (full page) or the atom-list fragment.

    HTMX requests (header ``HX-Request: true``) get just the
    ``#atom-list`` fragment so the filter form swaps in-place; everything
    else gets the full page. Both renders share the same filter logic +
    context payload so behaviour stays parallel.
    """
    _ensure_distillation_exists(substrate, source_id)

    atoms = list(substrate.list_atoms(source_id))
    filtered = _filter_atoms(
        atoms,
        scale=scale,
        predicate=predicate,
        paragraph_index=paragraph_index,
    )
    context: dict[str, object] = {
        "source_id": source_id,
        "atoms": filtered,
        "total_atoms": len(atoms),
        "filtered_count": len(filtered),
        "scale": scale or "",
        "predicate": predicate or "",
        "paragraph_index": "" if paragraph_index is None else paragraph_index,
    }

    templates = request.app.state.templates
    template_name = (
        "atom_list_fragment.html"
        if request.headers.get("HX-Request") == "true"
        else "atom_browser.html"
    )
    return templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        template_name,
        context,
    )


def _highlight_segments(body: str, char_span: tuple[int, int]) -> tuple[str, str, str]:
    """Slice ``body`` into ``(before, highlight, after)`` for the ``<mark>``.

    Out-of-range spans are clamped to ``[0, len(body)]``; the schema
    already guarantees ``start < end`` (see ``Atom._char_span_ordered``)
    but a paragraph body that has been edited or truncated can still
    leave a span dangling. Clamping keeps the page renderable instead
    of raising; the template surfaces the raw span numbers separately
    so callers can spot the mismatch.
    """
    start, end = char_span
    n = len(body)
    start = max(0, min(start, n))
    end = max(start, min(end, n))
    return body[:start], body[start:end], body[end:]


@router.get(
    "/distillations/{source_id}/atoms/{atom_id}",
    response_class=HTMLResponse,
)
async def atom_detail(
    request: Request,
    source_id: str,
    atom_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """Render the per-atom detail page with source-paragraph highlight.

    The route fetches the atom (404 on miss), then attempts to load the
    source-mirror paragraph file at the width-4 padded id derived from
    ``atom.paragraph_index``. A missing paragraph file does NOT 404 —
    the atom is still renderable; the template just omits the
    highlight block and surfaces a "paragraph file missing" notice.
    """
    _ensure_distillation_exists(substrate, source_id)

    try:
        atom = substrate.get_atom(source_id, atom_id)
    except SubstrateInvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"atom {atom_id!r} not found",
        ) from exc
    except SubstrateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"atom {atom_id!r} not found",
        ) from exc

    paragraph_id = _paragraph_id_for_index(atom.paragraph_index)
    paragraph_path = substrate.paragraph_path(source_id, paragraph_id)

    before = highlight = after = ""
    paragraph_body: str | None = None
    if paragraph_path.is_file():
        try:
            _frontmatter, paragraph_body = parse_paragraph_md(
                paragraph_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            # A corrupt paragraph file is a substrate-integrity issue,
            # not a 500. Surface the atom unhighlighted and let the
            # supervisor investigate via the source-overview page.
            paragraph_body = None
        if paragraph_body is not None:
            before, highlight, after = _highlight_segments(paragraph_body, atom.char_span)

    templates = request.app.state.templates
    return templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "atom_detail.html",
        {
            "source_id": source_id,
            "atom": atom,
            "paragraph_id": paragraph_id,
            "paragraph_body": paragraph_body,
            "before": before,
            "highlight": highlight,
            "after": after,
        },
    )
