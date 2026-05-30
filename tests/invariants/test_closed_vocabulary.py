"""Gate test for INV-5 (Closed predicate vocabulary at extraction).

Quoting INVARIANTS.md INV-5 verbatim:

    Atoms must use predicates from the project's vocabulary registry.
    Open-vocabulary extraction is rejected by the auditor. Adding new
    predicates requires a governance event (human-proposed, test-suite
    validated, version-bumped registry commit).

What this gate certifies
------------------------
The M2.4 ``closed_vocabulary`` validator rejects atoms whose predicate
is not in the (per-distillation) SNAPSHOT vocabulary. The gate also
certifies INV-10's "validators read the snapshot, not the global"
property is testable: an atom whose predicate is in the global registry
but not in the snapshot is rejected when the validator routes through
the snapshot.

Scope boundary
--------------
This gate exercises the validator directly against the snapshot
``Vocabulary``; the auditor's "vocabulary-violation" surface (M7) wraps
the same validator but produces an auditor-flavored aggregate report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import Substrate
from amanuensis.schemas import Vocabulary
from amanuensis.validators import closed_vocabulary
from amanuensis.vocabulary.registry import load_vocabulary
from tests.invariants._types import MatchedAtomFactory

SOURCE_ID = "src-fixture-001"

# Path to the vendored generic registry (real file on disk, not a fixture).
_GENERIC_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "vocabularies" / "generic" / "predicates.yaml"
)


def _snapshot_generic_into(substrate: Substrate, source_id: str) -> Vocabulary:
    """Load the vendored generic registry and snapshot it under ``source_id``."""
    vocab = load_vocabulary(_GENERIC_REGISTRY_PATH)
    substrate.snapshot_vocabulary(source_id, vocab)
    return vocab


@pytest.mark.invariants
def test_inv5_known_canonical_predicate_passes(
    tmp_workspace: Path, matched_atom_factory: MatchedAtomFactory
) -> None:
    """Positive: canonical predicate ``asserts_obligation`` resolves in the snapshot."""
    substrate = Substrate(tmp_workspace)
    _snapshot_generic_into(substrate, SOURCE_ID)
    atom, _ = matched_atom_factory(predicate="asserts_obligation")
    snapshot = substrate.get_vocabulary_snapshot(SOURCE_ID)

    result = closed_vocabulary(atom, vocabulary=snapshot)
    assert result.passed is True
    assert result.validator == "closed_vocabulary"
    assert result.subject_id == atom.id


@pytest.mark.invariants
def test_inv5_known_alias_passes(
    tmp_workspace: Path, matched_atom_factory: MatchedAtomFactory
) -> None:
    """Positive: an alias (``asserts_shall``) resolves through the snapshot.

    ``asserts_shall`` is declared as an alias of ``asserts_obligation`` in
    ``vocabularies/generic/predicates.yaml``; resolution must be
    alias-aware (delegated to ``Vocabulary.has_predicate``).
    """
    substrate = Substrate(tmp_workspace)
    _snapshot_generic_into(substrate, SOURCE_ID)
    atom, _ = matched_atom_factory(predicate="asserts_shall")
    snapshot = substrate.get_vocabulary_snapshot(SOURCE_ID)

    result = closed_vocabulary(atom, vocabulary=snapshot)
    assert result.passed is True


@pytest.mark.invariants
def test_inv5_unknown_predicate_fails(
    tmp_workspace: Path, matched_atom_factory: MatchedAtomFactory
) -> None:
    """Negative: an obviously unregistered predicate is rejected.

    Failure reason must name the offending predicate and the vocabulary
    so an auditor surface can render the violation legibly.
    """
    substrate = Substrate(tmp_workspace)
    vocab = _snapshot_generic_into(substrate, SOURCE_ID)
    bad_predicate = "asserts_definitely_not_in_vocab_xyz"
    atom, _ = matched_atom_factory(predicate=bad_predicate)
    snapshot = substrate.get_vocabulary_snapshot(SOURCE_ID)

    result = closed_vocabulary(atom, vocabulary=snapshot)
    assert result.passed is False
    assert bad_predicate in result.reason
    assert vocab.name in result.reason
    assert result.subject_id == atom.id


@pytest.mark.invariants
def test_inv5_snapshot_vs_global_distinction(
    tmp_workspace: Path,
    matched_atom_factory: MatchedAtomFactory,
    vocabulary_subset: Vocabulary,
) -> None:
    """Negative: a predicate in the GLOBAL but NOT in the SNAPSHOT is rejected.

    Certifies INV-10's "validators read the snapshot, not the global"
    property: snapshot a 3-entry subset to the substrate; load the full
    generic registry in memory; pick a predicate that exists in the
    global registry but NOT in the subset; run ``closed_vocabulary``
    against the snapshot and assert it fails.

    This is the test that would catch a regression where a validator
    accidentally consulted the global registry as a fallback.
    """
    substrate = Substrate(tmp_workspace)
    substrate.snapshot_vocabulary(SOURCE_ID, vocabulary_subset)

    # Load the global registry just to confirm our chosen predicate is
    # actually IN it (so the test stays honest if the global registry
    # changes in the future).
    global_vocab = load_vocabulary(_GENERIC_REGISTRY_PATH)
    predicate_in_global_only = "alleges_exclusionary_conduct"
    assert global_vocab.has_predicate(predicate_in_global_only), (
        f"test premise broken: {predicate_in_global_only!r} no longer in global registry"
    )
    assert not vocabulary_subset.has_predicate(predicate_in_global_only), (
        f"test premise broken: {predicate_in_global_only!r} leaked into the subset"
    )

    atom, _ = matched_atom_factory(predicate=predicate_in_global_only)
    snapshot = substrate.get_vocabulary_snapshot(SOURCE_ID)

    result = closed_vocabulary(atom, vocabulary=snapshot)
    assert result.passed is False
    assert predicate_in_global_only in result.reason
    assert vocabulary_subset.name in result.reason
