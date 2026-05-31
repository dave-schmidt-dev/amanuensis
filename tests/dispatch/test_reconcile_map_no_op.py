"""Tests for the map-role no-op contract (T6.5 / SC-7 / R14).

Empty ``proposed_entities`` / ``proposed_resolutions`` lists produce
zero substrate writes but still append a replay-log entry with
``substrate_changes: []``. This is the SC-7 no-op invariant: every
reconcile run leaves a trace in the replay log regardless of whether
any artifacts were committed.
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
        "schema_version: 1\nproject_name: map-noop-test\n",
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


# --- map-resolve with empty lists -----------------------------------------


def test_map_resolve_empty_proposals_no_substrate_writes(tmp_path: Path) -> None:
    """Empty map-resolve proposals produce no entity/resolution writes."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    inputs_hash = "a" * 64

    _plant_output(
        workspace,
        "map-resolve",
        inputs_hash,
        {"proposed_entities": [], "proposed_resolutions": []},
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert result.errors == []
    assert result.atoms_committed == []
    assert result.relations_committed == []
    assert list(substrate.list_entities()) == []
    assert list(substrate.list_resolutions()) == []

    # Output moved to _consumed/.
    assert len(result.outputs_consumed) == 1

    # Replay log entry written with empty substrate_changes.
    log = ReplayLog.for_mappings(workspace)
    entries = list(log.list_entries())
    assert len(entries) == 1, f"expected 1 replay entry, got {entries!r}"
    assert entries[0].substrate_changes == []
    assert entries[0].activity == "map-resolve"


def test_map_resolve_missing_keys_treated_as_empty(tmp_path: Path) -> None:
    """A map-resolve payload with missing list keys behaves like empty lists."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    inputs_hash = "b" * 64

    # Payload has neither key.
    _plant_output(workspace, "map-resolve", inputs_hash, {})

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert result.errors == []
    assert list(substrate.list_entities()) == []
    assert list(substrate.list_resolutions()) == []

    log = ReplayLog.for_mappings(workspace)
    entries = list(log.list_entries())
    assert len(entries) == 1
    assert entries[0].substrate_changes == []


# --- map-audit with empty lists -------------------------------------------


def test_map_audit_empty_lists_no_substrate_writes(tmp_path: Path) -> None:
    """Empty map-audit payload produces no clarifications and a replay entry."""
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    inputs_hash = "c" * 64

    _plant_output(
        workspace,
        "map-audit",
        inputs_hash,
        {
            "accepted_entities": [],
            "accepted_resolutions": [],
            "clarifications": [],
            "inputs_hash": inputs_hash,
        },
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert result.errors == []
    assert result.clarifications_raised == []
    assert len(result.outputs_consumed) == 1

    log = ReplayLog.for_mappings(workspace)
    entries = list(log.list_entries())
    assert len(entries) == 1
    assert entries[0].substrate_changes == []
    assert entries[0].activity == "map-audit"
