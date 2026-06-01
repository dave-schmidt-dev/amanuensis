"""INV-16 — Probandum-edge graph is a tree (no cycles, no multi-parent).

Walks every ProbandumEdge under ``mappings/probandum-edges/`` and
verifies the tree-shape invariant. Catches edges that bypassed the
substrate write gate (e.g., manually edited YAML).

The helper re-runs the INV-16 gate by attempting to re-add every
on-disk probandum-edge via ``Substrate.add_probandum_edge``. For valid
edges the re-add hits the idempotency path; for tampered edges (cycles,
multi-parent) the gate raises ``ProbandumTreeViolation``.

Fixtures bypass ``add_probandum_edge`` by writing YAML directly so the
walker can observe the cycle / multi-parent state on disk and trip the
gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import (
    ProbandumTreeViolation,
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
    """Build a Probandum with a real content-addressable id.

    Default ``alternatives_considered=["alt"]`` keeps the ACH gate
    happy for ``interim`` / ``penultimate`` kinds.
    """
    payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "statement": statement,
        "kind": kind,
        "scheme": "argument-from-expert-opinion",
        "alternatives_considered": alternatives_considered
        if alternatives_considered is not None
        else (["alt"] if kind != "ultimate" else []),
        "confidence": "high",
        "provenance_id": "p-fixture-inv16-prob",
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
    warrant: str = "Tree-shape fixture edge.",
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
        "provenance_id": "p-fixture-inv16-edge",
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
def tmp_workspace_inv16_clean(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """Clean tree: ult → pen → interim. Passes INV-16."""
    _make_marker(tmp_path, "inv16-clean")
    _plant_walton_snapshot(tmp_path)
    ult = _probandum(role_attribution, statement="Ultimate.", kind="ultimate")
    pen = _probandum(
        role_attribution,
        statement="Penultimate.",
        kind="penultimate",
        alternatives_considered=["alt"],
    )
    interim = _probandum(
        role_attribution, statement="Interim.", kind="interim", alternatives_considered=["alt"]
    )
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
def tmp_workspace_inv16_self_loop(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """A planted edge whose parent and child are the same probandum (self-loop)."""
    _make_marker(tmp_path, "inv16-self-loop")
    _plant_walton_snapshot(tmp_path)
    ult = _probandum(role_attribution, statement="Self-loop target.", kind="ultimate")
    _plant_probandum(tmp_path, ult)
    _plant_edge(
        tmp_path,
        _make_edge(
            role_attribution, parent_probandum_id=ult.id, child_id=ult.id, warrant="Self-loop."
        ),
    )
    return tmp_path


@pytest.fixture
def tmp_workspace_inv16_two_cycle(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """Planted two-cycle: ult → pen AND pen → ult."""
    _make_marker(tmp_path, "inv16-two-cycle")
    _plant_walton_snapshot(tmp_path)
    ult = _probandum(role_attribution, statement="Ult in cycle.", kind="ultimate")
    pen = _probandum(
        role_attribution,
        statement="Pen in cycle.",
        kind="penultimate",
        alternatives_considered=["alt"],
    )
    _plant_probandum(tmp_path, ult)
    _plant_probandum(tmp_path, pen)
    _plant_edge(
        tmp_path,
        _make_edge(
            role_attribution, parent_probandum_id=ult.id, child_id=pen.id, warrant="Forward."
        ),
    )
    _plant_edge(
        tmp_path,
        _make_edge(
            role_attribution, parent_probandum_id=pen.id, child_id=ult.id, warrant="Back-edge."
        ),
    )
    return tmp_path


@pytest.fixture
def tmp_workspace_inv16_three_cycle(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """Planted three-cycle: a → b → c → a."""
    _make_marker(tmp_path, "inv16-three-cycle")
    _plant_walton_snapshot(tmp_path)
    a = _probandum(role_attribution, statement="A.", kind="ultimate")
    b = _probandum(
        role_attribution, statement="B.", kind="penultimate", alternatives_considered=["alt"]
    )
    c = _probandum(
        role_attribution, statement="C.", kind="interim", alternatives_considered=["alt"]
    )
    for p in (a, b, c):
        _plant_probandum(tmp_path, p)
    _plant_edge(
        tmp_path,
        _make_edge(role_attribution, parent_probandum_id=a.id, child_id=b.id, warrant="A→B."),
    )
    _plant_edge(
        tmp_path,
        _make_edge(role_attribution, parent_probandum_id=b.id, child_id=c.id, warrant="B→C."),
    )
    _plant_edge(
        tmp_path,
        _make_edge(role_attribution, parent_probandum_id=c.id, child_id=a.id, warrant="C→A."),
    )
    return tmp_path


@pytest.fixture
def tmp_workspace_inv16_deep_chain(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """A clean 10-deep linear chain p0 → p1 → ... → p9 with no cycles."""
    _make_marker(tmp_path, "inv16-deep-chain")
    _plant_walton_snapshot(tmp_path)
    chain: list[Probandum] = []
    for i in range(10):
        kind = "ultimate" if i == 0 else "penultimate" if i == 1 else "interim"
        p = _probandum(
            role_attribution,
            statement=f"Chain level {i}.",
            kind=kind,
            alternatives_considered=[] if kind == "ultimate" else ["alt"],
        )
        chain.append(p)
        _plant_probandum(tmp_path, p)
    from itertools import pairwise

    for parent, child in pairwise(chain):
        _plant_edge(
            tmp_path,
            _make_edge(
                role_attribution,
                parent_probandum_id=parent.id,
                child_id=child.id,
                warrant=f"Link {parent.id[:6]}→{child.id[:6]}.",
            ),
        )
    return tmp_path


# --- Tests ------------------------------------------------------------


def test_clean_tree_passes(tmp_workspace_inv16_clean: Path) -> None:
    """A workspace with a valid tree of edges passes the INV-16 walk."""
    sub = Substrate(tmp_workspace_inv16_clean)
    _walk_and_check(sub)  # must not raise


def test_self_loop_caught(tmp_workspace_inv16_self_loop: Path) -> None:
    """A planted self-loop edge is rejected by the walker."""
    sub = Substrate(tmp_workspace_inv16_self_loop)
    with pytest.raises(ProbandumTreeViolation, match=r"self-loop|cycle"):
        _walk_and_check(sub)


def test_two_cycle_caught(tmp_workspace_inv16_two_cycle: Path) -> None:
    """A planted two-cycle is rejected by the walker."""
    sub = Substrate(tmp_workspace_inv16_two_cycle)
    with pytest.raises(ProbandumTreeViolation, match=r"cycle|multi-parent|multiple parents"):
        _walk_and_check(sub)


def test_three_cycle_caught(tmp_workspace_inv16_three_cycle: Path) -> None:
    """A planted three-cycle is rejected by the walker."""
    sub = Substrate(tmp_workspace_inv16_three_cycle)
    with pytest.raises(ProbandumTreeViolation, match=r"cycle|multi-parent|multiple parents"):
        _walk_and_check(sub)


def test_deep_chain_passes(tmp_workspace_inv16_deep_chain: Path) -> None:
    """A 10-deep linear chain (no cycles, single parent per child) passes."""
    sub = Substrate(tmp_workspace_inv16_deep_chain)
    _walk_and_check(sub)  # must not raise


def _walk_and_check(sub: Substrate) -> None:
    """Re-run the INV-16 gate on every on-disk probandum-edge.

    For each edge under ``mappings/probandum-edges/``, calls
    ``sub.add_probandum_edge(edge)`` — the substrate enforces INV-16 on
    every write, so tampered records raise ``ProbandumTreeViolation``.
    Valid records hit the idempotent no-op path.

    The cycle / multi-parent checks reference the existing on-disk
    edge set: when a fixture has already planted a cycle, re-attempting
    any one of the participating edges via the substrate gate is
    sufficient to trip the walker (the substrate sees the OTHER edges
    on disk and detects the back-edge / multi-parent condition).
    """
    for edge in sub.list_probandum_edges():
        sub.add_probandum_edge(edge)
