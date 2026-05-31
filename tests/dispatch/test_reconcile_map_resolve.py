"""Tests for the map-resolve reconciliation path (T6.3).

Covers:
1. A valid single-entity + single-resolution proposal commits both
   artifacts and appends a mappings replay-log entry.
2. An entity with a bad field value (empty kind) surfaces as an error
   without writing partial state.
3. A resolution with an out-of-range entity_index surfaces as an error.
4. A second identical reconcile of the same payload is a no-op (entity
   idempotency via Substrate.add_entity).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import ReplayLog, Substrate

# --- Local fixtures --------------------------------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: map-resolve-test\n",
        encoding="utf-8",
    )
    return tmp_path


def _plant_output(workspace: Path, role: str, inputs_hash: str, payload: dict[str, Any]) -> Path:
    out_dir = workspace / "dispatch" / "outputs" / f"{role}-{inputs_hash}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "output.yaml"
    out_path.write_text(
        yaml.safe_dump(payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    return out_path


def _entity_payload(
    *,
    kind: str = "organization",
    canonical_name: str = "ACME Corp",
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "canonical_name": canonical_name,
        "aliases": aliases or ["Acme"],
        "notes": "test entity",
    }


def _resolution_payload(
    *,
    entity_index: int = 0,
    source_id: str = "src-1",
    atom_id: str = "a-" + "0" * 16,
    operand_index: int = 0,
    confidence: str = "high",
    basis: str = "name match",
) -> dict[str, Any]:
    return {
        "entity_index": entity_index,
        "source_id": source_id,
        "atom_id": atom_id,
        "operand_index": operand_index,
        "confidence": confidence,
        "basis": basis,
    }


# --- 1. Happy path: entity + resolution committed -------------------------


def test_map_resolve_commits_entity_and_resolution(tmp_path: Path) -> None:
    """A valid proposal writes entity, resolution, provenance, and replay log."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    inputs_hash = "a" * 64

    _plant_output(
        workspace,
        "map-resolve",
        inputs_hash,
        {
            "proposed_entities": [_entity_payload()],
            "proposed_resolutions": [_resolution_payload()],
        },
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert result.errors == [], f"unexpected errors: {result.errors!r}"
    assert len(result.outputs_consumed) == 1

    # Entity committed.
    entities = list(substrate.list_entities())
    assert len(entities) == 1, f"expected 1 entity, got {entities!r}"
    entity = entities[0]
    assert entity.id.startswith("e-"), f"unexpected entity id shape: {entity.id!r}"
    assert entity.canonical_name == "ACME Corp"

    # Entity file on disk.
    entity_path = substrate.entity_path(entity.id)
    assert entity_path.is_file(), f"entity file missing at {entity_path}"

    # Resolution committed.
    resolutions = list(substrate.list_resolutions())
    assert len(resolutions) == 1, f"expected 1 resolution, got {resolutions!r}"
    resolution = resolutions[0]
    assert resolution.id.startswith("j-"), f"unexpected resolution id shape: {resolution.id!r}"
    assert resolution.entity_id == entity.id

    # Provenance files written under mappings/provenance/.
    prov_dir = workspace / "mappings" / "provenance"
    assert prov_dir.is_dir(), "mappings/provenance/ not created"
    prov_files = list(prov_dir.glob("p-*.yaml"))
    # One prov for entity + one for resolution.
    assert len(prov_files) >= 2, f"expected >=2 prov files, got {prov_files!r}"

    # Mappings replay log appended.
    log = ReplayLog.for_mappings(workspace)
    entries = list(log.list_entries())
    assert len(entries) == 1, f"expected 1 replay entry, got {entries!r}"
    entry = entries[0]
    assert entry.activity == "map-resolve"
    assert len(entry.substrate_changes) >= 2  # at least entity + resolution paths


# --- 2. Entity build failure: error, no partial write ---------------------


def test_map_resolve_entity_build_failure_recorded_as_error(tmp_path: Path) -> None:
    """An entity dict with a schema-violating value surfaces as an error.

    The resolution that references the failed entity is skipped (entity_id
    is empty after the build failure).
    """
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    inputs_hash = "b" * 64

    # kind="" is invalid for Entity (empty string fails the schema).
    bad_entity = _entity_payload(kind="")
    _plant_output(
        workspace,
        "map-resolve",
        inputs_hash,
        {
            "proposed_entities": [bad_entity],
            "proposed_resolutions": [_resolution_payload(entity_index=0)],
        },
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    # Error recorded but output file still consumed (the gate always moves).
    assert len(result.errors) >= 1, "expected at least one error for bad entity"
    assert any("entity-build" in reason for _, reason in result.errors), (
        f"expected entity-build error in {result.errors!r}"
    )
    # No entities written.
    assert list(substrate.list_entities()) == []


# --- 3. Resolution with out-of-range entity_index ------------------------


def test_map_resolve_resolution_out_of_range_entity_index(tmp_path: Path) -> None:
    """A resolution referencing entity_index beyond the proposals list is an error."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    inputs_hash = "c" * 64

    _plant_output(
        workspace,
        "map-resolve",
        inputs_hash,
        {
            "proposed_entities": [_entity_payload()],
            # entity_index=5 but only 1 entity was proposed.
            "proposed_resolutions": [_resolution_payload(entity_index=5)],
        },
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert len(result.errors) >= 1, "expected out-of-range error"
    assert any("entity_index" in reason for _, reason in result.errors), (
        f"expected entity_index error in {result.errors!r}"
    )
    # Entity is still committed even though the resolution failed.
    assert len(list(substrate.list_entities())) == 1


# --- 4. Idempotency: second reconcile is a no-op -------------------------


def test_map_resolve_idempotent_on_second_run(tmp_path: Path) -> None:
    """Re-planting the same proposal and reconciling again does not duplicate artifacts."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    inputs_hash = "d" * 64

    payload = {
        "proposed_entities": [_entity_payload()],
        "proposed_resolutions": [_resolution_payload()],
    }

    # First run.
    _plant_output(workspace, "map-resolve", inputs_hash, payload)
    result1 = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert result1.errors == []

    # Second run with identical content re-planted.
    _plant_output(workspace, "map-resolve", inputs_hash, payload)
    result2 = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert result2.errors == [], f"second run errors: {result2.errors!r}"

    # Still only one entity and one resolution.
    assert len(list(substrate.list_entities())) == 1
    assert len(list(substrate.list_resolutions())) == 1
