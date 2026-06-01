"""INV-17 — Every non-ultimate probandum's lineage reaches an ultimate.

Walks every probandum-edge under ``mappings/probandum-edges/`` and
verifies that the proposed parent traces upward through incoming edges
to at least one ``Probandum`` with ``kind == "ultimate"``. Catches
edges that bypassed the substrate write gate (e.g., manually edited
YAML).

The helper re-runs the INV-17 gate by attempting to re-add every
on-disk probandum-edge via ``Substrate.add_probandum_edge``. For valid
edges the re-add is a no-op (idempotency); for edges whose parent does
not trace to an ultimate the gate raises ``LineageIncomplete``.

Fixtures bypass ``add_probandum_edge`` by writing YAML directly so the
walker can observe the orphan / dangling state on disk and trip the
gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import (
    LineageIncomplete,
    Substrate,
)
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import (
    serialize_probandum_edge_yaml,
    serialize_probandum_md,
)
from amanuensis.schemas import (
    Probandum,
    ProbandumEdge,
    RoleAttribution,
    compute_id,
)

pytestmark = pytest.mark.invariants


def _make_marker(workspace: Path, project_name: str) -> None:
    marker = workspace / "amanuensis.yaml"
    marker.write_text(
        f"schema_version: 1\nproject_name: {project_name}\n",
        encoding="utf-8",
    )


def _probandum(
    role_attribution: RoleAttribution,
    *,
    statement: str,
    kind: str = "interim",
    alternatives_considered: list[str] | None = None,
) -> Probandum:
    """Build a Probandum with a real content-addressable id."""
    payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "statement": statement,
        "kind": kind,
        "scheme": "argument-from-expert-opinion",
        "alternatives_considered": alternatives_considered
        if alternatives_considered is not None
        else (["alt"] if kind != "ultimate" else []),
        "confidence": "high",
        "provenance_id": "p-fixture-inv17-prob",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = Probandum(**payload)
    payload["id"] = compute_id(draft)
    return Probandum(**payload)


def _plant_probandum(workspace: Path, p: Probandum) -> None:
    """Write a Probandum directly to disk (bypasses substrate gates)."""
    path = workspace / "mappings" / "probanda" / f"{p.id}.md"
    atomic_write_text(path, serialize_probandum_md(p))


def _make_edge(
    role_attribution: RoleAttribution,
    *,
    parent_probandum_id: str,
    child_id: str,
    warrant: str = "Lineage fixture edge.",
) -> ProbandumEdge:
    """Build a ProbandumEdge with a real content-addressable id."""
    payload: dict[str, Any] = {
        "id": "q-" + "0" * 16,
        "parent_probandum_id": parent_probandum_id,
        "child_id": child_id,
        "child_kind": "probandum",
        "child_source_id": None,
        "kind": "supports",
        "warrant": warrant,
        "warrant_defensibility": "conventional",
        "warrant_basis": "fixture",
        "confidence": "medium",
        "provenance_id": "p-fixture-inv17-edge",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = ProbandumEdge(**payload)
    payload["id"] = compute_id(draft)
    return ProbandumEdge(**payload)


def _plant_edge(workspace: Path, edge: ProbandumEdge) -> None:
    """Write a ProbandumEdge directly to disk (bypasses substrate gates)."""
    path = workspace / "mappings" / "probandum-edges" / f"{edge.id}.yaml"
    atomic_write_text(path, serialize_probandum_edge_yaml(edge))


def _plant_walton_snapshot(workspace: Path) -> None:
    """Pin the generic Walton snapshot so INV-18 doesn't block planted probanda."""
    Substrate(workspace).snapshot_walton_schemes()


# --- Fixtures ---------------------------------------------------------


@pytest.fixture
def tmp_workspace_inv17_clean(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """Clean tree with full lineage: ult → pen → interim. Passes INV-17."""
    _make_marker(tmp_path, "inv17-clean")
    _plant_walton_snapshot(tmp_path)
    ult = _probandum(role_attribution, statement="Ultimate.", kind="ultimate")
    pen = _probandum(role_attribution, statement="Pen.", kind="penultimate")
    interim = _probandum(role_attribution, statement="Interim.", kind="interim")
    for p in (ult, pen, interim):
        _plant_probandum(tmp_path, p)
    _plant_edge(
        tmp_path,
        _make_edge(
            role_attribution, parent_probandum_id=ult.id, child_id=pen.id, warrant="Ult→pen."
        ),
    )
    _plant_edge(
        tmp_path,
        _make_edge(
            role_attribution,
            parent_probandum_id=pen.id,
            child_id=interim.id,
            warrant="Pen→interim.",
        ),
    )
    return tmp_path


@pytest.fixture
def tmp_workspace_inv17_orphan_interim(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """An interim probandum whose parent has no lineage to an ultimate.

    Plants:
    - A penultimate ``pen`` with NO incoming edge.
    - An interim ``interim`` linked by an edge ``pen → interim``.

    The edge passes parent / child existence but the parent ``pen``
    cannot trace to an ultimate, so INV-17 trips on the walker re-run.
    """
    _make_marker(tmp_path, "inv17-orphan-interim")
    _plant_walton_snapshot(tmp_path)
    pen = _probandum(role_attribution, statement="Orphan pen.", kind="penultimate")
    interim = _probandum(role_attribution, statement="Orphan interim.", kind="interim")
    _plant_probandum(tmp_path, pen)
    _plant_probandum(tmp_path, interim)
    _plant_edge(
        tmp_path,
        _make_edge(
            role_attribution,
            parent_probandum_id=pen.id,
            child_id=interim.id,
            warrant="Orphan-parent edge.",
        ),
    )
    return tmp_path


@pytest.fixture
def tmp_workspace_inv17_penultimate_without_parent(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """A penultimate filed via an edge whose parent (another penultimate) has no ultimate above it.

    Plants:
    - ``pen_a`` (penultimate, NO parent edge).
    - ``pen_b`` (penultimate).
    - Edge ``pen_a → pen_b``.

    The parent of the edge (``pen_a``) is itself a non-ultimate with no
    incoming edge to an ultimate. INV-17 trips on the walker re-run.
    """
    _make_marker(tmp_path, "inv17-pen-no-parent")
    _plant_walton_snapshot(tmp_path)
    pen_a = _probandum(role_attribution, statement="Penultimate A (no parent).", kind="penultimate")
    pen_b = _probandum(role_attribution, statement="Penultimate B.", kind="penultimate")
    _plant_probandum(tmp_path, pen_a)
    _plant_probandum(tmp_path, pen_b)
    _plant_edge(
        tmp_path,
        _make_edge(
            role_attribution,
            parent_probandum_id=pen_a.id,
            child_id=pen_b.id,
            warrant="pen_a → pen_b (parent has no lineage).",
        ),
    )
    return tmp_path


@pytest.fixture
def tmp_workspace_inv17_chain_ends_at_penultimate(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """A chain ``pen → interim_a → interim_b`` whose top is a penultimate (no ultimate).

    Walking incoming edges from any node terminates at ``pen``, which
    is NOT an ultimate. INV-17 trips on every non-root edge in the
    chain at re-walk.
    """
    _make_marker(tmp_path, "inv17-chain-no-ultimate")
    _plant_walton_snapshot(tmp_path)
    pen = _probandum(role_attribution, statement="Top is penultimate.", kind="penultimate")
    interim_a = _probandum(role_attribution, statement="Interim A.", kind="interim")
    interim_b = _probandum(role_attribution, statement="Interim B.", kind="interim")
    for p in (pen, interim_a, interim_b):
        _plant_probandum(tmp_path, p)
    _plant_edge(
        tmp_path,
        _make_edge(
            role_attribution,
            parent_probandum_id=pen.id,
            child_id=interim_a.id,
            warrant="pen → interim_a.",
        ),
    )
    _plant_edge(
        tmp_path,
        _make_edge(
            role_attribution,
            parent_probandum_id=interim_a.id,
            child_id=interim_b.id,
            warrant="interim_a → interim_b.",
        ),
    )
    return tmp_path


# --- Tests ------------------------------------------------------------


def test_clean_tree_passes(tmp_workspace_inv17_clean: Path) -> None:
    """A workspace with a full lineage tree passes the INV-17 walk."""
    sub = Substrate(tmp_workspace_inv17_clean)
    _walk_and_check(sub)  # must not raise


def test_orphan_interim_caught(tmp_workspace_inv17_orphan_interim: Path) -> None:
    """An interim probandum whose parent has no path to an ultimate is rejected."""
    sub = Substrate(tmp_workspace_inv17_orphan_interim)
    with pytest.raises(LineageIncomplete, match="lineage"):
        _walk_and_check(sub)


def test_penultimate_without_parent_caught(
    tmp_workspace_inv17_penultimate_without_parent: Path,
) -> None:
    """A penultimate parent with no incoming-to-ultimate edge is rejected."""
    sub = Substrate(tmp_workspace_inv17_penultimate_without_parent)
    with pytest.raises(LineageIncomplete, match="lineage"):
        _walk_and_check(sub)


def test_chain_ends_at_penultimate_caught(
    tmp_workspace_inv17_chain_ends_at_penultimate: Path,
) -> None:
    """A chain whose top node is a penultimate (not an ultimate) is rejected."""
    sub = Substrate(tmp_workspace_inv17_chain_ends_at_penultimate)
    with pytest.raises(LineageIncomplete, match="lineage"):
        _walk_and_check(sub)


def _walk_and_check(sub: Substrate) -> None:
    """Re-run the INV-17 gate on every on-disk probandum-edge.

    For each edge under ``mappings/probandum-edges/``, calls
    ``sub.add_probandum_edge(edge)`` — the substrate enforces INV-17
    on every write, so tampered records raise ``LineageIncomplete``.
    Valid records hit the idempotent no-op path.
    """
    for edge in sub.list_probandum_edges():
        sub.add_probandum_edge(edge)
