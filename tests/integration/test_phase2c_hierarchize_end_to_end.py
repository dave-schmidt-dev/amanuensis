"""Phase 2c M13 end-to-end integration test for the full Hierarchize pipeline (T13.1).

Drives the complete Phase 2a + 2b + 2c pipeline against the 3-distillation
synthetic corpus and asserts that the Hierarchize role produces a fully-
shaped Wigmore tree (ultimate + ≥2 penultimate + ≥3 interim) with edges
of all three kinds (``supports`` / ``attacks`` / ``undercuts``):

1. Plant the workspace via the Phase 2a ``build_map_end_to_end_workspace``
   fixture builder (3 distillations, 9 atoms total).
2. Run the Phase 2a resolver+auditor pair via hand-placed
   ``dispatch/outputs/map-resolve-<hash>/output.yaml`` +
   ``map-audit-<hash>/output.yaml``. 5 canonical entities + 9 bilateral
   resolutions land. (Re-uses the Phase 2b integration test's payloads.)
3. Run the Phase 2b Connect phase by pre-placing a Connector
   ``output.yaml`` carrying 3 hand-authored candidates — one of each
   kind — anchored on the canonical ACME Corp entity. 3 cross-doc
   relations land.
4. Supervisor (the test) authors the macroscopic probanda directly
   against the substrate (simulating the CLI ``map probandum add``
   + ``map probandum link`` flow): 1 ultimate + 2 penultimate
   probanda, with edges linking ultimate -> penultimate.
5. Run :func:`run_hierarchize_phase` with a pre-placed Hierarchize
   harness output carrying 3 interim probanda + 5 probandum-edges
   (one penultimate -> interim per penultimate, one interim -> atom
   and one interim -> cross-doc-relation, edges of all 3 kinds).

Assertions
----------
- ≥1 ultimate exists.
- ≥2 penultimate probanda exist.
- ≥3 interim probanda exist.
- Every non-ultimate probandum walks upward to the ultimate via
  ``Substrate._walk_to_ultimate``.
- Probandum-edges of all 3 kinds (supports / attacks / undercuts)
  collectively exist.
- The tree structure is well-formed: no cycles, no multi-parent
  (verified by the substrate's INV-16 gate having accepted every
  edge written by the reconciler).

Byte-identical idempotency
--------------------------
A second test re-runs the pipeline against the same substrate state
and asserts that ``mappings/probanda/`` + ``mappings/probandum-edges/``
+ ``mappings/supersedes/`` byte images are unchanged (INV-4 + INV-8 +
INV-13).
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from amanuensis.dispatch.connect_orchestrator import run_connect_phase
from amanuensis.dispatch.hierarchize_orchestrator import run_hierarchize_phase
from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import Substrate
from amanuensis.schemas import (
    AgentAttribution,
    Probandum,
    ProbandumEdge,
    ProvenanceRecord,
    RoleAttribution,
    compute_id,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FIXTURE_BUILDER_PATH: Path = (
    Path(__file__).parent.parent / "fixtures" / "map-end-to-end" / "_fixture_builder.py"
)


def _load_fixture_builder() -> ModuleType:
    """Load the fixture builder module via importlib (hyphen in dir name)."""
    spec = importlib.util.spec_from_file_location("_fixture_builder", _FIXTURE_BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _write_output(workspace: Path, *, role: str, inputs_hash: str, payload: dict[str, Any]) -> Path:
    """Drop a synthesized ``<role>-<hash>/output.yaml`` under dispatch/outputs/."""
    out_dir = workspace / "dispatch" / "outputs" / f"{role}-{inputs_hash}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "output.yaml"
    out_path.write_text(
        yaml.safe_dump(payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    return out_path


def _hash_mappings_dir(workspace: Path, subpath: str) -> dict[str, bytes]:
    """Return {filename: bytes} for every file under ``mappings/<subpath>/``.

    Skips writer-leftover ``.tmp.*`` files. Used to assert byte-identical
    idempotency on the Hierarchize re-run path (INV-4 + INV-8 + INV-13).
    """
    root = workspace / "mappings" / subpath
    if not root.is_dir():
        return {}
    out: dict[str, bytes] = {}
    for path in sorted(root.iterdir()):
        if not path.is_file() or ".tmp." in path.name:
            continue
        out[path.name] = path.read_bytes()
    return out


# ---------------------------------------------------------------------------
# Phase 2a resolver + auditor + Phase 2b connector payloads (copied
# verbatim from ``test_phase2b_connect_end_to_end.py``; this test is a
# strict superset of the Phase 2b contract).
# ---------------------------------------------------------------------------

# Stable atom ids produced by the fixture builder (deterministic because
# compute_id is pure and all builder inputs are fixed).
_CD1_ATOM_ACME = "a-ed6c0eb084918d05"
_CD1_ATOM_BETACO = "a-ebc28e91f7e5b843"
_CD1_ATOM_DRAFT1 = "a-688b086a934eb635"

_CD2_ATOM_ACME_CORP = "a-4e6b201e1cae5e95"
_CD2_ATOM_BETACO_LTD = "a-54e5ec5f12fe5809"
_CD2_ATOM_DRAFT2 = "a-aff4b81a17af60d0"

_SI_ATOM_ACME = "a-2245cf8ea1f02e8a"
_SI_ATOM_BETACO = "a-149f73c02c98417b"
_SI_ATOM_COUNSEL = "a-d43e92c75baadd2e"

_HASH_RESOLVE_ALL = "a" * 64
_HASH_AUDIT_1 = "d" * 64
_HASH_CONNECT_ALL_KINDS = "c" * 64
_HASH_HIERARCHIZE_ALL_KINDS = "e" * 64

_SRC_CD1 = "contract-draft-1"
_SRC_CD2 = "contract-draft-2"
_SRC_SI = "settlement-instrument"


def _make_resolver_payload() -> dict[str, Any]:
    """Resolver output covering all 5 entities and all 9 resolutions."""
    return {
        "proposed_entities": [
            {
                "kind": "organization",
                "canonical_name": "ACME Corp",
                "aliases": ["ACME Corporation"],
                "notes": "party A",
            },
            {
                "kind": "organization",
                "canonical_name": "BetaCo Ltd",
                "aliases": ["BetaCo Ltd.", "BetaCo"],
                "notes": "party B",
            },
            {
                "kind": "document",
                "canonical_name": "Contract Draft 1",
                "aliases": [],
                "notes": "first draft",
            },
            {
                "kind": "document",
                "canonical_name": "Contract Draft 2",
                "aliases": [],
                "notes": "second draft",
            },
            {
                "kind": "person",
                "canonical_name": "Counsel for ACME",
                "aliases": [],
                "notes": "legal counsel",
            },
        ],
        "proposed_resolutions": [
            {
                "entity_index": 0,
                "source_id": _SRC_CD1,
                "atom_id": _CD1_ATOM_ACME,
                "operand_index": 0,
                "confidence": "high",
                "basis": "exact name match",
            },
            {
                "entity_index": 1,
                "source_id": _SRC_CD1,
                "atom_id": _CD1_ATOM_BETACO,
                "operand_index": 0,
                "confidence": "high",
                "basis": "exact name match",
            },
            {
                "entity_index": 2,
                "source_id": _SRC_CD1,
                "atom_id": _CD1_ATOM_DRAFT1,
                "operand_index": 0,
                "confidence": "high",
                "basis": "exact name match",
            },
            {
                "entity_index": 0,
                "source_id": _SRC_CD2,
                "atom_id": _CD2_ATOM_ACME_CORP,
                "operand_index": 0,
                "confidence": "high",
                "basis": "alias match ACME Corporation",
            },
            {
                "entity_index": 1,
                "source_id": _SRC_CD2,
                "atom_id": _CD2_ATOM_BETACO_LTD,
                "operand_index": 0,
                "confidence": "high",
                "basis": "alias match BetaCo Ltd.",
            },
            {
                "entity_index": 3,
                "source_id": _SRC_CD2,
                "atom_id": _CD2_ATOM_DRAFT2,
                "operand_index": 0,
                "confidence": "high",
                "basis": "exact name match",
            },
            {
                "entity_index": 0,
                "source_id": _SRC_SI,
                "atom_id": _SI_ATOM_ACME,
                "operand_index": 0,
                "confidence": "high",
                "basis": "exact name match",
            },
            {
                "entity_index": 1,
                "source_id": _SRC_SI,
                "atom_id": _SI_ATOM_BETACO,
                "operand_index": 0,
                "confidence": "high",
                "basis": "alias match BetaCo",
            },
            {
                "entity_index": 4,
                "source_id": _SRC_SI,
                "atom_id": _SI_ATOM_COUNSEL,
                "operand_index": 0,
                "confidence": "high",
                "basis": "exact name match",
            },
        ],
    }


def _make_connect_payload(*, acme_entity_id: str) -> dict[str, Any]:
    """Connector output proposing 3 cross-doc edges (one of each kind).

    All anchored on the canonical ACME Corp entity, exactly mirroring
    the Phase 2b integration test's connector payload.
    """
    return {
        "proposed_relations": [
            {
                "from_atom_id": _CD1_ATOM_ACME,
                "from_source_id": _SRC_CD1,
                "to_atom_id": _CD2_ATOM_ACME_CORP,
                "to_source_id": _SRC_CD2,
                "kind": "supports",
                "warrant": (
                    "Both atoms attest ACME Corp's contractual obligation "
                    "across successive contract drafts."
                ),
                "warrant_defensibility": "conventional",
                "warrant_basis": "Two independent attestations of ACME Corp.",
                "confidence": "high",
                "shared_entities": [acme_entity_id],
            },
            {
                "from_atom_id": _CD2_ATOM_ACME_CORP,
                "from_source_id": _SRC_CD2,
                "to_atom_id": _SI_ATOM_ACME,
                "to_source_id": _SRC_SI,
                "kind": "attacks",
                "warrant": (
                    "The settlement instrument's ACME Corp payment terms "
                    "conflict with the second draft's deliverable schedule."
                ),
                "warrant_defensibility": "conventional",
                "warrant_basis": (
                    "Contract Draft 2 obligates filings; the settlement "
                    "instrument obligates a payment instead."
                ),
                "confidence": "medium",
                "shared_entities": [acme_entity_id],
            },
            {
                "from_atom_id": _CD1_ATOM_ACME,
                "from_source_id": _SRC_CD1,
                "to_atom_id": _SI_ATOM_ACME,
                "to_source_id": _SRC_SI,
                "kind": "undercuts",
                "warrant": (
                    "The settlement instrument's payment obligation "
                    "undercuts the original draft's delivery obligation "
                    "as a precondition for ACME Corp's performance."
                ),
                "warrant_defensibility": "methodology-derived",
                "warrant_basis": "Same canonical obligor, replacement obligation.",
                "confidence": "medium",
                "shared_entities": [acme_entity_id],
            },
        ]
    }


# ---------------------------------------------------------------------------
# Supervisor-authored probanda + edges (simulates the CLI flow)
# ---------------------------------------------------------------------------


def _supervisor_agent() -> AgentAttribution:
    """Synthetic supervisor agent for the planted ultimate + penultimate writes."""
    return AgentAttribution(kind="human", identifier="supervisor-e2e", role="human_supervisor")


def _supervisor_role_attr() -> RoleAttribution:
    """Pinned role-attribution timestamp so planted ids stay deterministic."""
    return RoleAttribution(
        agent=_supervisor_agent(),
        activity="proposed",
        at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
    )


def _plant_supervisor_provenance(substrate: Substrate) -> ProvenanceRecord:
    """Mint a mappings-scope PROV record for the supervisor-authored writes.

    The probanda + edges below all share this provenance id. The
    substrate write path requires the PROV to exist on disk before the
    probandum/edge writes.
    """
    agent = _supervisor_agent()
    when = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="probandum",
        entity_id="p-placeholder",
        activity="supervisor-author-probanda",
        activity_started_at=when,
        activity_ended_at=when,
        used_entity_ids=[],
        was_attributed_to=agent,
        was_influenced_by=[],
        schema_version=1,
    )
    prov_id = compute_id(draft)
    prov = draft.model_copy(update={"id": prov_id})
    prov_path = substrate.mappings_provenance_path(prov.id)
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    from amanuensis.fs._atomic import atomic_write_text
    from amanuensis.fs._serialize import serialize_yaml

    atomic_write_text(prov_path, serialize_yaml(prov))
    return prov


def _plant_macroscopic_probanda(
    substrate: Substrate, prov: ProvenanceRecord
) -> tuple[Probandum, Probandum, Probandum]:
    """Plant the macroscopic skeleton: 1 ultimate + 2 penultimate.

    Returns (ultimate, pen1, pen2). The penultimate probanda each attach
    to atoms / cross-doc-relations via subsequent edges; the Hierarchize
    role then fans out interim probanda underneath.
    """
    role_attr = _supervisor_role_attr()

    ultimate_draft = Probandum(
        id="p-placeholder",
        statement=(
            "ACME Corp's contractual obligations under the three-document "
            "corpus were systematically supplanted by the settlement "
            "instrument."
        ),
        kind="ultimate",
        scheme="argument-from-expert-opinion",
        alternatives_considered=[],
        confidence="high",
        provenance_id=prov.id,
        role_attributions=[role_attr],
        schema_version=1,
    )
    ultimate = ultimate_draft.model_copy(update={"id": compute_id(ultimate_draft)})
    substrate.add_probandum(ultimate)

    pen1_draft = Probandum(
        id="p-placeholder",
        statement=(
            "The Contract Draft 1 -> Contract Draft 2 amendment chain "
            "preserved ACME Corp's underlying delivery obligation."
        ),
        kind="penultimate",
        scheme="argument-from-sign",
        alternatives_considered=[
            "Draft 2 silently waived Draft 1's delivery obligation.",
            "The delivery obligation was novated rather than preserved.",
        ],
        confidence="high",
        provenance_id=prov.id,
        role_attributions=[role_attr],
        schema_version=1,
    )
    pen1 = pen1_draft.model_copy(update={"id": compute_id(pen1_draft)})
    substrate.add_probandum(pen1)

    pen2_draft = Probandum(
        id="p-placeholder",
        statement=(
            "The settlement instrument replaced the obligation rather than "
            "merely deferring performance."
        ),
        kind="penultimate",
        scheme="argument-from-sign",
        alternatives_considered=[
            "The settlement instrument is a temporary stipulation.",
            "The settlement instrument is a non-binding side letter.",
        ],
        confidence="medium",
        provenance_id=prov.id,
        role_attributions=[role_attr],
        schema_version=1,
    )
    pen2 = pen2_draft.model_copy(update={"id": compute_id(pen2_draft)})
    substrate.add_probandum(pen2)

    return ultimate, pen1, pen2


def _plant_ultimate_to_penultimate_edges(
    substrate: Substrate,
    *,
    ultimate: Probandum,
    pen1: Probandum,
    pen2: Probandum,
    prov: ProvenanceRecord,
) -> tuple[ProbandumEdge, ProbandumEdge]:
    """Plant the two ``ultimate -> penultimate`` decomposition edges."""
    role_attr = _supervisor_role_attr()

    def _edge(parent: Probandum, child: Probandum, basis: str) -> ProbandumEdge:
        draft = ProbandumEdge(
            id="q-placeholder",
            parent_probandum_id=parent.id,
            child_id=child.id,
            child_kind="probandum",
            child_source_id=None,
            kind="supports",
            warrant=f"Decomposition: {basis}",
            warrant_defensibility="methodology-derived",
            warrant_basis="Wigmore §III decomposition.",
            confidence="high",
            provenance_id=prov.id,
            role_attributions=[role_attr],
            schema_version=1,
        )
        return draft.model_copy(update={"id": compute_id(draft)})

    e1 = _edge(ultimate, pen1, "amendment-chain preserves obligation")
    e2 = _edge(ultimate, pen2, "settlement replaces obligation")
    substrate.add_probandum_edge(e1)
    substrate.add_probandum_edge(e2)
    return e1, e2


def _plant_penultimate_to_evidence_edges(
    substrate: Substrate,
    *,
    pen1: Probandum,
    pen2: Probandum,
    cross_doc_supports_id: str,
    prov: ProvenanceRecord,
) -> None:
    """Plant the seed evidence edges below each penultimate.

    Each penultimate is linked to at least one existing child so the
    Hierarchize orchestrator's cluster-enumeration discovers them.
    ``pen1`` -> the cross-doc-relation of kind 'supports'.
    ``pen2`` -> a contract-draft-1 atom (the §3 obligation).
    """
    role_attr = _supervisor_role_attr()

    def _edge(
        parent: Probandum,
        child_id: str,
        child_kind: str,
        child_source_id: str | None,
        suffix: str,
    ) -> ProbandumEdge:
        draft = ProbandumEdge(
            id="q-placeholder",
            parent_probandum_id=parent.id,
            child_id=child_id,
            child_kind=child_kind,  # pyright: ignore[reportArgumentType]
            child_source_id=child_source_id,
            kind="supports",
            warrant=f"Seed evidence: {suffix}",
            warrant_defensibility="conventional",
            warrant_basis="Direct attestation in the source corpus.",
            confidence="high",
            provenance_id=prov.id,
            role_attributions=[role_attr],
            schema_version=1,
        )
        return draft.model_copy(update={"id": compute_id(draft)})

    pen1_edge = _edge(pen1, cross_doc_supports_id, "cross-doc-relation", None, "cd1->cd2 supports")
    pen2_edge = _edge(pen2, _SI_ATOM_ACME, "atom", _SRC_SI, "settlement attests replacement")
    substrate.add_probandum_edge(pen1_edge)
    substrate.add_probandum_edge(pen2_edge)


def _make_hierarchize_payload(
    *,
    pen1_id: str,
    pen2_id: str,
    cd1_supports_relation_id: str,
) -> dict[str, Any]:
    """Build a Hierarchize-role output proposing 3 interim probanda + 5 edges.

    Tree shape produced (with index references resolved by the reconciler):

    - interim[0]: "Draft 2 incorporates Draft 1's delivery obligation."
                  parent: pen1, kind: supports
    - interim[1]: "BetaCo Ltd. acknowledged the same delivery obligation."
                  parent: interim[0], kind: supports
    - interim[2]: "The settlement payment supersedes rather than supplements
                  the delivery obligation."
                  parent: pen2, kind: supports

    Edges of all 3 kinds emitted between the 5 edges (one supports between
    pen1->interim[0], one attacks between interim[0]->the supporting
    cross-doc-relation, one undercuts between interim[1]->an atom, one
    supports between interim[1]->interim's incoming edge, one supports
    between pen2->interim[2]).
    """
    return {
        "interim_probanda": [
            {
                "statement": (
                    "Contract Draft 2 incorporates Contract Draft 1's delivery "
                    "obligation by reference."
                ),
                "kind": "interim",
                "scheme": "argument-from-sign",
                "alternatives_considered": [
                    "Draft 2 fully supersedes Draft 1 and silently drops the obligation.",
                    "Draft 2 redefines the obligation as discretionary.",
                ],
                "confidence": "high",
            },
            {
                "statement": (
                    "BetaCo Ltd. acknowledged the same underlying delivery "
                    "obligation across both drafts."
                ),
                "kind": "interim",
                "scheme": "argument-from-witness-testimony",
                "alternatives_considered": [
                    "BetaCo Ltd. acknowledged only the second draft's obligation.",
                    "BetaCo Ltd.'s acknowledgement was conditional on signing.",
                ],
                "confidence": "medium",
            },
            {
                "statement": (
                    "The settlement instrument's payment provision supersedes "
                    "rather than supplements the original delivery obligation."
                ),
                "kind": "interim",
                "scheme": "argument-from-sign",
                "alternatives_considered": [
                    "The payment provision is consideration in addition to delivery.",
                    "The payment provision is a liquidated-damages estimate.",
                ],
                "confidence": "high",
            },
        ],
        "probandum_edges": [
            # pen1 -> interim[0]  (kind=supports)
            {
                "parent_probandum_id": pen1_id,
                "child_id": "0",  # interim[0] index reference
                "child_kind": "probandum",
                "child_source_id": None,
                "kind": "supports",
                "warrant": (
                    "The §3 cross-reference language in Draft 2 textually maps "
                    "to Draft 1's delivery clause."
                ),
                "warrant_defensibility": "methodology-derived",
                "warrant_basis": "Wigmore §III decomposition.",
                "confidence": "high",
            },
            # interim[0] -> interim[1]  (kind=supports)
            {
                "parent_probandum_id": "0",
                "child_id": "1",
                "child_kind": "probandum",
                "child_source_id": None,
                "kind": "supports",
                "warrant": (
                    "BetaCo Ltd.'s repeated acknowledgement provides "
                    "evidentiary weight for the incorporation claim."
                ),
                "warrant_defensibility": "literature-backed",
                "warrant_basis": "Standard witness-testimony chain.",
                "confidence": "medium",
            },
            # interim[1] -> the cross-doc-relation (kind=attacks)
            {
                "parent_probandum_id": "1",
                "child_id": cd1_supports_relation_id,
                "child_kind": "cross-doc-relation",
                "child_source_id": None,
                "kind": "attacks",
                "warrant": (
                    "BetaCo Ltd.'s acknowledgement timing pre-dates the "
                    "Draft 1 -> Draft 2 supports edge's posited mechanism."
                ),
                "warrant_defensibility": "methodology-derived",
                "warrant_basis": "Temporal-order attack on the warrant.",
                "confidence": "medium",
            },
            # interim[0] -> a contract-draft-2 atom (kind=undercuts)
            {
                "parent_probandum_id": "0",
                "child_id": _CD2_ATOM_DRAFT2,
                "child_kind": "atom",
                "child_source_id": _SRC_CD2,
                "kind": "undercuts",
                "warrant": (
                    "The Draft 2 governance clause undercuts the cross-reference's "
                    "presumed continuity."
                ),
                "warrant_defensibility": "conventional",
                "warrant_basis": "Plain-text reading of Draft 2 §1.",
                "confidence": "medium",
            },
            # pen2 -> interim[2]  (kind=supports)
            {
                "parent_probandum_id": pen2_id,
                "child_id": "2",
                "child_kind": "probandum",
                "child_source_id": None,
                "kind": "supports",
                "warrant": (
                    "The settlement instrument's release language is "
                    "characteristic of supersession rather than supplement."
                ),
                "warrant_defensibility": "literature-backed",
                "warrant_basis": "Restatement (Second) of Contracts §279.",
                "confidence": "high",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Pipeline driver
# ---------------------------------------------------------------------------


def _drive_full_pipeline(workspace: Path) -> dict[str, str]:
    """Run plant → resolve → audit → connect → supervisor → hierarchize.

    Returns a dict of ``{role: id}`` for the planted ultimate + penultimates
    and the supporting cross-doc-relation id, so the second (idempotency)
    test can re-target the same hierarchize candidates.
    """
    builder = _load_fixture_builder()
    builder.build_map_end_to_end_workspace(workspace)
    substrate = Substrate(workspace)

    # --- Phase 2a resolve + audit -------------------------------------
    _write_output(
        workspace,
        role="map-resolve",
        inputs_hash=_HASH_RESOLVE_ALL,
        payload=_make_resolver_payload(),
    )
    resolve_result = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert resolve_result.errors == [], f"resolver errors: {resolve_result.errors!r}"

    entities = list(substrate.list_entities())
    resolutions = list(substrate.list_resolutions())
    audit_payload: dict[str, Any] = {
        "accepted_entities": [e.id for e in entities],
        "accepted_resolutions": [r.id for r in resolutions],
        "rejected_entities": [],
        "rejected_resolutions": [],
        "clarifications": [],
        "inputs_hash": _HASH_AUDIT_1,
    }
    _write_output(workspace, role="map-audit", inputs_hash=_HASH_AUDIT_1, payload=audit_payload)
    audit_result = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert audit_result.errors == [], f"audit errors: {audit_result.errors!r}"

    # --- Phase 2b connect ---------------------------------------------
    acme = next(e for e in entities if e.canonical_name == "ACME Corp")
    _write_output(
        workspace,
        role="connect",
        inputs_hash=_HASH_CONNECT_ALL_KINDS,
        payload=_make_connect_payload(acme_entity_id=acme.id),
    )
    connect_report = run_connect_phase(substrate)
    assert connect_report.errors == [], f"connect errors: {connect_report.errors!r}"
    assert len(connect_report.relations_committed) == 3, (
        f"expected 3 relations committed; got {connect_report.relations_committed!r}"
    )

    # Locate the canonical "supports" cross-doc relation (cd1 -> cd2 on ACME).
    relations = sorted(substrate.list_cross_doc_relations(), key=lambda r: r.id)
    cd1_supports = next(
        r
        for r in relations
        if r.kind == "supports" and r.from_source_id == _SRC_CD1 and r.to_source_id == _SRC_CD2
    )

    # --- Pin the Walton-scheme snapshot --------------------------------
    # Required by INV-18 before any probandum write can land.
    substrate.snapshot_walton_schemes()

    # --- Supervisor: plant macroscopic probanda + ultimate->pen edges ---
    prov = _plant_supervisor_provenance(substrate)
    ultimate, pen1, pen2 = _plant_macroscopic_probanda(substrate, prov)
    _plant_ultimate_to_penultimate_edges(
        substrate, ultimate=ultimate, pen1=pen1, pen2=pen2, prov=prov
    )
    _plant_penultimate_to_evidence_edges(
        substrate,
        pen1=pen1,
        pen2=pen2,
        cross_doc_supports_id=cd1_supports.id,
        prov=prov,
    )

    # --- Phase 2c hierarchize ------------------------------------------
    _write_output(
        workspace,
        role="hierarchize",
        inputs_hash=_HASH_HIERARCHIZE_ALL_KINDS,
        payload=_make_hierarchize_payload(
            pen1_id=pen1.id,
            pen2_id=pen2.id,
            cd1_supports_relation_id=cd1_supports.id,
        ),
    )
    h_report = run_hierarchize_phase(substrate)
    # The phase report's "errors" surface as part of the reconcile pass;
    # the inner reconcile_outputs surfaces them. We assert the substrate
    # state below directly rather than re-deriving from the report.
    # The hierarchize report should have 3 probanda and 5 edges committed.
    assert len(h_report.probanda_committed) == 3, (
        f"expected 3 hierarchize-committed probanda; got "
        f"{h_report.probanda_committed!r} (clar_raised={h_report.clarifications_raised!r})"
    )
    assert len(h_report.edges_committed) == 5, (
        f"expected 5 hierarchize-committed edges; got {h_report.edges_committed!r}"
    )

    return {
        "ultimate": ultimate.id,
        "pen1": pen1.id,
        "pen2": pen2.id,
        "cd1_supports_relation": cd1_supports.id,
    }


# ---------------------------------------------------------------------------
# The integration test
# ---------------------------------------------------------------------------


def test_phase2c_end_to_end_produces_full_tree(tmp_path: Path) -> None:
    """Full pipeline produces a Wigmore tree with all 3 edge kinds.

    Asserts ≥1 ultimate, ≥2 penultimate, ≥3 interim probanda; every
    non-ultimate probandum has lineage to ultimate; edges of all 3 kinds
    (supports / attacks / undercuts) exist; substrate gates accepted
    every edge (so the tree shape is well-formed by construction).
    """
    planted = _drive_full_pipeline(tmp_path)
    substrate = Substrate(tmp_path)

    # --- Probandum-kind population assertions --------------------------
    probanda = list(substrate.list_probanda())
    ultimates = [p for p in probanda if p.kind == "ultimate"]
    penultimates = [p for p in probanda if p.kind == "penultimate"]
    interims = [p for p in probanda if p.kind == "interim"]

    assert len(ultimates) >= 1, f"expected ≥1 ultimate; got {len(ultimates)}"
    assert len(penultimates) >= 2, f"expected ≥2 penultimate; got {len(penultimates)}"
    assert len(interims) >= 3, f"expected ≥3 interim; got {len(interims)}"

    # --- Lineage assertion: every non-ultimate probandum walks up to an ultimate ---
    for prob in probanda:
        if prob.kind == "ultimate":
            continue
        assert substrate._walk_to_ultimate(prob.id), (  # pyright: ignore[reportPrivateUsage]
            f"probandum {prob.id} (kind={prob.kind}) does not trace upward "
            "to an ultimate (INV-17 lineage incomplete on disk)"
        )

    # --- Edge-kind diversity assertion ---------------------------------
    edges = list(substrate.list_probandum_edges())
    edge_kinds = {e.kind for e in edges}
    assert "supports" in edge_kinds, f"missing 'supports' edges; got {sorted(edge_kinds)!r}"
    assert "attacks" in edge_kinds, f"missing 'attacks' edges; got {sorted(edge_kinds)!r}"
    assert "undercuts" in edge_kinds, f"missing 'undercuts' edges; got {sorted(edge_kinds)!r}"

    # --- Tree shape: no cycle / no multi-parent on probandum subgraph --
    # The substrate's INV-16 gate rejected any edge that would have
    # closed a cycle or introduced multi-parent at write time; the fact
    # that every edge in the planted payload landed on disk is itself
    # the assertion. We additionally sanity-check the absence of
    # multi-parent by counting incoming probandum-edges per probandum.
    incoming_count: dict[str, int] = {}
    for edge in edges:
        if edge.child_kind != "probandum":
            continue
        incoming_count[edge.child_id] = incoming_count.get(edge.child_id, 0) + 1
    multi_parent = {pid: n for pid, n in incoming_count.items() if n > 1}
    assert not multi_parent, f"multi-parent probanda detected (INV-16 violation): {multi_parent!r}"

    # The ultimate has no incoming probandum-edges.
    assert planted["ultimate"] not in incoming_count, (
        "ultimate probandum has incoming probandum-edges; tree must root there"
    )


def test_phase2c_byte_identical_on_rerun(tmp_path: Path) -> None:
    """Re-running the hierarchize phase against the same substrate is byte-identical.

    INV-4 + INV-8 + INV-13: a second invocation of
    :func:`run_hierarchize_phase` against the substrate that already
    holds the committed tree must not mutate any committed probandum,
    edge, or supersede file. (No new outputs are placed; the second
    invocation observes the cache-hit short-circuit at the queue layer
    and the no-pending-outputs short-circuit at the reconcile layer.)
    """
    _drive_full_pipeline(tmp_path)
    substrate = Substrate(tmp_path)

    snapshot_probanda_first = _hash_mappings_dir(tmp_path, "probanda")
    snapshot_edges_first = _hash_mappings_dir(tmp_path, "probandum-edges")
    snapshot_supersedes_first = _hash_mappings_dir(tmp_path, "supersedes")
    assert snapshot_probanda_first, "expected at least one probandum on disk"
    assert snapshot_edges_first, "expected at least one probandum-edge on disk"

    # Re-run: no new harness outputs are pending; the reconciler sees an
    # empty drain and commits nothing.
    second_report = run_hierarchize_phase(substrate)
    assert second_report.probanda_committed == [], (
        f"expected zero new commits on re-run; got {second_report.probanda_committed!r}"
    )
    assert second_report.edges_committed == [], (
        f"expected zero new edge commits on re-run; got {second_report.edges_committed!r}"
    )
    assert second_report.clarifications_raised == [], (
        f"expected zero new clarifications on re-run; got {second_report.clarifications_raised!r}"
    )

    snapshot_probanda_second = _hash_mappings_dir(tmp_path, "probanda")
    snapshot_edges_second = _hash_mappings_dir(tmp_path, "probandum-edges")
    snapshot_supersedes_second = _hash_mappings_dir(tmp_path, "supersedes")

    assert snapshot_probanda_first == snapshot_probanda_second, (
        "byte-identical idempotency violation: mappings/probanda/ changed on re-run"
    )
    assert snapshot_edges_first == snapshot_edges_second, (
        "byte-identical idempotency violation: mappings/probandum-edges/ changed on re-run"
    )
    assert snapshot_supersedes_first == snapshot_supersedes_second, (
        "byte-identical idempotency violation: mappings/supersedes/ changed on re-run"
    )
