"""Phase 2a M11 end-to-end integration test for the full map pipeline (T11.2).

Drives the complete map pipeline against a 3-distillation synthetic corpus:

1. Plant the workspace via ``build_map_end_to_end_workspace``.
2. Write one synthesized ``dispatch/outputs/map-resolve-<hash>/output.yaml``
   proposing all 5 canonical entities and all 9 resolutions (atoms from all
   3 distillations).  A single inputs_hash ensures ``_stable_role_attribution_at``
   produces stable timestamps so entity ids are deterministic.
3. ``reconcile_outputs`` → assert 5 entities, 9 resolutions, no errors.
4. Verify cross-document resolution: the "ACME Corp" and "BetaCo Ltd"
   entities each have resolutions from atoms in all 3 distillations.
5. Write a synthesized ``map-audit-<hash>/output.yaml`` accepting all
   entities/resolutions with no clarifications. Reconcile → no errors.
6. Replay idempotency (CR-5): call ``reconcile_outputs`` again immediately
   after all outputs have been consumed; the pending queue is empty so
   ``outputs_consumed == []`` and ``mappings/`` (excluding ``replay-log/``)
   is byte-identical to the snapshot before the replay call.

The dispatch driver itself is the only short-cut: role outputs are written
synthetically rather than invoking a real LLM. Every other contract
(output discovery, reconcile, mappings substrate writes, duplicate-triple
guard, replay-log append) is exercised against production code.

Mirrors the style of ``tests/dispatch/test_map_role_pair.py`` scaled to
3 distillations and the 5-entity deduplication scenario documented in
``tests/fixtures/map-end-to-end/SOURCES.md``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import ReplayLog, Substrate

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


def _hash_mappings(workspace: Path) -> dict[str, bytes]:
    """Return {relative-path: content-bytes} for all files under mappings/,
    excluding mappings/replay-log/ (CR-5: replay log is explicitly excluded
    from the idempotency snapshot)."""
    mappings_root = workspace / "mappings"
    if not mappings_root.is_dir():
        return {}
    result: dict[str, bytes] = {}
    for p in sorted(mappings_root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(workspace))
        # Skip replay-log per CR-5.
        if rel.startswith("mappings/replay-log/") or rel.startswith("mappings\\replay-log\\"):
            continue
        result[rel] = p.read_bytes()
    return result


# ---------------------------------------------------------------------------
# Resolver payload
#
# A SINGLE resolver output proposes all 5 canonical entities and all 9
# resolutions across all 3 distillations.  Using one inputs_hash is
# essential: _build_entity in reconcile.py derives a stable role_attribution
# timestamp from inputs_hash via _stable_role_attribution_at.  Two runs with
# different inputs_hashes proposing "ACME Corp" produce two different entity
# ids (different content hash) — add_entity would write them to different
# paths rather than deduplicating.  A single inputs_hash eliminates that
# problem: all 5 entities are committed in one pass; the 9 resolutions
# reference atom ids that span all 3 source_ids.
#
#   Entity index  canonical_name    surface forms merged
#   0             ACME Corp         "ACME Corp" (x2), "ACME Corporation"
#   1             BetaCo Ltd        "BetaCo Ltd", "BetaCo Ltd.", "BetaCo"
#   2             Contract Draft 1  "Contract Draft 1"
#   3             Contract Draft 2  "Contract Draft 2"
#   4             Counsel for ACME  "Counsel for ACME"
# ---------------------------------------------------------------------------

# Stable atom ids produced by the fixture builder (deterministic because
# compute_id is pure and all inputs are fixed in the builder).
_CD1_ATOM_ACME = "a-ed6c0eb084918d05"
_CD1_ATOM_BETACO = "a-ebc28e91f7e5b843"
_CD1_ATOM_DRAFT1 = "a-688b086a934eb635"

_CD2_ATOM_ACME_CORP = "a-4e6b201e1cae5e95"  # "ACME Corporation"
_CD2_ATOM_BETACO_LTD = "a-54e5ec5f12fe5809"  # "BetaCo Ltd."
_CD2_ATOM_DRAFT2 = "a-aff4b81a17af60d0"

_SI_ATOM_ACME = "a-2245cf8ea1f02e8a"  # "ACME Corp"
_SI_ATOM_BETACO = "a-149f73c02c98417b"  # "BetaCo"
_SI_ATOM_COUNSEL = "a-d43e92c75baadd2e"  # "Counsel for ACME"

# Single inputs_hash shared by all resolver proposals (keeps entity ids stable).
_HASH_RESOLVE_ALL = "a" * 64
_HASH_AUDIT_1 = "d" * 64

# Source ids (mirrored from fixture builder constants)
_SRC_CD1 = "contract-draft-1"
_SRC_CD2 = "contract-draft-2"
_SRC_SI = "settlement-instrument"


def _make_resolver_payload() -> dict[str, Any]:
    """Single resolver output covering all 5 entities and all 9 resolutions.

    Proposes all 5 canonical entities, then maps each of the 9 atom
    entity-kind obligor operands (3 per distillation) to the appropriate
    canonical entity via its entity_index.
    """
    return {
        "proposed_entities": [
            # index 0
            {
                "kind": "organization",
                "canonical_name": "ACME Corp",
                "aliases": ["ACME Corporation"],
                "notes": "party A",
            },
            # index 1
            {
                "kind": "organization",
                "canonical_name": "BetaCo Ltd",
                "aliases": ["BetaCo Ltd.", "BetaCo"],
                "notes": "party B",
            },
            # index 2
            {
                "kind": "document",
                "canonical_name": "Contract Draft 1",
                "aliases": [],
                "notes": "first draft",
            },
            # index 3
            {
                "kind": "document",
                "canonical_name": "Contract Draft 2",
                "aliases": [],
                "notes": "second draft",
            },
            # index 4
            {
                "kind": "person",
                "canonical_name": "Counsel for ACME",
                "aliases": [],
                "notes": "legal counsel",
            },
        ],
        "proposed_resolutions": [
            # contract-draft-1 atoms
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
            # contract-draft-2 atoms
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
            # settlement-instrument atoms
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


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


def test_map_pipeline_end_to_end(tmp_path: Path) -> None:
    """Full map pipeline: plant → resolve (all 3 sources) → audit → idempotency.

    T11.2 integration gate for Phase 2a M11.
    """
    # --- 1. Plant the 3-distillation workspace --------------------------------
    builder = _load_fixture_builder()
    workspace = builder.build_map_end_to_end_workspace(tmp_path)
    substrate = Substrate(workspace)

    # --- 2. Write a single resolver output covering all 3 distillations ------
    _write_output(
        workspace,
        role="map-resolve",
        inputs_hash=_HASH_RESOLVE_ALL,
        payload=_make_resolver_payload(),
    )

    # --- 3. Reconcile resolver output -----------------------------------------
    resolve_result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert resolve_result.errors == [], (
        f"resolver reconcile reported errors: {resolve_result.errors!r}"
    )
    assert len(resolve_result.outputs_consumed) == 1, (
        f"expected 1 output consumed, got {len(resolve_result.outputs_consumed)}"
    )

    # --- 4. Verify substrate: 5 canonical entities, 9 resolutions ------------
    entities = list(substrate.list_entities())
    assert len(entities) == 5, (
        f"expected 5 canonical entities after deduplication, got {len(entities)}: "
        f"{[e.canonical_name for e in entities]!r}"
    )

    resolutions = list(substrate.list_resolutions())
    assert len(resolutions) == 9, (
        f"expected 9 resolutions (one per atom entity-operand), got {len(resolutions)}"
    )

    # --- 5. Cross-document resolution: ACME Corp and BetaCo Ltd span all 3 ---
    entity_by_name = {e.canonical_name: e for e in entities}

    acme_entity = entity_by_name.get("ACME Corp")
    assert acme_entity is not None, "ACME Corp entity missing from substrate"
    acme_resolutions = list(substrate.list_resolutions(where_entity_id=acme_entity.id))
    assert len(acme_resolutions) == 3, (
        f"ACME Corp should have 3 resolutions (one per distillation), got {len(acme_resolutions)}"
    )
    acme_source_ids = {r.source_id for r in acme_resolutions}
    assert acme_source_ids == {_SRC_CD1, _SRC_CD2, _SRC_SI}, (
        f"ACME Corp resolutions should span all 3 distillations, got source_ids={acme_source_ids!r}"
    )

    betaco_entity = entity_by_name.get("BetaCo Ltd")
    assert betaco_entity is not None, "BetaCo Ltd entity missing from substrate"
    betaco_resolutions = list(substrate.list_resolutions(where_entity_id=betaco_entity.id))
    assert len(betaco_resolutions) == 3, (
        f"BetaCo Ltd should have 3 resolutions (one per distillation), "
        f"got {len(betaco_resolutions)}"
    )
    betaco_source_ids = {r.source_id for r in betaco_resolutions}
    assert betaco_source_ids == {_SRC_CD1, _SRC_CD2, _SRC_SI}, (
        f"BetaCo Ltd resolutions should span all 3 distillations, "
        f"got source_ids={betaco_source_ids!r}"
    )

    # Resolutions cover every entity-kind atom operand planted in the fixture.
    all_resolution_triples = {(r.source_id, r.atom_id, r.operand_index) for r in resolutions}
    expected_triples = {
        (_SRC_CD1, _CD1_ATOM_ACME, 0),
        (_SRC_CD1, _CD1_ATOM_BETACO, 0),
        (_SRC_CD1, _CD1_ATOM_DRAFT1, 0),
        (_SRC_CD2, _CD2_ATOM_ACME_CORP, 0),
        (_SRC_CD2, _CD2_ATOM_BETACO_LTD, 0),
        (_SRC_CD2, _CD2_ATOM_DRAFT2, 0),
        (_SRC_SI, _SI_ATOM_ACME, 0),
        (_SRC_SI, _SI_ATOM_BETACO, 0),
        (_SRC_SI, _SI_ATOM_COUNSEL, 0),
    }
    assert all_resolution_triples == expected_triples, (
        f"resolution triples mismatch.\n"
        f"  expected: {sorted(expected_triples)!r}\n"
        f"  got:      {sorted(all_resolution_triples)!r}"
    )

    # --- 6. Write + reconcile auditor output (accept all, no clarifications) ---
    entity_ids = [e.id for e in entities]
    resolution_ids = [r.id for r in resolutions]
    audit_payload: dict[str, Any] = {
        "accepted_entities": entity_ids,
        "accepted_resolutions": resolution_ids,
        "rejected_entities": [],
        "rejected_resolutions": [],
        "clarifications": [],
        "inputs_hash": _HASH_AUDIT_1,
    }
    _write_output(workspace, role="map-audit", inputs_hash=_HASH_AUDIT_1, payload=audit_payload)

    audit_result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert audit_result.errors == [], f"auditor reconcile reported errors: {audit_result.errors!r}"
    assert audit_result.clarifications_raised == [], (
        f"clean accept should raise no clarifications; got {audit_result.clarifications_raised!r}"
    )
    assert len(audit_result.outputs_consumed) == 1

    # Substrate unchanged by audit (entities / resolutions immutable).
    assert len(list(substrate.list_entities())) == 5
    assert len(list(substrate.list_resolutions())) == 9

    # --- 7. Idempotency replay (CR-5) ----------------------------------------
    # Snapshot mappings/ (excluding replay-log/) BEFORE the replay call.
    snapshot_before = _hash_mappings(workspace)

    # Re-run reconcile with an empty pending queue: nothing to consume,
    # nothing to write.  The mappings tree must be byte-identical.
    replay_result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert replay_result.errors == [], (
        f"idempotency replay reported errors: {replay_result.errors!r}"
    )
    assert replay_result.outputs_consumed == [], (
        f"expected 0 outputs consumed in replay (queue drained), "
        f"got {len(replay_result.outputs_consumed)}"
    )

    # Snapshot mappings/ AFTER replay.
    snapshot_after = _hash_mappings(workspace)

    # CR-5: mappings/ (excluding replay-log/) must be byte-identical.
    assert snapshot_before == snapshot_after, (
        "idempotency violation: mappings/ changed on replay\n"
        + "\n".join(
            f"  CHANGED: {k}"
            for k in sorted(set(snapshot_before) | set(snapshot_after))
            if snapshot_before.get(k) != snapshot_after.get(k)
        )
    )

    # Entity + resolution counts unchanged.
    assert len(list(substrate.list_entities())) == 5
    assert len(list(substrate.list_resolutions())) == 9

    # --- 8. Replay-log entries ------------------------------------------------
    log = ReplayLog.for_mappings(workspace)
    entries = list(log.list_entries())
    # One entry for map-resolve, one for map-audit (replay run appends nothing).
    assert len(entries) == 2, (
        f"expected 2 mappings replay-log entries (resolve + audit), "
        f"got {len(entries)}: {[e.activity for e in entries]!r}"
    )
    activities = {e.activity for e in entries}
    assert "map-resolve" in activities
    assert "map-audit" in activities


# ---------------------------------------------------------------------------
# Guard: fixture builder module is importable
# ---------------------------------------------------------------------------


def test_fixture_builder_importable() -> None:
    """Smoke-guard: the fixture builder module loads without error."""
    assert _FIXTURE_BUILDER_PATH.is_file(), f"fixture builder not found at {_FIXTURE_BUILDER_PATH}"
    mod = _load_fixture_builder()
    assert hasattr(mod, "build_map_end_to_end_workspace")
    assert hasattr(mod, "SOURCE_CONTRACT_1")
    assert hasattr(mod, "SOURCE_CONTRACT_2")
    assert hasattr(mod, "SOURCE_SETTLEMENT")
