"""Reconciliation gate for CrossDocRelation candidates (Phase 2b M4).

The Connector role surfaces candidate cross-doc edges as plain dicts.
``_build_cross_doc_relation`` is the reconciler's choke point: it builds
the typed record, runs the INV-15 shared-entity gate (via
``Substrate.add_cross_doc_relation``), and on INV-15 failure auto-raises
a ``resolution-ambiguous`` clarification under the from-endpoint
distillation rather than propagating the gate exception.

Coverage map:

- T4.1 — happy path (bilateral resolutions present → record committed).
- T4.2 — INV-15 failure auto-raises a ``resolution-ambiguous``
  clarification under the from-endpoint distillation.
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


# --- T4.2: INV-15 failure auto-raises a clarification -----------------


def test_inv15_failure_writes_resolution_ambiguous_clarification(
    tmp_workspace_with_partial_resolutions: Path,
    role_attribution: RoleAttribution,
    fake_provenance: ProvenanceRecord,
) -> None:
    """Missing from-endpoint Resolution → reconciler raises ``resolution-ambiguous``.

    Asserts:

    1. ``_build_cross_doc_relation`` returns ``None`` (NOT an exception).
    2. No CrossDocRelation lands in the substrate.
    3. Exactly one open ``resolution-ambiguous`` Clarification is filed
       under the from-endpoint distillation.
    4. The clarification's ``question`` text and / or ``context_refs``
       carries both atom ids and the shared entity id so a human
       navigator can pivot to any of them from the resolved-clarification
       view (M8 / web UI).
    """
    sub = Substrate(tmp_workspace_with_partial_resolutions)

    result = _build_cross_doc_relation(
        _base_candidate(),
        sub,
        fake_provenance,
        role_attributions=[role_attribution],
    )
    assert result is None
    # No CrossDocRelation was written.
    assert list(sub.list_cross_doc_relations()) == []
    # A Clarification of kind resolution-ambiguous was written under from-source.
    open_clarifications = list_open_clarifications_for_source(
        sub, FROM_SOURCE_ID, kind="resolution-ambiguous"
    )
    assert len(open_clarifications) == 1
    c = open_clarifications[0]
    assert c.kind == "resolution-ambiguous"
    # Both atom ids and the shared entity id are referenced (in question
    # text or in context_refs) so a human resolving the clarification
    # can navigate.
    haystack_text = c.question + " " + " ".join(c.context_refs)
    assert FROM_ATOM_ID in haystack_text
    assert TO_ATOM_ID in haystack_text
    assert SHARED_ENTITY_ID in haystack_text
