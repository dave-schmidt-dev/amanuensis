"""End-to-end dispatch flow test for the map-resolve / map-audit pair (T6.8).

Drives the full enqueue → simulated-driver-output → reconcile sequence
for both Phase 2a map roles, with mocked role payloads (no real LLM
invocation). The pair completes against a substrate seeded with the
minimum context the resolver / auditor need.

Mirrors the style of ``tests/integration/test_distill_tiny_fixture.py``:
the dispatch driver itself is the only short-cut — we write the role's
``output.yaml`` synthetically rather than spawning a model — but every
other contract (queue write, output discovery, reconcile, mappings
substrate writes, replay-log append) is exercised against the real code.

Covers:
1. Enqueue map-resolve; simulate driver output proposing one entity +
   one resolution. Reconcile commits both to mappings/.
2. Enqueue map-audit referencing the just-committed entity / resolution
   ids; simulate auditor accepting both with no clarifications. Reconcile
   surfaces no errors, no clarifications, and appends a second
   mappings-scope replay-log entry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from amanuensis.dispatch.queue import enqueue
from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import ReplayLog, Substrate
from amanuensis.llm.queue import DispatchQueueEntry


def _make_workspace(tmp_path: Path) -> Path:
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: map-pair-integration\n",
        encoding="utf-8",
    )
    return tmp_path


def _write_output(workspace: Path, *, role: str, inputs_hash: str, payload: dict[str, Any]) -> Path:
    out_dir = workspace / "dispatch" / "outputs" / f"{role}-{inputs_hash}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "output.yaml"
    out_path.write_text(
        yaml.safe_dump(payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    return out_path


def _queue_entry(role: str, inputs_hash: str) -> DispatchQueueEntry:
    return DispatchQueueEntry(
        role=role,
        prompt=f"<mock {role} prompt>",
        inputs={"placeholder": True},
        model_id="claude-opus-4-7",
        inputs_hash=inputs_hash,
        enqueued_at=datetime.now(UTC),
    )


def test_full_map_role_pair_flow(tmp_path: Path) -> None:
    """Enqueue resolver, reconcile, enqueue auditor, reconcile — clean pass."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)

    # --- Phase 1: enqueue + simulate + reconcile map-resolve ---------------
    resolve_hash = "1" * 64
    queue_path = enqueue(workspace, _queue_entry("map-resolve", resolve_hash))
    assert queue_path.is_file()

    resolve_payload: dict[str, Any] = {
        "proposed_entities": [
            {
                "kind": "organization",
                "canonical_name": "ACME Corp",
                "aliases": ["Acme"],
                "notes": "supplier of widgets",
            },
        ],
        "proposed_resolutions": [
            {
                "entity_index": 0,
                "source_id": "src-pair",
                "atom_id": "a-" + "0" * 16,
                "operand_index": 0,
                "confidence": "high",
                "basis": "exact name match",
            },
        ],
    }
    _write_output(workspace, role="map-resolve", inputs_hash=resolve_hash, payload=resolve_payload)

    resolve_result = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert resolve_result.errors == [], f"resolve errors: {resolve_result.errors!r}"
    assert len(resolve_result.outputs_consumed) == 1

    entities = list(substrate.list_entities())
    resolutions = list(substrate.list_resolutions())
    assert len(entities) == 1, f"expected 1 entity, got {entities!r}"
    assert len(resolutions) == 1, f"expected 1 resolution, got {resolutions!r}"
    entity_id = entities[0].id
    resolution_id = resolutions[0].id

    # --- Phase 2: enqueue + simulate + reconcile map-audit -----------------
    audit_hash = "2" * 64
    enqueue(workspace, _queue_entry("map-audit", audit_hash))

    audit_payload: dict[str, Any] = {
        "accepted_entities": [entity_id],
        "accepted_resolutions": [resolution_id],
        "rejected_entities": [],
        "rejected_resolutions": [],
        "clarifications": [],
        "inputs_hash": audit_hash,
    }
    _write_output(workspace, role="map-audit", inputs_hash=audit_hash, payload=audit_payload)

    audit_result = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert audit_result.errors == [], f"audit errors: {audit_result.errors!r}"
    assert audit_result.clarifications_raised == [], (
        f"clean accept should raise no clarifications: {audit_result.clarifications_raised!r}"
    )
    assert len(audit_result.outputs_consumed) == 1

    # --- Cross-cutting: mappings replay-log carries both runs --------------
    log = ReplayLog.for_mappings(workspace)
    entries = list(log.list_entries())
    assert len(entries) == 2, f"expected 2 mappings replay entries, got {len(entries)}: {entries!r}"
    activities = [e.activity for e in entries]
    assert "map-resolve" in activities
    assert "map-audit" in activities

    # --- Cross-cutting: substrate state unchanged by audit run -------------
    assert len(list(substrate.list_entities())) == 1
    assert len(list(substrate.list_resolutions())) == 1
