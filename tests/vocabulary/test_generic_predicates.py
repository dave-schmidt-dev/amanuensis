"""Happy-path + structural-rule tests for the vendored v0.1 vocabulary.

The vendored ``vocabularies/generic/predicates.yaml`` (M2.2) is the
fixture: it must load cleanly, expose 58 entries, and answer
``has_predicate`` correctly for both canonical names and unknown
predicates. The structural-rule tests assert the loader rejects
duplicate-predicate and alias-collision YAMLs — these are the
prerequisites that make ``resolve`` unambiguous (INV-5).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from amanuensis.schemas import Vocabulary
from amanuensis.vocabulary import VocabularyLoadError, load_vocabulary

# Path to the vendored generic vocabulary (M2.2 deliverable).
REPO_ROOT = Path(__file__).resolve().parents[2]
GENERIC_VOCAB_PATH = REPO_ROOT / "vocabularies" / "generic" / "predicates.yaml"


def test_vendored_vocabulary_loads() -> None:
    vocab = load_vocabulary(GENERIC_VOCAB_PATH)
    assert vocab.name == "amanuensis-generic-v0.1"
    assert vocab.version == "0.1.0"
    assert len(vocab.entries) == 58


def test_vocabulary_load_classmethod_equivalent() -> None:
    vocab = Vocabulary.load(GENERIC_VOCAB_PATH)
    assert vocab.name == "amanuensis-generic-v0.1"
    assert len(vocab.entries) == 58


def test_vendored_vocabulary_contains_expected_predicates() -> None:
    vocab = load_vocabulary(GENERIC_VOCAB_PATH)
    expected = {
        "asserts_market_definition",
        "asserts_obligation",
        "asserts_finding",
        "cites_evidence",
        "quotes_party_statement",
        "exhibits_data",
        "applies_jurisdiction",
        "applies_governing_law",
        "concludes_finding",
        "denies_proof",
        "denies_causal_link",
        "contests_defense",
    }
    canonical = {entry.predicate for entry in vocab.entries}
    missing = expected - canonical
    assert missing == set(), f"vocabulary missing expected predicates: {missing}"


def test_has_predicate_true_for_canonical_name() -> None:
    vocab = load_vocabulary(GENERIC_VOCAB_PATH)
    assert vocab.has_predicate("asserts_obligation") is True
    assert vocab.has_predicate("cites_evidence") is True


def test_has_predicate_false_for_unknown_name() -> None:
    vocab = load_vocabulary(GENERIC_VOCAB_PATH)
    assert vocab.has_predicate("nonexistent_predicate_xyz") is False
    assert vocab.has_predicate("") is False


def test_duplicate_predicate_rejected(tmp_path: Path) -> None:
    """Two entries with the same ``predicate`` field must fail to load."""
    bad_path = tmp_path / "dup.yaml"
    bad_path.write_text(
        yaml.safe_dump(
            {
                "name": "dup-test",
                "version": "0.0.1",
                "entries": [
                    {
                        "predicate": "asserts_x",
                        "aliases": [],
                        "operand_types": [],
                        "qualifier_required": False,
                        "notes": "first",
                    },
                    {
                        "predicate": "asserts_x",
                        "aliases": [],
                        "operand_types": [],
                        "qualifier_required": False,
                        "notes": "second",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(VocabularyLoadError, match="duplicate predicate"):
        load_vocabulary(bad_path)


def test_alias_collides_with_other_predicate_rejected(tmp_path: Path) -> None:
    """Alias of entry A equal to canonical predicate of entry B → reject."""
    bad_path = tmp_path / "alias_collision.yaml"
    bad_path.write_text(
        yaml.safe_dump(
            {
                "name": "alias-collision",
                "version": "0.0.1",
                "entries": [
                    {
                        "predicate": "asserts_a",
                        "aliases": ["asserts_b"],
                        "operand_types": [],
                        "qualifier_required": False,
                        "notes": "A",
                    },
                    {
                        "predicate": "asserts_b",
                        "aliases": [],
                        "operand_types": [],
                        "qualifier_required": False,
                        "notes": "B",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(VocabularyLoadError, match="collides with"):
        load_vocabulary(bad_path)


def test_alias_repeated_across_entries_rejected(tmp_path: Path) -> None:
    """Same alias on two different entries must fail to load."""
    bad_path = tmp_path / "alias_repeat.yaml"
    bad_path.write_text(
        yaml.safe_dump(
            {
                "name": "alias-repeat",
                "version": "0.0.1",
                "entries": [
                    {
                        "predicate": "asserts_a",
                        "aliases": ["shared_alias"],
                        "operand_types": [],
                        "qualifier_required": False,
                        "notes": "A",
                    },
                    {
                        "predicate": "asserts_b",
                        "aliases": ["shared_alias"],
                        "operand_types": [],
                        "qualifier_required": False,
                        "notes": "B",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(VocabularyLoadError, match="collides with"):
        load_vocabulary(bad_path)


def test_schema_validation_failure_raises_load_error(tmp_path: Path) -> None:
    """Pydantic ValidationError must be wrapped as VocabularyLoadError."""
    bad_path = tmp_path / "schema_bad.yaml"
    bad_path.write_text(
        yaml.safe_dump(
            {
                # missing required `version`
                "name": "schema-bad",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(VocabularyLoadError, match="schema validation"):
        load_vocabulary(bad_path)


def test_malformed_yaml_raises_load_error(tmp_path: Path) -> None:
    bad_path = tmp_path / "malformed.yaml"
    bad_path.write_text("name: x\n  this is: not valid: yaml\n", encoding="utf-8")
    with pytest.raises(VocabularyLoadError, match="not valid YAML"):
        load_vocabulary(bad_path)


def test_missing_file_raises_load_error(tmp_path: Path) -> None:
    with pytest.raises(VocabularyLoadError, match="could not read"):
        load_vocabulary(tmp_path / "does_not_exist.yaml")
