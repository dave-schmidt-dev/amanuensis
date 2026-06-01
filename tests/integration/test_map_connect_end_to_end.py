"""Phase 2b M6 end-to-end orchestrator test: ``amanuensis map`` Connect phase.

Drives the full Connect-phase pipeline through the ``amanuensis map``
CLI orchestrator with mocked harness outputs:

1. Plant a workspace with 2 distillations + bilateral resolutions
   pointing into a shared canonical entity (the multi-source precondition).
2. Pre-place a Connector output payload under
   ``dispatch/outputs/connect-<hash>/output.yaml`` mimicking what a real
   harness would emit (canned candidate referencing the planted atoms +
   entity).
3. Invoke ``amanuensis map --connect-only`` via the Typer CliRunner.
4. Assert: the orchestrator enqueued one connect cluster, drained the
   canned output, and committed a ``CrossDocRelation`` to
   ``mappings/relations/``.
5. Re-run ``amanuensis map --connect-only`` against the (now-clean)
   substrate; no new ``CrossDocRelation`` is written and the existing
   queue entries are re-emitted byte-identically (cache-stable
   ``inputs_hash``).

The dispatch driver itself is the only short-cut: we hand-place the
canned ``output.yaml`` instead of spawning a real LLM. Every other
contract (cluster enumeration, queue write, output discovery, reconcile,
substrate commit, replay-log append) is exercised against real code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate

pytestmark = pytest.mark.integration


# Source / atom / entity ids reused across this module so the canned
# Connector output payload can reference them by hand.
_FROM_SRC = "src-A"
_FROM_ATOM = "a-A-shared00000000"
_TO_SRC = "src-B"
_TO_ATOM = "a-B-shared00000000"
_SHARED_ENTITY = "e-shared00000000a"


def _plant_workspace_with_connect_precondition(tmp_path: Path) -> Path:
    """Plant a workspace where two atoms in different sources resolve to ``e-shared``.

    The substrate state satisfies the INV-15 shared-entity gate's
    bilateral-resolution precondition, so a Connector candidate
    referencing both endpoints will commit cleanly.
    """
    from datetime import UTC, datetime

    from amanuensis.fs._atomic import atomic_write_text
    from amanuensis.fs._serialize import (
        serialize_atom_md,
        serialize_entity_md,
        serialize_resolution_yaml,
    )
    from amanuensis.schemas import (
        AgentAttribution,
        Atom,
        Entity,
        OperandRef,
        Resolution,
        RoleAttribution,
    )

    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: m6-connect-e2e\n",
        encoding="utf-8",
    )
    for src in (_FROM_SRC, _TO_SRC):
        (tmp_path / "distillations" / src).mkdir(parents=True, exist_ok=True)

    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)
    role_attr = RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="fixture", role="map-resolve"),
        activity="proposed",
        at=now,
    )

    # --- Plant atoms ---
    for src, atom_id, narrative, offset in [
        (_FROM_SRC, _FROM_ATOM, "Smith filed a brief in March 2024.", 0),
        (_TO_SRC, _TO_ATOM, "Smith was deposed in April 2024.", 0),
    ]:
        atom = Atom(
            id=atom_id,
            source_id=src,
            section_path=["body"],
            paragraph_index=0,
            sentence_index=None,
            char_span=(offset, offset + 30),
            scale_anchor="paragraph",
            kind="claim",
            predicate="references",
            operands=[
                OperandRef(role="subject", kind="entity", value="Smith", type_hint=None),
            ],
            narrative=narrative,
            qualifier_level=None,
            qualifier_basis=None,
            provenance_id="p-fixture00000010",
            role_attributions=[role_attr],
            schema_version=1,
        )
        atomic_write_text(
            tmp_path / "distillations" / src / "atoms" / f"{atom.id}.md",
            serialize_atom_md(atom),
        )

    # --- Plant the shared canonical entity ---
    entity = Entity(
        id=_SHARED_ENTITY,
        kind="party",
        canonical_name="Smith",
        aliases=[],
        notes=None,
        provenance_id="p-fixture00000020",
        role_attributions=[role_attr],
        schema_version=1,
    )
    atomic_write_text(
        tmp_path / "mappings" / "entities" / f"{entity.id}.md",
        serialize_entity_md(entity),
    )

    # --- Plant bilateral resolutions ---
    for slug, src, atom_id in [("from", _FROM_SRC, _FROM_ATOM), ("to", _TO_SRC, _TO_ATOM)]:
        res = Resolution(
            id=f"j-fixture-{slug}001",
            source_id=src,
            atom_id=atom_id,
            operand_index=0,
            entity_id=_SHARED_ENTITY,
            confidence="high",
            basis="fixture",
            provenance_id="p-fixture00000030",
            role_attributions=[role_attr],
            schema_version=1,
        )
        atomic_write_text(
            tmp_path / "mappings" / "resolutions" / f"{res.id}.yaml",
            serialize_resolution_yaml(res),
        )

    return tmp_path


def _place_connect_output(workspace: Path) -> Path:
    """Pre-place a canned Connector ``output.yaml`` under dispatch/outputs/."""
    inputs_hash = "e2etestconnect01"
    out_dir = workspace / "dispatch" / "outputs" / f"connect-{inputs_hash}"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "proposed_relations": [
            {
                "from_atom_id": _FROM_ATOM,
                "from_source_id": _FROM_SRC,
                "to_atom_id": _TO_ATOM,
                "to_source_id": _TO_SRC,
                "kind": "supports",
                "warrant": "Both atoms attest Smith's role in March/April 2024.",
                "warrant_defensibility": "conventional",
                "warrant_basis": "Two independent attestations of the same party.",
                "confidence": "medium",
                "shared_entities": [_SHARED_ENTITY],
            }
        ]
    }
    out_path = out_dir / "output.yaml"
    out_path.write_text(
        yaml.safe_dump(payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    return out_path


# ---------------------------------------------------------------------------
# T6.3: end-to-end orchestrator test
# ---------------------------------------------------------------------------


def test_amanuensis_map_connect_only_runs_connect_phase(tmp_path: Path) -> None:
    """``amanuensis map --connect-only`` enqueues clusters AND reconciles pending outputs."""
    workspace = _plant_workspace_with_connect_precondition(tmp_path)
    canned_output_path = _place_connect_output(workspace)
    assert canned_output_path.is_file()

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--connect-only"],
    )
    assert result.exit_code == 0, (
        f"map --connect-only failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    # The canned output landed as a committed CrossDocRelation.
    sub = Substrate(workspace)
    rels = list(sub.list_cross_doc_relations())
    assert len(rels) == 1, f"expected one cross-doc relation; got {len(rels)}"
    rel = rels[0]
    assert rel.from_source_id == _FROM_SRC
    assert rel.to_source_id == _TO_SRC
    assert _SHARED_ENTITY in rel.shared_entities

    # The orchestrator also enqueued the cluster for the next dispatch run.
    queue_dir = workspace / "dispatch" / "queue"
    queue_entries = sorted(queue_dir.glob("connect-*.yaml"))
    assert len(queue_entries) >= 1, "expected at least one connect cluster on the queue"

    # The canned output is now under _consumed/ (reconciler idempotency).
    consumed = workspace / "dispatch" / "outputs" / "_consumed"
    assert any(consumed.rglob("output.yaml")), (
        "expected the canned connect output to move into _consumed/"
    )

    # Summary line ends with the phase counters.
    assert "Connect phase:" in result.stdout or "connect:" in result.stdout
    assert "relations_committed=1" in result.stdout


def test_amanuensis_map_no_connect_only_runs_full_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``amanuensis map`` (no flag) runs the resolve handoff THEN the connect phase.

    No canned connect outputs land — we only verify that the orchestrator
    proceeds past the resolve handoff, enqueues a map-resolve queue
    entry, AND runs the connect phase enumeration on the same substrate.
    """
    workspace = _plant_workspace_with_connect_precondition(tmp_path)

    # Install fake map-resolve / map-audit skills so the preflight passes.
    fake_home = tmp_path / "fake_home"
    skills_dir = fake_home / ".claude" / "skills" / "amanuensis"
    skills_dir.mkdir(parents=True)
    (skills_dir / "map_resolve.md").write_text("---\nrole: map-resolve\n---\nbody")
    (skills_dir / "map_audit.md").write_text("---\nrole: map-audit\n---\nbody")
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--non-interactive"],
    )
    assert result.exit_code == 0, (
        f"map without flag failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    # Resolve handoff produced one map-resolve queue entry.
    map_resolve_entries = list((workspace / "dispatch" / "queue").glob("map-resolve-*.yaml"))
    assert len(map_resolve_entries) == 1, (
        f"expected one map-resolve queue entry, got {map_resolve_entries!r}"
    )

    # Connect phase ALSO ran (one connect-cluster on the queue).
    connect_entries = list((workspace / "dispatch" / "queue").glob("connect-*.yaml"))
    assert len(connect_entries) >= 1, (
        f"expected at least one connect queue entry, got {connect_entries!r}"
    )

    # The output summarises both phases.
    assert "Enqueued role: map-resolve-" in result.stdout
    assert "Connect phase:" in result.stdout
