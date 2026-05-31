"""Tests for the map-audit reconciliation path (T6.4).

Covers:
1. Accepted entity / resolution ids that exist in the substrate produce no
   errors and append a mappings replay-log entry.
2. An accepted entity id that is NOT in the substrate surfaces as an error.
3. A clarification entry writes an open clarification under the correct
   distillation source and records the id in result.clarifications_raised.
4. All three clarification kinds (resolution-disputed,
   resolution-ambiguous, warrant-defensibility-contested) are accepted.
5. An unknown clarification kind is normalised to ``resolution-disputed``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import ReplayLog, Substrate

# --- Local fixtures --------------------------------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: map-audit-test\n",
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


def _plant_resolve_output(workspace: Path, inputs_hash: str, payload: dict[str, Any]) -> Path:
    return _plant_output(workspace, "map-resolve", inputs_hash, payload)


def _plant_audit_output(workspace: Path, inputs_hash: str, payload: dict[str, Any]) -> Path:
    return _plant_output(workspace, "map-audit", inputs_hash, payload)


# --- Helper: plant a known entity + resolution in the substrate -----------


def _plant_entity_and_resolution(workspace: Path) -> tuple[str, str]:
    """Run a map-resolve reconcile to plant a real entity + resolution.

    Returns (entity_id, resolution_id).
    """
    substrate = Substrate(workspace)
    resolve_hash = "e" * 64
    _plant_resolve_output(
        workspace,
        resolve_hash,
        {
            "proposed_entities": [
                {"kind": "organization", "canonical_name": "ACME Corp", "aliases": ["Acme"]}
            ],
            "proposed_resolutions": [
                {
                    "entity_index": 0,
                    "source_id": "src-audit",
                    "atom_id": "a-" + "0" * 16,
                    "operand_index": 0,
                    "confidence": "high",
                    "basis": "name match",
                }
            ],
        },
    )
    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert result.errors == [], f"resolve-plant errors: {result.errors!r}"
    entities = list(substrate.list_entities())
    resolutions = list(substrate.list_resolutions())
    return entities[0].id, resolutions[0].id


# --- 1. Accepted ids that exist → no errors, replay entry appended --------


def test_map_audit_accepted_ids_no_errors(tmp_path: Path) -> None:
    """Accepted entity / resolution ids that exist produce no errors."""
    workspace = _make_workspace(tmp_path)
    entity_id, resolution_id = _plant_entity_and_resolution(workspace)

    substrate = Substrate(workspace)
    audit_hash = "f" * 64
    _plant_audit_output(
        workspace,
        audit_hash,
        {
            "accepted_entities": [entity_id],
            "accepted_resolutions": [resolution_id],
            "clarifications": [],
            "inputs_hash": audit_hash,
        },
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert result.errors == [], f"unexpected errors: {result.errors!r}"
    assert len(result.outputs_consumed) == 1

    # Mappings replay log appended.
    log = ReplayLog.for_mappings(workspace)
    entries = list(log.list_entries())
    # One entry from resolve, one from audit.
    assert len(entries) == 2, f"expected 2 replay entries, got {entries!r}"
    audit_entry = entries[-1]
    assert audit_entry.activity == "map-audit"


# --- 2. Accepted entity id not in substrate → error -----------------------


def test_map_audit_unknown_accepted_entity_id_is_error(tmp_path: Path) -> None:
    """An accepted entity id not present in the substrate is recorded as an error."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    audit_hash = "g" * 64
    _plant_audit_output(
        workspace,
        audit_hash,
        {
            "accepted_entities": ["e-" + "9" * 16],
            "accepted_resolutions": [],
            "clarifications": [],
            "inputs_hash": audit_hash,
        },
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert any("not found" in reason for _, reason in result.errors), (
        f"expected 'not found' error in {result.errors!r}"
    )
    # Output is still consumed even with the cross-check error.
    assert len(result.outputs_consumed) == 1


# --- 3. Clarification written and tracked ---------------------------------


def test_map_audit_clarification_written(tmp_path: Path) -> None:
    """A clarification entry produces an open clarification file."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    audit_hash = "h" * 64
    source_id = "src-audit-clar"
    (workspace / "distillations" / source_id).mkdir(parents=True, exist_ok=True)

    _plant_audit_output(
        workspace,
        audit_hash,
        {
            "accepted_entities": [],
            "accepted_resolutions": [],
            "clarifications": [
                {
                    "kind": "resolution-disputed",
                    "source_id": source_id,
                    "context_refs": ["j-" + "0" * 16],
                    "question": "Is this entity the correct match?",
                }
            ],
            "inputs_hash": audit_hash,
        },
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert result.errors == [], f"unexpected errors: {result.errors!r}"
    assert len(result.clarifications_raised) == 1
    clar_id = result.clarifications_raised[0]
    assert clar_id.startswith("c-"), f"unexpected clarification id: {clar_id!r}"

    # Open clarification file exists on disk.
    clar_path = substrate.clarification_path(source_id, clar_id, resolved=False)
    assert clar_path.is_file(), f"open clarification file missing at {clar_path}"


# --- 4. All three clarification kinds accepted ----------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "resolution-disputed",
        "resolution-ambiguous",
        "warrant-defensibility-contested",
    ],
)
def test_map_audit_all_clarification_kinds_accepted(tmp_path: Path, kind: str) -> None:
    """Each of the three valid clarification kinds produces a written clarification."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    inputs_hash = "i" * 64
    source_id = "src-audit-kinds"
    (workspace / "distillations" / source_id).mkdir(parents=True, exist_ok=True)

    _plant_audit_output(
        workspace,
        inputs_hash,
        {
            "accepted_entities": [],
            "accepted_resolutions": [],
            "clarifications": [
                {
                    "kind": kind,
                    "source_id": source_id,
                    "context_refs": [],
                    "question": f"Test question for kind {kind!r}.",
                }
            ],
            "inputs_hash": inputs_hash,
        },
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert result.errors == [], f"unexpected errors for kind={kind!r}: {result.errors!r}"
    assert len(result.clarifications_raised) == 1


# --- 5. Unknown kind normalised to resolution-disputed --------------------


def test_map_audit_unknown_kind_normalised(tmp_path: Path) -> None:
    """An unrecognised clarification kind is silently normalised to resolution-disputed."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    inputs_hash = "j" * 64
    source_id = "src-audit-badkind"
    (workspace / "distillations" / source_id).mkdir(parents=True, exist_ok=True)

    _plant_audit_output(
        workspace,
        inputs_hash,
        {
            "accepted_entities": [],
            "accepted_resolutions": [],
            "clarifications": [
                {
                    "kind": "completely-unknown-kind",
                    "source_id": source_id,
                    "context_refs": [],
                    "question": "Does normalisation work?",
                }
            ],
            "inputs_hash": inputs_hash,
        },
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert result.errors == []
    assert len(result.clarifications_raised) == 1

    # Read back and verify kind was normalised.
    clar_id = result.clarifications_raised[0]
    clar_path = substrate.clarification_path(source_id, clar_id, resolved=False)
    assert clar_path.is_file()
    content = clar_path.read_text(encoding="utf-8")
    assert "resolution-disputed" in content, f"expected normalised kind in content: {content!r}"
