"""Supervisor-write forms: clarification resolve + iteration directive add (M8.5).

Two paired routes, four total endpoints, behind the workspace flock:

- ``GET  /clarifications``                      list (open + resolved)
- ``POST /clarifications/<id>/resolve``         flip open -> resolved
- ``GET  /iterations``                          list directives + add form
- ``POST /iterations/add``                      issue a new directive

Both POST handlers mirror the M4.3 CLI semantics (see
``amanuensis.cli.clarification`` and ``amanuensis.cli.iteration``):

1. acquire the workspace flock with a 5s timeout (plan §5);
2. build the paired PROV record + the mutated artifact;
3. write atomically via ``Substrate.add_*``;
4. on success, redirect with 303 back to the listing page.

A flock timeout surfaces as a 503 rendered via ``_form_error.html`` so
the supervisor sees a clear message instead of an opaque error.
Unknown-id POSTs return 404; invalid form data (e.g. an unknown
``target_phase``) returns 400 without touching the substrate.

The router exports ``router: APIRouter`` at module level so the
orchestrator can wire it via ``app.include_router(...)`` once M8.5's
sibling routes have landed. This module deliberately does NOT touch
``amanuensis.web.app``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from amanuensis.fs import (
    Substrate,
    WorkspaceLockTimeout,
    acquire_workspace_lock,
)
from amanuensis.fs._serialize import parse_clarification_md, parse_iteration_md
from amanuensis.schemas import (
    AgentAttribution,
    Clarification,
    IterationDirective,
    ProvenanceRecord,
    compute_id,
)

from ..dependencies import get_substrate

router = APIRouter()

# Phases an iteration directive may target. Mirrors the literal on
# ``IterationDirective.target_phase`` so an unknown value is rejected at
# the route layer (before any flock acquisition) rather than at write
# time. Kept duplicated rather than imported from the CLI module so the
# web package does not pull in typer.
_TARGET_PHASES: tuple[str, ...] = ("distill", "map", "extend", "synthesize")

# Flock timeout for web POSTs — plan §5 says 5 seconds. Lifted as a
# module constant so tests can monkeypatch a tighter value.
_FORM_LOCK_TIMEOUT_SECONDS: float = 5.0


# ---------------------------------------------------------------------------
# Helpers shared by list + POST handlers.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ClarificationRow:
    """Listing row for ``/clarifications``.

    Mirrors the (source_id, clarification) tuple yielded by the CLI's
    ``_iter_clarifications`` walker, but as a dataclass so the template
    can address the source_id and the clarification fields by attribute
    instead of unpacking a tuple.
    """

    source_id: str
    clarification: Clarification


def _list_distillation_source_ids(substrate: Substrate) -> list[str]:
    """Return source_ids that have a ``distillations/<id>/`` directory.

    Duplicated from ``_substrate_counts.list_distillation_source_ids``
    rather than imported so a future refactor of the dashboard helpers
    does not silently change the form-route walker. Cheap to keep both.
    """
    dist_root = substrate.root / "distillations"
    if not dist_root.is_dir():
        return []
    return sorted(p.name for p in dist_root.iterdir() if p.is_dir())


def _iter_clarifications(substrate: Substrate) -> list[_ClarificationRow]:
    """Walk every distillation; return rows for both open + resolved buckets.

    Lex-sorted by source_id then by clarification id. Skips ``.tmp.*``
    writer leftovers and any clarification whose Markdown will not parse
    (a corrupt-on-disk file is a substrate-integrity issue surfaced
    elsewhere; this listing should still render).
    """
    out: list[_ClarificationRow] = []
    for source_id in _list_distillation_source_ids(substrate):
        for bucket in ("open", "resolved"):
            bucket_dir = substrate.root / "distillations" / source_id / "clarifications" / bucket
            if not bucket_dir.is_dir():
                continue
            for path in sorted(bucket_dir.iterdir()):
                if not path.is_file() or not path.name.endswith(".md"):
                    continue
                if ".tmp." in path.name:
                    continue
                try:
                    clar = parse_clarification_md(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                out.append(_ClarificationRow(source_id=source_id, clarification=clar))
    return out


def _find_open_clarification(
    substrate: Substrate, clarification_id: str
) -> tuple[str, Clarification] | None:
    """Locate an open clarification by id across every distillation.

    Returns ``(source_id, clarification)`` or ``None`` if no open
    clarification with that id exists. The caller maps ``None`` to a
    404; a separately-stored resolved variant is treated as
    not-eligible (mirrors the CLI's ``_find_clarification``).
    """
    for source_id in _list_distillation_source_ids(substrate):
        open_path = substrate.clarification_path(source_id, clarification_id, resolved=False)
        if open_path.is_file():
            try:
                clar = parse_clarification_md(open_path.read_text(encoding="utf-8"))
            except Exception:
                # Treat corrupt on-disk file as "not found" for resolve.
                return None
            return source_id, clar
    return None


def _list_iterations(substrate: Substrate) -> list[IterationDirective]:
    """Return every iteration directive at the workspace root (lex sorted).

    Skips ``.tmp.*`` leftovers and unparseable files (same rationale as
    the clarification walker above).
    """
    iters_dir = substrate.root / "iterations"
    if not iters_dir.is_dir():
        return []
    out: list[IterationDirective] = []
    for path in sorted(iters_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".md"):
            continue
        if ".tmp." in path.name:
            continue
        try:
            out.append(parse_iteration_md(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def _render_lock_timeout(request: Request, *, action: str) -> HTMLResponse:
    """Render the generic flock-timeout error page as a 503."""
    templates = request.app.state.templates
    return templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "_form_error.html",
        {
            "title": "workspace busy",
            "action": action,
            "message": (
                "another amanuensis process is holding the workspace lock "
                f"(waited {_FORM_LOCK_TIMEOUT_SECONDS:.0f}s). try again in "
                "a moment, or check for a running CLI distill/dispatch."
            ),
        },
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ---------------------------------------------------------------------------
# Routes — clarifications.
# ---------------------------------------------------------------------------


@router.get("/clarifications", response_class=HTMLResponse)
async def clarifications_list(
    request: Request,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """List every clarification across every distillation, grouped by status."""
    rows = _iter_clarifications(substrate)
    open_rows = [r for r in rows if r.clarification.status == "open"]
    resolved_rows = [r for r in rows if r.clarification.status == "resolved"]
    templates = request.app.state.templates
    return templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "clarifications.html",
        {
            "workspace_path": str(substrate.root),
            "open_rows": open_rows,
            "resolved_rows": resolved_rows,
            "total": len(rows),
        },
    )


@router.post("/clarifications/{clarification_id}/resolve", response_model=None)
async def clarifications_resolve(
    request: Request,
    clarification_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
    source_id: Annotated[str, Form()],
    resolution: Annotated[str, Form()],
    resolver: Annotated[str, Form()] = "web-supervisor",
) -> HTMLResponse | RedirectResponse:
    """Resolve an open clarification — mirrors M4.3 ``clarification resolve`` CLI.

    Acquires the workspace flock (5s timeout). On success: 303 redirect
    back to ``/clarifications``. On flock timeout: 503 + rendered error
    page. On unknown id: 404 (no flock acquired). The ``source_id``
    field is required even though the id alone could locate the file
    (the CLI mirrors this convention).
    """
    # Validate form basics before acquiring the flock — a blank
    # resolution is operator error, not contention.
    if not resolution.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="resolution must be non-empty",
        )

    try:
        with acquire_workspace_lock(substrate.root, timeout=_FORM_LOCK_TIMEOUT_SECONDS):
            found = _find_open_clarification(substrate, clarification_id)
            if found is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"open clarification {clarification_id!r} not found",
                )
            actual_source_id, original = found
            # The form-supplied ``source_id`` is a hint; if it disagrees
            # with the one the walker found we use the walker's truth
            # (the id-lookup is the canonical resolution). ``source_id``
            # is captured in the form so the template can target the
            # right resolve endpoint even when multiple distillations
            # have clarifications.
            _ = source_id

            now = datetime.now(UTC)
            resolved_by = AgentAttribution(
                kind="human",
                identifier=resolver,
                role="human_supervisor",
            )

            prov_draft = ProvenanceRecord(
                id="p-" + "0" * 16,
                entity_type="clarification-resolved",
                entity_id=original.id,
                activity="clarification-resolve",
                activity_started_at=now,
                activity_ended_at=now,
                used_entity_ids=[original.raised_provenance_id],
                was_attributed_to=resolved_by,
                was_influenced_by=[],
                schema_version=1,
            )
            prov_id = compute_id(prov_draft)
            prov = prov_draft.model_copy(update={"id": prov_id})
            substrate.add_provenance(actual_source_id, prov)

            resolved_clar = original.model_copy(
                update={
                    "status": "resolved",
                    "resolved_at": now,
                    "resolved_by": resolved_by,
                    "resolution": resolution,
                    "resolved_provenance_id": prov.id,
                }
            )
            substrate.add_clarification(actual_source_id, resolved_clar)

            # Remove the open-bucket file so readers see one canonical
            # location. The resolved variant has already been written
            # atomically; unlink failure is logged-and-swallowed
            # (idempotent: a re-resolve attempt would simply see no
            # open file and 404).
            open_path = substrate.clarification_path(
                actual_source_id, clarification_id, resolved=False
            )
            try:
                open_path.unlink()
            except FileNotFoundError:  # pragma: no cover - already gone
                pass
    except WorkspaceLockTimeout:
        return _render_lock_timeout(request, action="resolve clarification")

    return RedirectResponse(
        url="/clarifications",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Routes — iterations.
# ---------------------------------------------------------------------------


@router.get("/iterations", response_class=HTMLResponse)
async def iterations_list(
    request: Request,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """List every iteration directive at the workspace root + show add form."""
    directives = _list_iterations(substrate)
    source_ids = _list_distillation_source_ids(substrate)
    templates = request.app.state.templates
    return templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "iterations.html",
        {
            "workspace_path": str(substrate.root),
            "directives": directives,
            "source_ids": source_ids,
            "target_phases": _TARGET_PHASES,
        },
    )


@router.post("/iterations/add", response_model=None)
async def iterations_add(
    request: Request,
    substrate: Annotated[Substrate, Depends(get_substrate)],
    directive: Annotated[str, Form()],
    target_source: Annotated[str, Form()],
    target_phase: Annotated[str, Form()] = "distill",
    rationale: Annotated[str, Form()] = "(no rationale recorded)",
    issuer: Annotated[str, Form()] = "web-supervisor",
) -> HTMLResponse | RedirectResponse:
    """Issue a new iteration directive — mirrors M4.3 ``iteration add`` CLI.

    Acquires the workspace flock (5s timeout). On success: 303 redirect
    back to ``/iterations``. Unknown ``target_phase`` is rejected with
    400 before the flock is touched. Empty ``directive`` / blank
    ``target_source`` likewise 400.
    """
    if not directive.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="directive must be non-empty",
        )
    if not target_source.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_source must be non-empty",
        )
    if target_phase not in _TARGET_PHASES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"unknown target_phase {target_phase!r}; choices: {', '.join(_TARGET_PHASES)}"),
        )
    target_phase_lit = cast("Literal['distill', 'map', 'extend', 'synthesize']", target_phase)

    now = datetime.now(UTC)
    issued_by = AgentAttribution(
        kind="human",
        identifier=issuer,
        role="human_supervisor",
    )

    try:
        with acquire_workspace_lock(substrate.root, timeout=_FORM_LOCK_TIMEOUT_SECONDS):
            iter_draft = IterationDirective(
                id="i-" + "0" * 16,
                issued_at=now,
                issued_by=issued_by,
                target_phase=target_phase_lit,
                target_artifacts=[target_source],
                directive=directive,
                rationale=rationale,
                applied_at=None,
                applied_by=None,
                applied_outcome=None,
                issued_provenance_id="p-" + "0" * 16,
                applied_provenance_id=None,
                schema_version=1,
            )
            iter_id = compute_id(iter_draft)

            prov_draft = ProvenanceRecord(
                id="p-" + "0" * 16,
                entity_type="iteration-issued",
                entity_id=iter_id,
                activity="iteration-issue",
                activity_started_at=now,
                activity_ended_at=now,
                used_entity_ids=[],
                was_attributed_to=issued_by,
                was_influenced_by=[],
                schema_version=1,
            )
            prov_id = compute_id(prov_draft)
            prov = prov_draft.model_copy(update={"id": prov_id})
            substrate.add_provenance(target_source, prov)

            iter_obj = iter_draft.model_copy(
                update={
                    "id": iter_id,
                    "issued_provenance_id": prov.id,
                }
            )
            substrate.add_iteration(iter_obj)
    except WorkspaceLockTimeout:
        return _render_lock_timeout(request, action="issue iteration directive")

    return RedirectResponse(
        url="/iterations",
        status_code=status.HTTP_303_SEE_OTHER,
    )
