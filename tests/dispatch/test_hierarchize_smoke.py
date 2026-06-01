# pyright: reportPrivateUsage=false, reportUntypedFunctionDecorator=false
"""Smoke test: Hierarchize dispatch reconcile cycle with a mocked harness.

Phase 2c M7/T7.4. Mirrors the Phase 2b connect-role smoke test at
``tests/dispatch/test_connect_smoke.py``. The Hierarchize role's full
dispatch pipeline is:

    orchestrator (future) -> dispatch queue -> driver -> harness
    -> output.yaml -> reconciler -> Probandum + ProbandumEdge in substrate

M7 wires the reconciler half (the output.yaml -> substrate edge). The
orchestrator's cluster-enumeration logic is a later milestone. This
smoke test therefore short-circuits the upper half: it hand-places a
Hierarchize ``output.yaml`` under
``dispatch/outputs/hierarchize-<hash>/`` and calls
:func:`reconcile_outputs` directly.

What this test proves:

- ``_process_hierarchize_output`` is reachable from
  ``reconcile_outputs`` (the role-routing branch is wired correctly).
- A well-formed candidate batch (1 interim probandum + 2 edges)
  round-trips to committed records in ``mappings/probanda/`` and
  ``mappings/probandum-edges/``.
- The PROV record lands in ``mappings/provenance/`` and the consumed
  output file moves into the ``_consumed/`` subtree (idempotency).
- The mappings-scope replay-log records the activity with
  ``actor_role="hierarchize"``.
- An unknown Walton scheme drops the offending interim probandum and
  raises a ``scheme-missing`` Clarification (INV-18 rejection path).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text  # pyright: ignore[reportPrivateUsage]
from amanuensis.fs._serialize import serialize_atom_md  # pyright: ignore[reportPrivateUsage]
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    OperandRef,
    Probandum,
    ProbandumEdge,
    RoleAttribution,
    compute_id,
)

# Stable attribution timestamp; pinned so content-addressable ids that
# embed RoleAttribution.at stay deterministic across runs.
_STABLE_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


# --- Fixtures local to T7.4 -------------------------------------------


@pytest.fixture
def hierarchize_role_attribution() -> RoleAttribution:
    """Stable RoleAttribution stamping the planted probanda."""
    return RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="claude-opus-4-7", role="hierarchize"),
        activity="proposed",
        at=_STABLE_AT,
    )


@pytest.fixture
def tmp_hierarchize_workspace(
    tmp_workspace: Path,
    hierarchize_role_attribution: RoleAttribution,
) -> tuple[Path, str, str]:
    """Workspace with Walton snapshot + ultimate + penultimate probanda.

    Returns ``(workspace, ultimate_id, penultimate_id)`` so the smoke
    test can reference real substrate ids when planting the Hierarchize
    output payload. The penultimate already traces upward to the
    ultimate via a planted ``ProbandumEdge``, so the INV-17 lineage
    gate is satisfied for any further edges anchored at the penultimate.
    """
    sub = Substrate(tmp_workspace)
    sub.snapshot_walton_schemes()
    # Plant a distillation so Phase 2c clarifications have a real source
    # to file under (rather than the _mappings sentinel).
    (tmp_workspace / "distillations" / "src-A").mkdir(parents=True, exist_ok=True)

    # Plant a concrete atom in src-A so probandum-edges with
    # child_kind="atom" can reference it (the substrate validates atom
    # existence on edge write per the M2 child-existence gate).
    atom = Atom(
        id="a-fixture00000001",
        source_id="src-A",
        section_path=["body"],
        paragraph_index=0,
        sentence_index=None,
        char_span=(0, 40),
        scale_anchor="paragraph",
        kind="claim",
        predicate="failed_to_perform",
        operands=[
            OperandRef(role="subject", kind="entity", value="e-smith", type_hint=None),
        ],
        narrative="Smith failed to deliver the April 2024 shipment.",
        qualifier_level=None,
        qualifier_basis=None,
        provenance_id="p-fixture00000099",
        role_attributions=[hierarchize_role_attribution],
        schema_version=1,
    )
    atom_path = tmp_workspace / "distillations" / "src-A" / "atoms" / f"{atom.id}.md"
    atomic_write_text(atom_path, serialize_atom_md(atom))

    ultimate_draft = Probandum(
        id="p-placeholder",
        statement="ACME prevails on its breach claim against Smith.",
        kind="ultimate",
        scheme="argument-from-expert-opinion",
        alternatives_considered=[],
        confidence="high",
        provenance_id="p-fixture00000099",
        role_attributions=[hierarchize_role_attribution],
        schema_version=1,
    )
    ultimate = ultimate_draft.model_copy(update={"id": compute_id(ultimate_draft)})
    sub.add_probandum(ultimate)

    penultimate_draft = Probandum(
        id="p-placeholder",
        statement="Smith breached the 2018 contract under §3.",
        kind="penultimate",
        scheme="argument-from-sign",
        alternatives_considered=[
            "Smith performed under §3 but ACME alleged non-conforming tender.",
            "The §3 obligation was waived or modified by parol agreement.",
        ],
        confidence="high",
        provenance_id="p-fixture00000099",
        role_attributions=[hierarchize_role_attribution],
        schema_version=1,
    )
    penultimate = penultimate_draft.model_copy(update={"id": compute_id(penultimate_draft)})
    sub.add_probandum(penultimate)

    # Linking edge ultimate -> penultimate so the penultimate's lineage
    # reaches an ultimate (INV-17 precondition for further edges).
    linking_edge_draft = ProbandumEdge(
        id="q-placeholder",
        parent_probandum_id=ultimate.id,
        child_id=penultimate.id,
        child_kind="probandum",
        child_source_id=None,
        kind="supports",
        warrant="Penultimate decomposes the ultimate's legal conclusion.",
        warrant_defensibility="methodology-derived",
        warrant_basis="Wigmore §III argument-tree decomposition.",
        confidence="high",
        provenance_id="p-fixture00000099",
        role_attributions=[hierarchize_role_attribution],
        schema_version=1,
    )
    linking_edge = linking_edge_draft.model_copy(update={"id": compute_id(linking_edge_draft)})
    sub.add_probandum_edge(linking_edge)
    return tmp_workspace, ultimate.id, penultimate.id


def _place_hierarchize_output(
    workspace: Path,
    *,
    inputs_hash: str,
    interim_probanda: list[dict[str, Any]],
    probandum_edges: list[dict[str, Any]],
) -> Path:
    """Plant a Hierarchize ``output.yaml`` mimicking what the harness would emit."""
    output_dir = workspace / "dispatch" / "outputs" / f"hierarchize-{inputs_hash}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "output.yaml"
    payload = {
        "interim_probanda": interim_probanda,
        "probandum_edges": probandum_edges,
    }
    output_path.write_text(
        yaml.safe_dump(payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    return output_path


# --- T7.4: smoke -------------------------------------------------------


def test_hierarchize_dispatch_smoke_happy_path(
    tmp_hierarchize_workspace: tuple[Path, str, str],
) -> None:
    """End-to-end mock cycle: hand-placed output -> committed interim + edges.

    The mock-harness equivalent is the direct write of a canned
    ``output.yaml``; no subprocess invocation is required. The
    reconciler's role-routing branch must pick the file up, route it
    to ``_process_hierarchize_output``, build the typed records via
    ``_build_probandum`` and ``_build_probandum_edge``, resolve any
    ``<index>`` references in the edges (here we use a real penultimate
    id for parent and an index for the child's atom-equivalent), and
    persist the lot.
    """
    workspace, _ultimate_id, penultimate_id = tmp_hierarchize_workspace
    sub = Substrate(workspace)
    # Pre-condition: exactly the 2 planted probanda and 1 planted edge.
    assert len(list(sub.list_probanda())) == 2
    assert len(list(sub.list_probandum_edges())) == 1

    inputs_hash = "smoketest" + "a" * 8
    interim_probanda = [
        {
            "statement": "Smith failed to deliver the April 2024 shipment required by §3.",
            "kind": "interim",
            "scheme": "argument-from-sign",
            "alternatives_considered": [
                "Smith tendered but ACME rejected for unrelated quality reasons.",
                "Smith and ACME mutually deferred the April 2024 delivery.",
            ],
            "confidence": "high",
        }
    ]
    probandum_edges = [
        # Edge 1: penultimate (real id) -> interim (index "0")
        {
            "parent_probandum_id": penultimate_id,
            "child_id": "0",  # index reference into interim_probanda
            "child_kind": "probandum",
            "child_source_id": None,
            "kind": "supports",
            "warrant": (
                "The §3 obligation maps to a concrete April 2024 delivery; "
                "if Smith failed to deliver on that date, the §3 obligation "
                "was breached."
            ),
            "warrant_defensibility": "methodology-derived",
            "warrant_basis": (
                "Standard contract-law mapping from a specific performance "
                "obligation to its breach."
            ),
            "confidence": "high",
        },
        # Edge 2: interim (index "0") -> a concrete atom (synthetic id)
        {
            "parent_probandum_id": "0",
            "child_id": "a-fixture00000001",
            "child_kind": "atom",
            "child_source_id": "src-A",
            "kind": "supports",
            "warrant": (
                "The atom directly attests the missed delivery. "
                "Independent corroboration is documented in the source."
            ),
            "warrant_defensibility": "literature-backed",
            "warrant_basis": "Direct attestation in the source narrative.",
            "confidence": "high",
        },
    ]
    output_path = _place_hierarchize_output(
        workspace,
        inputs_hash=inputs_hash,
        interim_probanda=interim_probanda,
        probandum_edges=probandum_edges,
    )
    assert output_path.is_file()

    result = reconcile_outputs(substrate=sub, workspace_root=workspace)

    # No reconcile errors.
    assert result.errors == [], f"unexpected reconcile errors: {result.errors!r}"
    # No clarifications raised (happy path).
    assert result.clarifications_raised == [], (
        f"unexpected clarifications: {result.clarifications_raised!r}"
    )

    # The interim probandum landed in mappings/probanda/.
    probanda = list(sub.list_probanda())
    assert len(probanda) == 3, (
        f"expected 3 probanda (2 planted + 1 new interim); got {len(probanda)}"
    )
    new_interim = [p for p in probanda if p.kind == "interim"]
    assert len(new_interim) == 1
    assert new_interim[0].statement.startswith("Smith failed to deliver the April 2024")
    assert new_interim[0].scheme == "argument-from-sign"

    # Both edges landed in mappings/probandum-edges/.
    edges = list(sub.list_probandum_edges())
    assert len(edges) == 3, f"expected 3 edges (1 planted linking + 2 new); got {len(edges)}"

    # One of the new edges goes penultimate -> interim; the other goes
    # interim -> atom. Both reference the just-written interim probandum.
    interim_id = new_interim[0].id
    edge_pen_to_interim = [
        e for e in edges if e.parent_probandum_id == penultimate_id and e.child_id == interim_id
    ]
    assert len(edge_pen_to_interim) == 1, (
        f"expected one penultimate->interim edge; got {edge_pen_to_interim!r}"
    )
    edge_interim_to_atom = [
        e for e in edges if e.parent_probandum_id == interim_id and e.child_kind == "atom"
    ]
    assert len(edge_interim_to_atom) == 1, (
        f"expected one interim->atom edge; got {edge_interim_to_atom!r}"
    )
    assert edge_interim_to_atom[0].child_id == "a-fixture00000001"
    assert edge_interim_to_atom[0].child_source_id == "src-A"

    # The PROV record landed in mappings/provenance/.
    prov_dir = workspace / "mappings" / "provenance"
    prov_files = list(prov_dir.glob("p-*.yaml"))
    assert prov_files, "expected at least one mappings-scope PROV record"

    # The output file moved into _consumed/ (idempotency contract).
    assert not output_path.is_file(), "output.yaml should be moved into _consumed/"
    consumed = workspace / "dispatch" / "outputs" / "_consumed" / f"hierarchize-{inputs_hash}"
    assert (consumed / "output.yaml").is_file(), f"expected consumed file at {consumed}/output.yaml"

    # The mappings replay-log recorded the activity.
    replay_root = workspace / "mappings" / "replay-log"
    assert replay_root.is_dir(), "expected mappings replay-log dir to be created"
    replay_yaml_files: list[Path] = []
    for day_dir in replay_root.iterdir():
        if day_dir.is_dir():
            replay_yaml_files.extend(day_dir.glob("*.yaml"))
    assert replay_yaml_files, "expected at least one replay-log entry in mappings scope"
    # Sanity: the most recent replay entry references the hierarchize activity.
    recent = sorted(replay_yaml_files, key=lambda p: p.stat().st_mtime)[-1]
    recent_text = recent.read_text(encoding="utf-8")
    assert "hierarchize" in recent_text, (
        f"expected replay-log entry to reference 'hierarchize'; got:\n{recent_text}"
    )


def test_hierarchize_smoke_scheme_missing_rejection(
    tmp_hierarchize_workspace: tuple[Path, str, str],
) -> None:
    """An interim probandum with an unknown Walton scheme is dropped.

    Mirrors the Phase 2b ``test_connector_smoke_inv15_failure_raises_clarification``
    pattern: the reconciler routes the rejection through the auto-raise
    helper, the offending interim does NOT land in the substrate, and
    a ``scheme-missing`` clarification appears under the first
    distillation.
    """
    workspace, _, penultimate_id = tmp_hierarchize_workspace
    sub = Substrate(workspace)
    pre_count_probanda = len(list(sub.list_probanda()))

    inputs_hash = "smoketestscheme"
    interim_probanda = [
        {
            "statement": "Smith violated a fabricated obligation.",
            "kind": "interim",
            "scheme": "argument-from-pure-fabrication",  # not in snapshot
            "alternatives_considered": ["Some realistic alternative."],
            "confidence": "low",
        }
    ]
    # An edge referencing the rejected interim by index. Since the
    # interim never lands, the edge's parent reference cannot be
    # resolved at second-pass time, so the edge build will fail too —
    # but that's not what this test asserts. We assert ONLY on the
    # scheme-missing path here; the edge's downstream fate is incidental.
    probandum_edges: list[dict[str, Any]] = [
        {
            "parent_probandum_id": penultimate_id,
            "child_id": "0",
            "child_kind": "probandum",
            "child_source_id": None,
            "kind": "supports",
            "warrant": "Decomposition warrant.",
            "warrant_defensibility": "conventional",
            "warrant_basis": "Wigmore §III decomposition.",
            "confidence": "low",
        }
    ]
    _place_hierarchize_output(
        workspace,
        inputs_hash=inputs_hash,
        interim_probanda=interim_probanda,
        probandum_edges=probandum_edges,
    )

    result = reconcile_outputs(substrate=sub, workspace_root=workspace)

    # The interim did NOT land in the substrate.
    post_probanda = list(sub.list_probanda())
    interim_count = len([p for p in post_probanda if p.kind == "interim"])
    assert interim_count == 0, f"expected zero new interim probanda; got {interim_count}"
    assert len(post_probanda) == pre_count_probanda, (
        f"probanda count changed (expected stable); got {len(post_probanda)}"
    )

    # A scheme-missing clarification was raised under the first distillation.
    open_clar_dir = workspace / "distillations" / "src-A" / "clarifications" / "open"
    assert open_clar_dir.is_dir(), f"expected open clarifications dir at {open_clar_dir}"
    clar_files = [p for p in open_clar_dir.iterdir() if p.suffix == ".md"]
    assert clar_files, "expected at least one open clarification on disk"
    # The reconciler recorded the clarification id in its result.
    assert result.clarifications_raised, (
        "expected the hierarchize-reconcile path to record the "
        "auto-raised clarification id in result.clarifications_raised"
    )


# --- Phase 2c cleanup: clarification id plumbed through return --------


def test_two_scheme_missing_failures_in_one_drain_track_distinct_ids(
    tmp_hierarchize_workspace: tuple[Path, str, str],
) -> None:
    """Two interim probanda failing INV-18 in one drain record both clar ids.

    Regression for the mtime-scan bug parallel to Phase 2b cleanup-2's
    ``test_two_inv15_failures_in_one_drain_track_distinct_ids``: the
    pre-cleanup impl scanned ``clarifications/open/`` and returned the
    freshest ``c-*.md`` of the requested kind. When two scheme-missing
    rejections in one drain landed in the same filesystem mtime tick
    (1s precision on macOS HFS+), both could resolve to the SAME id —
    losing one raise and double-counting the other. The Phase 2c
    cleanup threads each ``Clarification.id`` back from
    :func:`_build_probandum` so the reconciler records each id exactly
    once and correctly.

    Two distinct interim probanda → two distinct INV-18 rejections →
    two distinct clarifications on disk → both ids in
    ``result.clarifications_raised``.

    Note on race coverage: we do NOT call ``os.utime`` to force the
    same mtime — on a fast machine both files often land in the same
    tick naturally. The test is a regression-against-the-bug-returning
    rather than a guaranteed-fail-before-fix: post-cleanup the
    plumbed-id contract makes filesystem mtimes irrelevant.
    """
    workspace, _, _penultimate_id = tmp_hierarchize_workspace
    sub = Substrate(workspace)
    pre_count_probanda = len(list(sub.list_probanda()))

    inputs_hash = "twoschememissing" + "a" * 8
    # Two interim probanda with different statements so the auto-raised
    # clarifications hash to different ids (the clarification's
    # context_refs carries the probandum id + statement excerpt; both
    # diverge between the two candidates).
    interim_probanda = [
        {
            "statement": "Smith violated fabricated obligation alpha.",
            "kind": "interim",
            "scheme": "argument-from-pure-fabrication",  # not in snapshot
            "alternatives_considered": ["Alpha alternative."],
            "confidence": "low",
        },
        {
            "statement": "Smith violated fabricated obligation beta.",
            "kind": "interim",
            "scheme": "argument-from-different-fabrication",  # also not in snapshot
            "alternatives_considered": ["Beta alternative."],
            "confidence": "low",
        },
    ]
    # No edges — this test isolates the scheme-missing path.
    probandum_edges: list[dict[str, Any]] = []
    _place_hierarchize_output(
        workspace,
        inputs_hash=inputs_hash,
        interim_probanda=interim_probanda,
        probandum_edges=probandum_edges,
    )

    result = reconcile_outputs(substrate=sub, workspace_root=workspace)

    # Neither interim landed in the substrate.
    post_probanda = list(sub.list_probanda())
    assert len(post_probanda) == pre_count_probanda, (
        f"probanda count changed (expected stable); got {len(post_probanda)}"
    )

    # Two clarification files on disk under src-A's open queue.
    clar_dir = workspace / "distillations" / "src-A" / "clarifications" / "open"
    on_disk = sorted(p.stem for p in clar_dir.iterdir() if p.suffix == ".md")
    assert len(on_disk) == 2, f"expected two clarifications on disk; got {on_disk}"

    # Both clarification ids must be in ReconcileResult and each must be
    # one of the on-disk ids. The set equality is the cleanup contract:
    # no spurious id, no missed id, no duplicate.
    assert sorted(result.clarifications_raised) == on_disk
    # Same contract on the hierarchize-only counter.
    assert sorted(result.hierarchize_clarifications_raised) == on_disk
