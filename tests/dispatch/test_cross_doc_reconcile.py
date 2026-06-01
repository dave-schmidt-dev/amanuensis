"""Reconciliation gate for CrossDocRelation candidates (Phase 2b M4).

The Connector role surfaces candidate cross-doc edges as plain dicts.
``_build_cross_doc_relation`` is the reconciler's choke point: it builds
the typed record, runs the INV-15 shared-entity gate (via
``Substrate.add_cross_doc_relation``), and on INV-15 failure auto-raises
a ``resolution-ambiguous`` clarification under the from-endpoint
distillation rather than propagating the gate exception.

Coverage map:

- T4.1 — happy path (bilateral resolutions present → record committed).
"""

# pyright: reportPrivateUsage=false
from __future__ import annotations

from pathlib import Path
from typing import Any

from amanuensis.dispatch.reconcile import _build_cross_doc_relation
from amanuensis.fs import Substrate
from amanuensis.schemas import ProvenanceRecord, RoleAttribution

from .conftest import (
    FROM_ATOM_ID,
    FROM_SOURCE_ID,
    SHARED_ENTITY_ID,
    TO_ATOM_ID,
    TO_SOURCE_ID,
    list_open_clarifications_for_source,
)


def _base_candidate() -> dict[str, Any]:
    """Return a syntactically-valid Connector candidate dict."""
    return {
        "from_atom_id": FROM_ATOM_ID,
        "from_source_id": FROM_SOURCE_ID,
        "to_atom_id": TO_ATOM_ID,
        "to_source_id": TO_SOURCE_ID,
        "kind": "supports",
        "warrant": "shared smith reference",
        "warrant_defensibility": "conventional",
        "warrant_basis": "Independent attestation of Smith's role",
        "confidence": "medium",
        "shared_entities": [SHARED_ENTITY_ID],
    }


# --- T4.1: happy path --------------------------------------------------


def test_valid_candidate_builds_record(
    tmp_workspace_with_bilateral_resolutions: Path,
    role_attribution: RoleAttribution,
    fake_provenance: ProvenanceRecord,
) -> None:
    """A Connector candidate that satisfies INV-15 commits a CrossDocRelation."""
    sub = Substrate(tmp_workspace_with_bilateral_resolutions)

    rel = _build_cross_doc_relation(
        _base_candidate(),
        sub,
        fake_provenance,
        role_attributions=[role_attribution],
    )
    assert rel is not None
    assert rel.kind == "supports"
    assert rel.provenance_id == fake_provenance.id
    # The substrate now has the record (read-back path).
    written = list(sub.list_cross_doc_relations())
    assert len(written) == 1
    assert written[0].id == rel.id
    # No clarification raised on the happy path.
    assert list_open_clarifications_for_source(sub, FROM_SOURCE_ID) == []
