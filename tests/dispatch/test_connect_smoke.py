"""Smoke test: Connector dispatch reconcile cycle with a mocked harness.

Phase 2b M5/T5.4. The Connector role's full dispatch pipeline is:

    orchestrator (M6, future) → dispatch queue → driver → harness
    → output.yaml → reconciler → CrossDocRelation in substrate

M5 wires the reconciler half (the output.yaml → substrate edge). The
orchestrator's cluster-enumeration logic is M6's job. This smoke test
therefore short-circuits the upper half: it hand-places a Connector
output.yaml (the artifact a real harness would emit) under
``dispatch/outputs/connect-<hash>/`` and calls
:func:`reconcile_outputs` directly.

What this test proves:

- ``_process_connect_output`` is reachable from ``reconcile_outputs``
  (the role-routing branch is wired correctly).
- A well-formed candidate round-trips to a committed
  ``CrossDocRelation`` in ``mappings/relations/``.
- The PROV record lands in ``mappings/provenance/`` and the
  consumed output file moves into the ``_consumed/`` subtree (idempotency).
- The mappings-scope replay-log records the activity.

What this test does NOT prove (M6's surface):

- Queue dequeue / driver invocation. The mock harness is implicit;
  no subprocess is run.
- Cluster enumeration / inputs_hash derivation. We pin a synthetic
  hash so the path layout is deterministic.

Rationale for the simplified shape: the M5 task brief explicitly
permits hand-placing the output file when the full enqueue/driver
scaffolding would expand the test beyond ~50 lines. The reconciler
edge is the M5 → M4 bond and is the only contract M5 needs to prove.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import Substrate
from amanuensis.schemas import ProvenanceRecord, RoleAttribution

from .conftest import (
    FROM_ATOM_ID,
    FROM_SOURCE_ID,
    SHARED_ENTITY_ID,
    TO_ATOM_ID,
    TO_SOURCE_ID,
)


def _place_connect_output(
    workspace: Path,
    *,
    inputs_hash: str,
    proposed_relations: list[dict[str, Any]],
) -> Path:
    """Plant a Connector ``output.yaml`` mimicking what the harness would emit.

    Standing in for the dispatch driver: the driver moves a harness's
    stdout payload to ``dispatch/outputs/connect-<hash>/output.yaml``
    via :func:`amanuensis.dispatch.queue.move_to_outputs`. We write
    the same shape directly.
    """
    output_dir = workspace / "dispatch" / "outputs" / f"connect-{inputs_hash}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "output.yaml"
    payload = {"proposed_relations": proposed_relations}
    output_path.write_text(
        yaml.safe_dump(payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    return output_path


def _valid_candidate() -> dict[str, Any]:
    """A Connector candidate that satisfies the INV-15 happy-path fixture."""
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


# --- T5.4: smoke ------------------------------------------------------


def test_connector_dispatch_smoke_with_mock_harness(
    tmp_workspace_with_bilateral_resolutions: Path,
    role_attribution: RoleAttribution,
    fake_provenance: ProvenanceRecord,
) -> None:
    """End-to-end mock cycle: hand-placed Connector output → committed CrossDocRelation.

    The mock-harness equivalent is the direct write of a canned
    ``output.yaml``; no subprocess invocation is required. The
    reconciler's role-routing branch must pick the file up, route it
    to ``_process_connect_output``, build the typed record via
    ``_build_cross_doc_relation``, and persist it.
    """
    workspace = tmp_workspace_with_bilateral_resolutions
    sub = Substrate(workspace)
    # Pre-condition: no CrossDocRelation in the substrate.
    assert list(sub.list_cross_doc_relations()) == []

    inputs_hash = "smoketest" + "a" * 8
    output_path = _place_connect_output(
        workspace,
        inputs_hash=inputs_hash,
        proposed_relations=[_valid_candidate()],
    )
    assert output_path.is_file()

    # Drive the reconciler — the single public entry point for the
    # dispatch-outputs → substrate edge.
    result = reconcile_outputs(substrate=sub, workspace_root=workspace)

    # The candidate landed as a CrossDocRelation in the substrate.
    rels = list(sub.list_cross_doc_relations())
    assert len(rels) == 1, (
        f"expected exactly one CrossDocRelation; got {len(rels)}. errors={result.errors!r}"
    )
    assert rels[0].kind == "supports"
    assert rels[0].shared_entities == [SHARED_ENTITY_ID]
    assert rels[0].from_source_id == FROM_SOURCE_ID
    assert rels[0].to_source_id == TO_SOURCE_ID

    # The ReconcileResult reflects the commit.
    assert result.relations_committed == [rels[0].id]
    assert result.errors == [], f"unexpected reconcile errors: {result.errors!r}"

    # The PROV record landed in mappings/provenance/.
    prov_dir = workspace / "mappings" / "provenance"
    prov_files = list(prov_dir.glob("p-*.yaml"))
    assert prov_files, "expected at least one mappings-scope PROV record"

    # The output file moved into _consumed/ (idempotency contract).
    assert not output_path.is_file(), "output.yaml should be moved into _consumed/"
    consumed = workspace / "dispatch" / "outputs" / "_consumed" / f"connect-{inputs_hash}"
    assert (consumed / "output.yaml").is_file(), f"expected consumed file at {consumed}/output.yaml"

    # The mappings replay-log recorded the activity.
    replay_root = workspace / "mappings" / "replay-log"
    assert replay_root.is_dir(), "expected mappings replay-log dir to be created"
    replay_yaml_files: list[Path] = []
    for day_dir in replay_root.iterdir():
        if day_dir.is_dir():
            replay_yaml_files.extend(day_dir.glob("*.yaml"))
    assert replay_yaml_files, "expected at least one replay-log entry in mappings scope"

    # Sanity: unused argument silencer (the fixtures are required by
    # the conftest precondition setup even though this test reads
    # the substrate directly rather than building candidates with them).
    del role_attribution, fake_provenance


def test_connector_smoke_inv15_failure_raises_clarification(
    tmp_workspace_with_partial_resolutions: Path,
) -> None:
    """A Connector candidate failing INV-15 (via reconcile_outputs) raises a clarification.

    Mirrors ``test_inv15_failure_writes_resolution_ambiguous_clarification``
    in ``test_cross_doc_reconcile.py`` but exercises the full
    ``reconcile_outputs`` entry point rather than calling
    ``_build_cross_doc_relation`` directly. This proves the connect
    branch routes INV-15 rejections through the auto-raise helper.
    """
    workspace = tmp_workspace_with_partial_resolutions
    sub = Substrate(workspace)

    inputs_hash = "smoketestinv15"
    _place_connect_output(
        workspace,
        inputs_hash=inputs_hash,
        proposed_relations=[_valid_candidate()],
    )

    result = reconcile_outputs(substrate=sub, workspace_root=workspace)

    # No CrossDocRelation was committed (INV-15 rejected it).
    assert list(sub.list_cross_doc_relations()) == []
    assert result.relations_committed == []

    # A resolution-ambiguous clarification was filed under the
    # from-endpoint distillation.
    clar_dir = workspace / "distillations" / FROM_SOURCE_ID / "clarifications" / "open"
    assert clar_dir.is_dir(), f"expected open-clarifications dir at {clar_dir}"
    clar_files = [p for p in clar_dir.iterdir() if p.suffix == ".md"]
    assert len(clar_files) == 1, (
        f"expected exactly one open clarification; got {[p.name for p in clar_files]}"
    )

    # The clarification id was recorded in ReconcileResult.
    assert result.clarifications_raised, (
        "expected the connect-reconcile path to record the auto-raised "
        "clarification id in result.clarifications_raised"
    )


# --- Phase 2b cleanup-2: clarification id plumbed through return ------


def test_two_inv15_failures_in_one_drain_track_distinct_ids(
    tmp_workspace_with_partial_resolutions: Path,
) -> None:
    """Two candidates failing INV-15 under the same from_source record both clar ids.

    Regression for the mtime-scan bug: the old impl scanned
    ``clarifications/open/`` and picked the freshest ``c-*.md``, so two
    clusters writing under the same from_source in a single drain could
    each pick up the OTHER cluster's id (mtime granularity is 1s on
    macOS HFS+ → both files often share a timestamp). The cleanup-2 fix
    threads each ``Clarification.id`` back from ``_build_cross_doc_relation``
    so the reconciler records each id exactly once and correctly.

    Two distinct candidates → two distinct INV-15 rejections → two
    distinct clarifications on disk → both ids in
    ``result.clarifications_raised``.
    """
    workspace = tmp_workspace_with_partial_resolutions
    sub = Substrate(workspace)

    # Two candidates that differ in warrant so their auto-raised
    # clarifications hash to different ids. Both fail INV-15 because the
    # partial-resolutions fixture has no from-endpoint Resolution.
    candidate_a = _valid_candidate()
    candidate_b = {**_valid_candidate(), "warrant": "alternate warrant for second cluster"}

    inputs_hash = "twoclusters" + "a" * 8
    _place_connect_output(
        workspace,
        inputs_hash=inputs_hash,
        proposed_relations=[candidate_a, candidate_b],
    )

    result = reconcile_outputs(substrate=sub, workspace_root=workspace)

    # No CrossDocRelation committed (both rejected).
    assert list(sub.list_cross_doc_relations()) == []

    # Two clarification files on disk.
    clar_dir = workspace / "distillations" / FROM_SOURCE_ID / "clarifications" / "open"
    on_disk = sorted(p.stem for p in clar_dir.iterdir() if p.suffix == ".md")
    assert len(on_disk) == 2, f"expected two clarifications on disk; got {on_disk}"

    # Both clarification ids must be in ReconcileResult and each must be
    # one of the on-disk ids. The set equality is the cleanup-2 contract:
    # no spurious id, no missed id, no duplicate.
    assert sorted(result.clarifications_raised) == on_disk


def test_build_cross_doc_relation_returns_clarification_id_on_inv15(
    tmp_workspace_with_partial_resolutions: Path,
    role_attribution: RoleAttribution,
    fake_provenance: ProvenanceRecord,
) -> None:
    """Cleanup-2 contract: ``_build_cross_doc_relation`` returns the clar id on INV-15.

    The helper used to return ``None`` on the auto-raise path, forcing
    the reconciler to mtime-scan ``clarifications/open/`` to recover
    the id. Post-cleanup-2 the helper returns a ``BuildResult`` with the
    clarification id populated, eliminating the brittle scan.
    """
    from amanuensis.dispatch.reconcile import _build_cross_doc_relation

    sub = Substrate(tmp_workspace_with_partial_resolutions)

    build = _build_cross_doc_relation(
        _valid_candidate(),
        sub,
        fake_provenance,
        role_attributions=[role_attribution],
    )
    assert build.cross_doc_relation is None
    assert build.clarification_id is not None
    assert build.clarification_id.startswith("c-")

    # The id must match the file that landed on disk.
    clar_dir = (
        tmp_workspace_with_partial_resolutions
        / "distillations"
        / FROM_SOURCE_ID
        / "clarifications"
        / "open"
    )
    on_disk = [p.stem for p in clar_dir.iterdir() if p.suffix == ".md"]
    assert build.clarification_id in on_disk
