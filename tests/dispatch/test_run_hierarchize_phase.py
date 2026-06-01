# pyright: reportPrivateUsage=false, reportUntypedFunctionDecorator=false
"""``run_hierarchize_phase`` end-to-end (Phase 2c M8 / T8.3).

Mirrors the Phase 2b ``test_connect_smoke`` end-to-end pattern:

- Hand-place a Hierarchize ``output.yaml`` under
  ``dispatch/outputs/hierarchize-<hash>/`` (simulating what the
  harness would emit after the orchestrator enqueued the cluster).
- Call :func:`run_hierarchize_phase` directly.
- Assert that the reconciler committed the interim probandum + edges,
  filtered the counters into the report, and the operator-facing
  summary line is emitted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from amanuensis.dispatch.hierarchize_orchestrator import (
    HierarchizePhaseReport,
    run_hierarchize_phase,
)
from amanuensis.fs import Substrate


def _place_hierarchize_output(
    workspace: Path,
    *,
    inputs_hash: str,
    interim_probanda: list[dict[str, Any]],
    probandum_edges: list[dict[str, Any]],
) -> Path:
    """Plant a Hierarchize ``output.yaml`` mimicking the harness emission."""
    output_dir = workspace / "dispatch" / "outputs" / f"hierarchize-{inputs_hash}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "output.yaml"
    payload = {
        "interim_probanda": interim_probanda,
        "probandum_edges": probandum_edges,
    }
    output_path.write_text(
        yaml.safe_dump(payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    return output_path


def test_run_hierarchize_phase_writes_probanda_and_edges(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """Phase report carries the committed interim id + edge ids."""
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)
    penultimate_id = tmp_workspace_with_probandum_tree["pen1"]
    atom_id = tmp_workspace_with_probandum_tree["atom1"]

    inputs_hash = "rhpsmoke" + "a" * 8
    interim_probanda = [
        {
            "statement": "Smith failed to deliver the April 2024 shipment required by §3.",
            "kind": "interim",
            "scheme": "argument-from-sign",
            "alternatives_considered": [
                "Smith tendered but ACME rejected for unrelated quality reasons.",
                "Smith and ACME mutually deferred the April 2024 delivery.",
            ],
            "confidence": "high",
        }
    ]
    probandum_edges = [
        {
            "parent_probandum_id": penultimate_id,
            "child_id": "0",  # index reference into interim_probanda
            "child_kind": "probandum",
            "child_source_id": None,
            "kind": "supports",
            "warrant": "The §3 obligation maps to the concrete April 2024 delivery.",
            "warrant_defensibility": "methodology-derived",
            "warrant_basis": "Standard contract-law mapping.",
            "confidence": "high",
        },
        {
            "parent_probandum_id": "0",
            "child_id": atom_id,
            "child_kind": "atom",
            "child_source_id": "src-A",
            "kind": "supports",
            "warrant": "The atom directly attests the missed delivery.",
            "warrant_defensibility": "literature-backed",
            "warrant_basis": "Direct attestation in the source.",
            "confidence": "high",
        },
    ]
    _place_hierarchize_output(
        workspace,
        inputs_hash=inputs_hash,
        interim_probanda=interim_probanda,
        probandum_edges=probandum_edges,
    )

    report = run_hierarchize_phase(sub)

    assert isinstance(report, HierarchizePhaseReport)
    # One interim probandum and two edges should have been reported.
    assert len(report.probanda_committed) == 1, (
        f"expected 1 committed probandum; got {report.probanda_committed!r}"
    )
    assert len(report.edges_committed) == 2, (
        f"expected 2 committed edges; got {report.edges_committed!r}"
    )
    assert report.clarifications_raised == []
    assert report.outputs_consumed == 1


def test_run_hierarchize_phase_reports_clarifications(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """An interim with an unknown Walton scheme produces a clarification id in the report."""
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)
    penultimate_id = tmp_workspace_with_probandum_tree["pen1"]

    inputs_hash = "rhpscheme" + "b" * 8
    interim_probanda = [
        {
            "statement": "Some claim that uses an unknown scheme.",
            "kind": "interim",
            "scheme": "argument-from-pure-fabrication",  # not in snapshot
            "alternatives_considered": ["Some realistic alternative."],
            "confidence": "low",
        }
    ]
    probandum_edges = [
        {
            "parent_probandum_id": penultimate_id,
            "child_id": "0",
            "child_kind": "probandum",
            "child_source_id": None,
            "kind": "supports",
            "warrant": "Decomposition warrant.",
            "warrant_defensibility": "conventional",
            "warrant_basis": "Wigmore §III decomposition.",
            "confidence": "low",
        }
    ]
    _place_hierarchize_output(
        workspace,
        inputs_hash=inputs_hash,
        interim_probanda=interim_probanda,
        probandum_edges=probandum_edges,
    )

    report = run_hierarchize_phase(sub)

    # No probandum committed (rejected by INV-18).
    assert report.probanda_committed == []
    # The scheme-missing clarification id is in the report.
    assert report.clarifications_raised, (
        "expected the hierarchize-reconcile path to record an "
        "auto-raised scheme-missing clarification id in the phase report"
    )


def test_run_hierarchize_phase_filters_non_hierarchize_outputs(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """Co-drained non-hierarchize outputs do not leak into the report counters.

    Plants a hierarchize output AND a map-audit output (raising a
    plain clarification). The hierarchize report must not count the
    map-audit-raised clarification.
    """
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)
    penultimate_id = tmp_workspace_with_probandum_tree["pen1"]
    atom_id = tmp_workspace_with_probandum_tree["atom1"]

    # (1) Plant a happy hierarchize output.
    h_hash = "filter" + "h" * 10
    _place_hierarchize_output(
        workspace,
        inputs_hash=h_hash,
        interim_probanda=[
            {
                "statement": "Filter-test interim probandum.",
                "kind": "interim",
                "scheme": "argument-from-sign",
                "alternatives_considered": [
                    "Filter alternative 1.",
                    "Filter alternative 2.",
                ],
                "confidence": "high",
            }
        ],
        probandum_edges=[
            {
                "parent_probandum_id": penultimate_id,
                "child_id": "0",
                "child_kind": "probandum",
                "child_source_id": None,
                "kind": "supports",
                "warrant": "Filter-test warrant.",
                "warrant_defensibility": "methodology-derived",
                "warrant_basis": "Wigmore §III decomposition.",
                "confidence": "high",
            },
            {
                "parent_probandum_id": "0",
                "child_id": atom_id,
                "child_kind": "atom",
                "child_source_id": "src-A",
                "kind": "supports",
                "warrant": "Filter-test atom warrant.",
                "warrant_defensibility": "literature-backed",
                "warrant_basis": "Direct attestation.",
                "confidence": "high",
            },
        ],
    )

    # (2) Plant a map-audit output that raises a clarification.
    audit_hash = "filter" + "a" * 10
    audit_dir = workspace / "dispatch" / "outputs" / f"map-audit-{audit_hash}"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_payload = {
        "accepted_entities": [],
        "accepted_resolutions": [],
        "clarifications": [
            {
                "kind": "resolution-disputed",
                "source_id": "src-A",
                "question": (
                    "Map-audit-raised clarification that must NOT leak into hierarchize report."
                ),
            }
        ],
    }
    (audit_dir / "output.yaml").write_text(
        yaml.safe_dump(audit_payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )

    report = run_hierarchize_phase(sub)

    # The hierarchize-only counters reflect the hierarchize output only.
    assert len(report.probanda_committed) == 1
    assert len(report.edges_committed) == 2
    assert report.clarifications_raised == [], (
        f"hierarchize report's clarifications_raised must not include "
        f"map-audit-raised ids; got {report.clarifications_raised!r}"
    )
    # outputs_consumed counts only the hierarchize-* directory.
    assert report.outputs_consumed == 1


def test_run_hierarchize_phase_zero_clusters_no_op(
    tmp_workspace_with_childless_penultimate: Path,
) -> None:
    """Empty-cluster workspace: enqueue=0, no errors, report is well-formed."""
    sub = Substrate(tmp_workspace_with_childless_penultimate)
    report = run_hierarchize_phase(sub)
    assert report.enqueued == 0
    assert report.probanda_committed == []
    assert report.edges_committed == []
    assert report.clarifications_raised == []
    assert report.outputs_consumed == 0
