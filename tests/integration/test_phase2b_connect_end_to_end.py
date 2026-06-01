"""Phase 2b M11 end-to-end integration test for the full Connect pipeline (T11.1).

Drives the complete Phase 2a + Phase 2b pipeline against a 3-distillation
synthetic corpus and asserts that the Connector role produces cross-doc
edges of all three kinds (``supports`` / ``attacks`` / ``undercuts``):

1. Plant the workspace via the Phase 2a ``build_map_end_to_end_workspace``
   fixture builder (3 distillations, 9 atoms total). Phase 2a's M11
   integration test exercises the same fixture for the resolve+audit half.
2. Run the Phase 2a resolver+auditor pair via hand-placed
   ``dispatch/outputs/map-resolve-<hash>/output.yaml`` +
   ``map-audit-<hash>/output.yaml``. After this step the substrate holds
   5 canonical entities (ACME Corp, BetaCo Ltd, Contract Draft 1,
   Contract Draft 2, Counsel for ACME) with 9 bilateral resolutions
   across the 3 distillations; ACME Corp and BetaCo Ltd each have
   resolutions spanning ALL 3 sources, satisfying INV-15 for any pair.
3. Run the Phase 2b Connect phase by pre-placing a Connector
   ``output.yaml`` carrying 3 hand-authored candidates — one of each
   kind, all referencing the canonical ACME Corp entity — then invoke
   :func:`run_connect_phase`. The reconciler routes each candidate
   through :func:`_build_cross_doc_relation`, the INV-15 gate passes
   (bilateral resolutions exist), and three ``CrossDocRelation``
   records land under ``mappings/relations/``.
4. Assert ≥1 cross-doc edge AND at least one of each kind.
5. (Byte-identical idempotency) Snapshot ``mappings/relations/``, re-run
   :func:`run_connect_phase` against the now-clean substrate, and confirm
   the byte image is unchanged (INV-4 + INV-8).

The dispatch driver itself is the only short-cut: role outputs are written
synthetically rather than invoking a real LLM. Every other contract
(cluster enumeration, queue write, output discovery, reconcile, substrate
commit, replay-log append, INV-15 gate, INV-13 immutability) is exercised
against production code.

Mirrors the style and scope of ``test_phase2a_map_end_to_end.py``
(``test_map_pipeline_end_to_end``) extended with the Phase 2b Connect
phase tail.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from amanuensis.dispatch.connect_orchestrator import run_connect_phase
from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import Substrate

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


def _hash_relations(workspace: Path) -> dict[str, bytes]:
    """Return {relative-path: bytes} for every file under ``mappings/relations/``.

    Used to assert byte-identical idempotency on the Connect re-run path
    (INV-4 + INV-8). Skips writer-leftover ``.tmp.*`` files.
    """
    rels_root = workspace / "mappings" / "relations"
    if not rels_root.is_dir():
        return {}
    out: dict[str, bytes] = {}
    for path in sorted(rels_root.iterdir()):
        if not path.is_file() or ".tmp." in path.name:
            continue
        out[path.name] = path.read_bytes()
    return out


# ---------------------------------------------------------------------------
# Resolver + auditor payloads (lifted from test_phase2a_map_end_to_end.py).
#
# The Phase 2a integration test resolves 9 atoms (3 per distillation) into
# 5 canonical entities. Of those, ACME Corp and BetaCo Ltd each span all
# 3 distillations, satisfying INV-15's bilateral-resolution gate for any
# pair of atoms drawn from different sources that resolve to the same
# canonical entity.
#
# We re-use the resolver/auditor shape verbatim so the Phase 2b test
# remains a strict superset of the Phase 2a contract.
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
    """Connector output proposing 3 cross-doc edges — one of each kind.

    All three edges reference the canonical "ACME Corp" entity, which has
    resolutions in all 3 distillations (cd1, cd2, si). The three pairs:

    - ``cd1 → cd2`` (kind=``supports``): both atoms attest ACME Corp's
      contractual obligations under successive drafts.
    - ``cd2 → si`` (kind=``attacks``): the settlement instrument's
      ACME Corp obligations conflict with the second draft's terms.
    - ``cd1 → si`` (kind=``undercuts``): the settlement instrument
      undercuts the warrant of the first-draft obligation.

    The narrative-content claims here are SYNTHETIC and only exist to
    populate the warrant fields; the structural test is whether all three
    kinds round-trip through INV-15 + INV-13 + INV-8 + INV-4.
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
                "warrant_basis": ("Same canonical obligor, replacement obligation."),
                "confidence": "medium",
                "shared_entities": [acme_entity_id],
            },
        ]
    }


# ---------------------------------------------------------------------------
# The integration test
# ---------------------------------------------------------------------------


def test_phase2b_end_to_end_produces_all_three_kinds(tmp_path: Path) -> None:
    """Full Phase 2a + 2b pipeline: plant → resolve → audit → connect.

    Asserts ≥1 cross-doc edge committed AND at least one of each
    relation kind (``supports``, ``attacks``, ``undercuts``).
    """
    # --- 1. Plant the 3-distillation workspace --------------------------------
    builder = _load_fixture_builder()
    workspace = builder.build_map_end_to_end_workspace(tmp_path)
    substrate = Substrate(workspace)

    # --- 2. Phase 2a: resolver + auditor (hand-placed outputs) ---------------
    _write_output(
        workspace,
        role="map-resolve",
        inputs_hash=_HASH_RESOLVE_ALL,
        payload=_make_resolver_payload(),
    )
    resolve_result = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert resolve_result.errors == [], (
        f"resolver reconcile reported errors: {resolve_result.errors!r}"
    )
    entities = list(substrate.list_entities())
    assert len(entities) == 5, f"expected 5 canonical entities, got {len(entities)}"
    resolutions = list(substrate.list_resolutions())
    assert len(resolutions) == 9, f"expected 9 resolutions, got {len(resolutions)}"

    # Auditor accepts everything (no clarifications raised).
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
    assert audit_result.errors == [], f"auditor reconcile errors: {audit_result.errors!r}"

    # --- 3. Phase 2b: Connect output with all three kinds --------------------
    entity_by_name = {e.canonical_name: e for e in entities}
    acme_entity = entity_by_name["ACME Corp"]

    _write_output(
        workspace,
        role="connect",
        inputs_hash=_HASH_CONNECT_ALL_KINDS,
        payload=_make_connect_payload(acme_entity_id=acme_entity.id),
    )

    connect_report = run_connect_phase(substrate)
    assert connect_report.errors == [], f"connect phase reported errors: {connect_report.errors!r}"

    # --- 4. Substrate assertions: ≥1 cross-doc edge AND every kind present --
    relations = list(substrate.list_cross_doc_relations())
    assert len(relations) >= 1, "expected at least one cross-doc relation; got none"

    kinds = {r.kind for r in relations}
    assert "supports" in kinds, f"missing kind 'supports'; got kinds={sorted(kinds)!r}"
    assert "attacks" in kinds, f"missing kind 'attacks'; got kinds={sorted(kinds)!r}"
    assert "undercuts" in kinds, f"missing kind 'undercuts'; got kinds={sorted(kinds)!r}"

    # All three relations reference the canonical ACME Corp entity.
    for rel in relations:
        assert acme_entity.id in rel.shared_entities, (
            f"relation {rel.id} does not reference ACME Corp; "
            f"shared_entities={rel.shared_entities!r}"
        )
        # Cross-source constraint must hold for every committed edge.
        assert rel.from_source_id != rel.to_source_id, (
            f"relation {rel.id} is intra-source (from={rel.from_source_id})"
        )

    # The orchestrator's report should reflect the 3 commits.
    assert len(connect_report.relations_committed) == 3, (
        f"expected 3 relations_committed; got {connect_report.relations_committed!r}"
    )


def test_phase2b_byte_identical_on_rerun(tmp_path: Path) -> None:
    """Re-running run_connect_phase against a clean substrate is byte-identical.

    INV-4 (read-only operations are deterministic) + INV-8 (path-as-truth):
    a second Connect phase invocation against the same substrate state must
    not mutate any committed CrossDocRelation file.
    """
    # --- Plant, resolve, audit -----------------------------------------------
    builder = _load_fixture_builder()
    workspace = builder.build_map_end_to_end_workspace(tmp_path)
    substrate = Substrate(workspace)

    _write_output(
        workspace,
        role="map-resolve",
        inputs_hash=_HASH_RESOLVE_ALL,
        payload=_make_resolver_payload(),
    )
    reconcile_outputs(substrate=substrate, workspace_root=workspace)

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
    reconcile_outputs(substrate=substrate, workspace_root=workspace)

    acme = next(e for e in entities if e.canonical_name == "ACME Corp")

    # --- First Connect phase: commits 3 relations ----------------------------
    _write_output(
        workspace,
        role="connect",
        inputs_hash=_HASH_CONNECT_ALL_KINDS,
        payload=_make_connect_payload(acme_entity_id=acme.id),
    )
    first_report = run_connect_phase(substrate)
    assert first_report.errors == [], f"first connect errors: {first_report.errors!r}"
    assert len(first_report.relations_committed) == 3

    snapshot_after_first = _hash_relations(workspace)
    assert len(snapshot_after_first) == 3, (
        f"expected 3 x-*.yaml files; got {sorted(snapshot_after_first)!r}"
    )

    # --- Second Connect phase: no new outputs, byte-identical relations -----
    second_report = run_connect_phase(substrate)
    assert second_report.errors == [], f"second connect errors: {second_report.errors!r}"
    # No new commits (the canned output was consumed; second run sees no
    # pending connect-* outputs). The relations directory is untouched.
    assert second_report.relations_committed == [], (
        f"expected no new commits on re-run; got {second_report.relations_committed!r}"
    )
    snapshot_after_second = _hash_relations(workspace)
    assert snapshot_after_first == snapshot_after_second, (
        "byte-identical idempotency violation: mappings/relations/ changed on re-run\n"
        + "\n".join(
            f"  CHANGED: {k}"
            for k in sorted(set(snapshot_after_first) | set(snapshot_after_second))
            if snapshot_after_first.get(k) != snapshot_after_second.get(k)
        )
    )
