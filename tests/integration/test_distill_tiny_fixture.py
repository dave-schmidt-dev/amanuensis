"""M7.5 — full pipeline integration test on a tiny PDF fixture.

Exercises ingest → reconcile end-to-end against the bundled M3.1 fixture
(``tests/fixtures/ingest/simple-contract.pdf``) without invoking the real
dispatch driver. The dispatch step is mocked by writing a synthesized
role-output YAML directly under
``<workspace>/dispatch/outputs/<role>-<hash>/output.yaml`` — the actual
LLM call is not testable in CI.

Two test functions:

- ``test_distill_pipeline_tiny_fixture_happy_path`` — ingest a real PDF
  using the bundled generic vocabulary; synthesize a single valid
  extractor output (predicate ``asserts_obligation``, drawn from the
  vendored ``vocabularies/generic/predicates.yaml``); run reconcile; then
  verify the substrate side-effects PLUS that every M2 validator passes
  on the produced atom (the "all M2 gate tests pass on the produced
  substrate" criterion from the M7.5 plan).

- ``test_auditor_contested_warrant_raises_clarification`` — covers the
  CR-7 e2e variant: an auditor output whose ``rejected_atoms`` entry
  carries ``warrant_defensibility: contested`` raises a
  ``warrant-defensibility-contested`` clarification on the substrate.

Fixture choice
--------------
We reuse the M3.1 fixture (``tests/fixtures/ingest/simple-contract.pdf``)
rather than building a new tiny PDF. The M7.5 plan explicitly allows
this and notes it as faster + equally valid for an integration test —
the fixture's identity does not matter, only that the pipeline produces
a sensible source-mirror substrate. The fixture is already documented
under ``tests/fixtures/ingest/SOURCES.md``.

Vocabulary choice
-----------------
We use the bundled vendored vocabulary at
``vocabularies/generic/predicates.yaml`` (loaded via
``amanuensis.vocabulary.registry.load_vocabulary``) so the predicate
``asserts_obligation`` resolves through the same closed-vocabulary path
production code uses. The ingest pipeline pins this vocabulary as the
per-distillation snapshot, and reconcile's ``closed_vocabulary``
validator reads that snapshot back — exactly the INV-10 lifecycle the
M2 gate tests cover, but here exercised end-to-end.

inputs_hash judgement call
--------------------------
The synthesized output file lives at
``dispatch/outputs/extractor-<inputs_hash>/output.yaml``. In production
the inputs_hash is computed by ``amanuensis.cli.distill._compute_inputs_hash``
from (role, prompt, inputs, model_id). For this test we use a fixed
64-character sentinel hash — reconcile only treats ``inputs_hash`` as an
opaque cross-reference string (it goes into the PROV record's
``was_influenced_by``); the gate's behaviour does NOT depend on it
matching any real cache key. A sentinel keeps the test hermetic and
avoids coupling to the private ``_compute_inputs_hash`` helper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import Substrate
from amanuensis.ingest import ingest_pdf
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    Vocabulary,
)
from amanuensis.validators import (
    ValidationResult,
    citation_ledger,
    closed_vocabulary,
    provenance_completeness,
    scale_anchor,
    schema_check,
    universe_check,
)
from amanuensis.vocabulary.registry import load_vocabulary

# --- Shared paths ------------------------------------------------------

FIXTURE_PDF: Path = Path(__file__).parent.parent / "fixtures" / "ingest" / "simple-contract.pdf"
VOCAB_YAML: Path = (
    Path(__file__).parent.parent.parent / "vocabularies" / "generic" / "predicates.yaml"
)

SOURCE_ID = "m75-tiny-fixture"

# A 64-character sentinel inputs_hash. The reconcile gate only uses this
# as an opaque cross-reference (see module docstring's "inputs_hash
# judgement call").
SENTINEL_INPUTS_HASH = "f" * 64


# --- Helpers -----------------------------------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    """Plant the INV-1 marker so Substrate / acquire_workspace_lock accept it."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: m75-integration-test\n",
        encoding="utf-8",
    )
    return tmp_path


def _load_generic_vocabulary() -> Vocabulary:
    """Load the vendored generic predicate vocabulary."""
    return load_vocabulary(VOCAB_YAML)


def _extractor_agent() -> AgentAttribution:
    return AgentAttribution(
        kind="llm",
        identifier="claude-opus-4-7",
        role="extractor",
    )


def _valid_extractor_atom_payload(source_id: str) -> dict[str, Any]:
    """A single atom that passes every M2 validator against the snapshot.

    - ``predicate`` is ``asserts_obligation`` (resolves in the bundled
      vocabulary; M2.1 confirmed it).
    - ``section_path`` is non-empty (``citation_ledger`` requires it).
    - ``char_span`` has ``0 <= start < end``.
    - ``scale_anchor`` is in the INV-6 closed set.
    """
    return {
        "source_id": source_id,
        "section_path": ["Part I", "§1"],
        "paragraph_index": 0,
        "char_span": [0, 42],
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [
            {
                "role": "obligor",
                "kind": "entity",
                "value": "ent-acme-corp",
                "type_hint": None,
            },
        ],
        "narrative": "ACME shall deliver widgets by 2024-01-15.",
        "qualifier_level": None,
        "qualifier_basis": None,
    }


def _write_role_output(
    workspace: Path,
    *,
    role: str,
    inputs_hash: str,
    payload: dict[str, Any],
) -> Path:
    """Drop a synthesized ``<role>-<hash>/output.yaml`` under dispatch/outputs/."""
    out_dir = workspace / "dispatch" / "outputs" / f"{role}-{inputs_hash}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "output.yaml"
    out_path.write_text(
        yaml.safe_dump(payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    return out_path


def _run_all_atom_validators(
    atom: Atom,
    *,
    substrate: Substrate,
    known_source_ids: set[str],
    vocabulary: Vocabulary,
) -> list[ValidationResult]:
    """Run every M2 atom-side validator and return their results.

    Parametrizing over the validator names per the M7.5 plan: this is the
    "all M2 gate tests pass on the produced substrate" check. Each
    validator has a different signature (some need a substrate handle,
    some a vocabulary), so we materialise the call list locally rather
    than dispatching via a string.
    """
    return [
        schema_check(atom, model_class=Atom),
        citation_ledger(atom),
        universe_check(atom, known_source_ids=known_source_ids),
        scale_anchor(atom),
        provenance_completeness(atom, substrate=substrate),
        closed_vocabulary(atom, vocabulary=vocabulary),
    ]


# --- Test 1: happy-path full pipeline ----------------------------------


def test_distill_pipeline_tiny_fixture_happy_path(tmp_path: Path) -> None:
    """Ingest → synthesize extractor output → reconcile → atom committed + valid.

    The "tiny fixture" is the M3.1 fixture
    (``tests/fixtures/ingest/simple-contract.pdf``) — reused per the
    M7.5 plan's explicit allowance. The full Phase 1 pipeline is
    exercised end-to-end with the only short-cut being the dispatch
    driver (we write the role output directly, since real harness CLIs
    are not testable in CI).
    """
    # --- 1. Setup workspace + Substrate.
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    vocabulary = _load_generic_vocabulary()
    agent = _extractor_agent()

    # --- 2. Ingest the tiny PDF. This writes:
    #       distillations/<src>/source-mirror/manifest.yaml,
    #       distillations/<src>/source-mirror/paragraphs/p-*.md,
    #       distillations/<src>/vocabulary-snapshot.yaml,
    #       distillations/<src>/provenance/<prov>.yaml.
    manifest = ingest_pdf(
        substrate=substrate,
        source_id=SOURCE_ID,
        pdf_path=FIXTURE_PDF,
        vocabulary=vocabulary,
        agent_attribution=agent,
    )
    manifest_path = substrate.manifest_path(SOURCE_ID)
    assert manifest_path.is_file(), f"source-mirror manifest missing after ingest: {manifest_path}"
    assert manifest.source_id == SOURCE_ID

    # --- 3. Skip the `distill` enqueue + `dispatch` invocation: write a
    #       synthesized extractor output directly. This mirrors what a
    #       real dispatch driver would have landed after invoking the
    #       extractor harness.
    out_path = _write_role_output(
        workspace,
        role="extractor",
        inputs_hash=SENTINEL_INPUTS_HASH,
        payload={
            "proposed_atoms": [_valid_extractor_atom_payload(SOURCE_ID)],
            "proposed_relations": [],
        },
    )

    # --- 4. Run reconcile. Should commit the one atom + write its PROV
    #       record + move the output file under _consumed/.
    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert result.errors == [], f"reconcile reported errors: {result.errors!r}"
    assert len(result.atoms_committed) == 1, (
        f"expected 1 atom committed, got {result.atoms_committed!r}; "
        f"clarifications={result.clarifications_raised!r}"
    )
    assert result.clarifications_raised == [], (
        f"unexpected clarifications raised: {result.clarifications_raised!r}"
    )

    atom_id = result.atoms_committed[0]
    assert atom_id.startswith("a-"), f"unexpected atom id shape: {atom_id!r}"

    # --- 5. Atom file exists at the canonical path.
    atom_path = substrate.atom_path(SOURCE_ID, atom_id)
    assert atom_path.is_file(), f"atom file missing at {atom_path}"

    # --- 6. The corresponding PROV record exists and names the atom.
    atom = substrate.get_atom(SOURCE_ID, atom_id)
    prov = substrate.get_provenance(SOURCE_ID, atom.provenance_id)
    assert prov.entity_id == atom_id, (
        f"PROV record entity_id={prov.entity_id!r} does not match atom_id={atom_id!r}"
    )
    assert prov.entity_type == "atom"

    # --- 7. The output file moved under _consumed/ (idempotency anchor).
    assert not out_path.exists(), "original output.yaml should have been moved"
    consumed_path = (
        workspace
        / "dispatch"
        / "outputs"
        / "_consumed"
        / f"extractor-{SENTINEL_INPUTS_HASH}"
        / "output.yaml"
    )
    assert consumed_path.is_file(), f"output not moved to _consumed/: {consumed_path}"
    assert result.outputs_consumed == [consumed_path]

    # --- 8. M7.5 "all M2 gate tests pass on the produced substrate".
    #       Run every atom-side validator on every atom on the substrate
    #       and assert every result passed. The snapshot vocabulary is
    #       loaded from the per-distillation pin (INV-10), matching what
    #       reconcile itself uses internally.
    snapshot_vocab = substrate.get_vocabulary_snapshot(SOURCE_ID)
    known_source_ids = {SOURCE_ID}
    all_atoms = list(substrate.list_atoms(SOURCE_ID))
    assert all_atoms, "expected at least one atom on the substrate"

    for committed_atom in all_atoms:
        results = _run_all_atom_validators(
            committed_atom,
            substrate=substrate,
            known_source_ids=known_source_ids,
            vocabulary=snapshot_vocab,
        )
        failures = [r for r in results if not r.passed]
        assert not failures, (
            f"M2 validators failed on committed atom {committed_atom.id!r}: "
            f"{[(f.validator, f.reason) for f in failures]!r}"
        )


# --- Test 2: CR-7 auditor-contested rejection raises clarification -----


def test_auditor_contested_warrant_raises_clarification(tmp_path: Path) -> None:
    """An auditor ``rejected_atoms`` entry with ``warrant_defensibility: contested``
    raises a CR-7 warrant-defensibility-contested clarification.

    This is the auditor-side variant of CR-7 (the extractor-relation
    variant is covered by tests/dispatch/test_contested_warrant_clarification.py;
    here we cover the auditor surface end-to-end on the same tiny
    substrate produced by the M3.1 ingest pipeline).
    """
    # --- 1. Setup workspace + ingest the tiny PDF so the distillation
    #       directory exists (auditor outputs file clarifications under
    #       it).
    workspace = _make_workspace(tmp_path)
    substrate = Substrate(workspace)
    vocabulary = _load_generic_vocabulary()
    agent = _extractor_agent()

    ingest_pdf(
        substrate=substrate,
        source_id=SOURCE_ID,
        pdf_path=FIXTURE_PDF,
        vocabulary=vocabulary,
        agent_attribution=agent,
    )

    # --- 2. Synthesize an auditor output that rejects an atom on
    #       warrant-defensibility grounds. The ``atom_id`` it cites does
    #       not need to be a real on-substrate atom — the auditor surface
    #       records the reference verbatim into context_refs and raises
    #       the clarification regardless of whether the atom committed.
    contested_atom_ref = "a-contested-placeholder"
    auditor_payload: dict[str, Any] = {
        "source_id": SOURCE_ID,
        "rejected_atoms": [
            {
                "source_id": SOURCE_ID,
                "atom_id": contested_atom_ref,
                "reason": "warrant for this obligation chain is contested.",
                "warrant_defensibility": "contested",
            },
        ],
    }
    _write_role_output(
        workspace,
        role="auditor",
        inputs_hash=SENTINEL_INPUTS_HASH,
        payload=auditor_payload,
    )

    # --- 3. Run reconcile; expect exactly one warrant-defensibility-contested
    #       clarification (and no atoms/relations committed).
    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert result.errors == [], f"reconcile reported errors: {result.errors!r}"
    assert result.atoms_committed == [], (
        f"auditor path must not commit atoms; got {result.atoms_committed!r}"
    )
    assert result.relations_committed == [], (
        f"auditor path must not commit relations; got {result.relations_committed!r}"
    )
    assert len(result.clarifications_raised) == 1, (
        f"expected 1 clarification, got {result.clarifications_raised!r}"
    )

    # --- 4. The clarification on disk is the warrant-defensibility-contested
    #       variant, references the contested atom, and the question text
    #       mentions "contested".
    from amanuensis.fs._serialize import parse_clarification_md

    clar_id = result.clarifications_raised[0]
    clar_path = substrate.clarification_path(SOURCE_ID, clar_id, resolved=False)
    assert clar_path.is_file(), f"clarification not on disk: {clar_path}"
    clar = parse_clarification_md(clar_path.read_text(encoding="utf-8"))
    assert clar.raised_by_activity == "warrant-defensibility-contested", (
        f"expected raised_by_activity 'warrant-defensibility-contested', "
        f"got {clar.raised_by_activity!r}"
    )
    assert contested_atom_ref in clar.context_refs, (
        f"context_refs {clar.context_refs!r} should include the contested atom ref"
    )
    assert "contested" in clar.question.lower(), (
        f"question should mention contested status: {clar.question!r}"
    )

    # --- 5. The output file moved under _consumed/.
    consumed_path = (
        workspace
        / "dispatch"
        / "outputs"
        / "_consumed"
        / f"auditor-{SENTINEL_INPUTS_HASH}"
        / "output.yaml"
    )
    assert consumed_path.is_file(), f"auditor output not moved to _consumed/: {consumed_path}"


# --- Module-level sanity: the fixture and vocabulary actually exist ----


def test_fixtures_exist() -> None:
    """Guard: the integration tests depend on the M3.1 fixture + vocab."""
    if not FIXTURE_PDF.is_file():
        pytest.fail(
            f"M3.1 fixture missing at {FIXTURE_PDF}; the integration tests "
            "reuse it (see module docstring)."
        )
    if not VOCAB_YAML.is_file():
        pytest.fail(
            f"vendored generic vocabulary missing at {VOCAB_YAML}; the "
            "integration tests rely on it to pin a snapshot at ingest."
        )
