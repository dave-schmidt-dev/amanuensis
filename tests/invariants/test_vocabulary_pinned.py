"""Gate test for INV-10 (Vocabulary is pinned per distillation).

Quoting INVARIANTS.md INV-10 verbatim:

    On ingest, the active vocabulary registry is snapshotted into
    distillations/<source-id>/vocabulary-snapshot.yaml (content-addressed;
    snapshot hash recorded in source-mirror/manifest.yaml). All
    validators read the per-distillation snapshot, never the global
    ~/.amanuensis/vocabularies/ registry. The global registry is a
    starting template, not a runtime dependency.

What this gate certifies
------------------------
- Every distillation has its own vocabulary snapshot file.
- Once written, the snapshot for distillation A is independent of any
  subsequent registry edits or of snapshots written for distillation B.
- A distillation without a snapshot raises ``SubstrateNotFound`` from
  ``get_vocabulary_snapshot`` — the INV-10 violation signal an auditor
  would surface.
- After M3.1 ingest, the manifest's recorded
  ``vocabulary_snapshot_sha256`` equals the on-disk snapshot's SHA-256.
  This is the manifest-hash link INV-10 was deferring until M3.1 landed
  the source-mirror manifest file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from amanuensis.fs import Substrate, SubstrateNotFound, SubstrateSnapshotCorrupt
from amanuensis.ingest import ingest_pdf
from amanuensis.schemas import (
    AgentAttribution,
    OperandTypeSchema,
    SourceMirrorManifest,
    Vocabulary,
    VocabularyEntry,
)
from tests.invariants._types import MatchedAtomFactory

_INGEST_FIXTURE_PDF = Path(__file__).parent.parent / "fixtures" / "ingest" / "simple-contract.pdf"

SOURCE_ID_A = "src-fixture-001"
SOURCE_ID_B = "src-fixture-002"
SOURCE_ID_C = "src-fixture-003"


def _vocabulary_v1() -> Vocabulary:
    """First synthetic vocabulary (``V``) — 2 entries."""
    return Vocabulary(
        name="invariants-v1",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall"],
                operand_types=[
                    OperandTypeSchema(name="obligor", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="V entry 1",
            ),
            VocabularyEntry(
                predicate="asserts_factual_event",
                aliases=[],
                operand_types=[],
                qualifier_required=False,
                notes="V entry 2",
            ),
        ],
    )


def _vocabulary_v2() -> Vocabulary:
    """Second synthetic vocabulary (``V'``) — different entries.

    Deliberately disjoint from V's entries so ``model_dump`` differs and
    a "did the snapshot change?" check is unambiguous.
    """
    return Vocabulary(
        name="invariants-v2",
        version="0.2.0",
        entries=[
            VocabularyEntry(
                predicate="cites_evidence",
                aliases=[],
                operand_types=[],
                qualifier_required=False,
                notes="V' entry 1",
            ),
            VocabularyEntry(
                predicate="denies_factual_assertion",
                aliases=[],
                operand_types=[],
                qualifier_required=False,
                notes="V' entry 2",
            ),
        ],
    )


@pytest.mark.invariants
def test_inv10_each_distillation_has_snapshot(tmp_workspace: Path) -> None:
    """Positive: two distillations snapshotted with the same vocab; both pinned.

    Verifies that ``snapshot_vocabulary`` creates the canonical pin file
    for each distillation under ``vocabulary_snapshot_path`` and that
    ``get_vocabulary_snapshot`` round-trips back to the same content.
    """
    substrate = Substrate(tmp_workspace)
    vocab = _vocabulary_v1()
    substrate.snapshot_vocabulary(SOURCE_ID_A, vocab)
    substrate.snapshot_vocabulary(SOURCE_ID_B, vocab)

    assert substrate.vocabulary_snapshot_path(SOURCE_ID_A).is_file()
    assert substrate.vocabulary_snapshot_path(SOURCE_ID_B).is_file()

    loaded_a = substrate.get_vocabulary_snapshot(SOURCE_ID_A)
    loaded_b = substrate.get_vocabulary_snapshot(SOURCE_ID_B)
    assert loaded_a.model_dump() == vocab.model_dump()
    assert loaded_b.model_dump() == vocab.model_dump()


@pytest.mark.invariants
def test_inv10_snapshot_independent_of_subsequent_edits(tmp_workspace: Path) -> None:
    """Positive: pinning a different vocab to B does not change A's pin.

    This is the heart of INV-10: vocabulary edits between distillations
    must NOT retroactively change what existing atoms mean. We model
    "registry edit" by constructing a different in-memory vocabulary
    (``V'``) and snapshotting IT to source B. Source A's snapshot must
    remain identically what was originally pinned.
    """
    substrate = Substrate(tmp_workspace)
    vocab_v = _vocabulary_v1()
    vocab_v_prime = _vocabulary_v2()

    substrate.snapshot_vocabulary(SOURCE_ID_A, vocab_v)
    # Simulate the registry being "edited" between distillations: pin V'
    # (a different vocabulary) to source B.
    substrate.snapshot_vocabulary(SOURCE_ID_B, vocab_v_prime)

    loaded_a = substrate.get_vocabulary_snapshot(SOURCE_ID_A)
    loaded_b = substrate.get_vocabulary_snapshot(SOURCE_ID_B)
    assert loaded_a.model_dump() == vocab_v.model_dump()
    assert loaded_b.model_dump() == vocab_v_prime.model_dump()
    # Sanity: A and B differ now (vocabulary evolution happened between them).
    assert loaded_a.model_dump() != loaded_b.model_dump()


@pytest.mark.invariants
def test_inv10_distillation_without_snapshot_raises(
    tmp_workspace: Path, matched_atom_factory: MatchedAtomFactory
) -> None:
    """Negative: writing an atom without snapshotting first is the INV-10 violation.

    A distillation that contains atoms but has no
    ``vocabulary-snapshot.yaml`` cannot be replayed deterministically:
    validators have no vocabulary to consult against. The signal an
    auditor would surface is ``SubstrateNotFound`` from
    ``get_vocabulary_snapshot``.
    """
    substrate = Substrate(tmp_workspace)
    # Write an atom under source C, but skip snapshot_vocabulary.
    atom, prov = matched_atom_factory(source_id=SOURCE_ID_C)
    substrate.add_provenance(SOURCE_ID_C, prov)
    substrate.add_atom(SOURCE_ID_C, atom)

    assert substrate.vocabulary_snapshot_path(SOURCE_ID_C).exists() is False
    with pytest.raises(SubstrateNotFound):
        substrate.get_vocabulary_snapshot(SOURCE_ID_C)


@pytest.mark.invariants
def test_inv10_corrupt_snapshot_raises(tmp_workspace: Path) -> None:
    """Negative: a present-but-unparseable snapshot raises ``SubstrateSnapshotCorrupt``.

    INV-10 says validators read the snapshot. A snapshot whose content
    cannot be parsed back into a ``Vocabulary`` is functionally
    equivalent to no snapshot — but it requires a *different* auditor
    signal (the file *exists*, so ``SubstrateNotFound`` would be wrong;
    a tampered or partially-written pin is a corruption event, not a
    missing one). The substrate raises ``SubstrateSnapshotCorrupt`` so
    auditors can distinguish "never snapshotted" from "snapshot damaged"
    — important because the remediation paths diverge.
    """
    substrate = Substrate(tmp_workspace)
    snapshot_path = substrate.vocabulary_snapshot_path(SOURCE_ID_A)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text("::: not valid yaml at all :::", encoding="utf-8")

    assert snapshot_path.exists()
    with pytest.raises(SubstrateSnapshotCorrupt):
        substrate.get_vocabulary_snapshot(SOURCE_ID_A)


@pytest.mark.invariants
def test_inv10_manifest_records_snapshot_hash(tmp_workspace: Path) -> None:
    """INV-10 — Vocabulary is pinned per distillation.

    The fourth (previously deferred) clause of INV-10: the source-mirror
    manifest must record the SHA-256 of the per-distillation vocabulary
    snapshot, so auditors can verify the pin has not been tampered with
    after ingest. M3.1 lands the manifest file; this gate test asserts:

    1. After running ``ingest_pdf``, ``manifest.vocabulary_snapshot_sha256``
       equals ``sha256(<vocabulary-snapshot.yaml bytes>).hexdigest()``.
    2. The manifest on disk round-trips that hash byte-for-byte through
       ``yaml.safe_load`` + ``SourceMirrorManifest.model_validate``.
    """
    substrate = Substrate(tmp_workspace)
    vocab = _vocabulary_v1()
    agent = AgentAttribution(
        kind="llm",
        identifier="claude-opus-4-7",
        role="extractor",
    )
    manifest = ingest_pdf(
        substrate=substrate,
        source_id=SOURCE_ID_A,
        pdf_path=_INGEST_FIXTURE_PDF,
        vocabulary=vocab,
        agent_attribution=agent,
    )

    snapshot_path = substrate.vocabulary_snapshot_path(SOURCE_ID_A)
    snapshot_bytes = snapshot_path.read_bytes()
    expected_hash = hashlib.sha256(snapshot_bytes).hexdigest()
    assert manifest.vocabulary_snapshot_sha256 == expected_hash

    manifest_path = substrate.manifest_path(SOURCE_ID_A)
    on_disk = SourceMirrorManifest.model_validate(
        yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    )
    assert on_disk.vocabulary_snapshot_sha256 == expected_hash
