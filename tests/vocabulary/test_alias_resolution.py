"""Alias-aware resolution tests for ``Vocabulary``.

Covers the lookup contract validators (M2.4) will depend on:

- ``resolve(canonical)`` returns the canonical name unchanged.
- ``resolve(alias)`` returns the canonical owner of the alias.
- ``resolve(unknown)`` returns ``None``.
- ``has_predicate(alias)`` is True; ``has_predicate(unknown)`` is False.
- A synthetic vocab where ``predicate=x, aliases=[y]`` and
  ``predicate=y, aliases=[]`` fails to load (resolution would be
  ambiguous; loader must refuse).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from amanuensis.vocabulary import VocabularyLoadError, load_vocabulary

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERIC_VOCAB_PATH = REPO_ROOT / "vocabularies" / "generic" / "predicates.yaml"

# A handful of (alias, canonical) pairs drawn from the vendored
# vocabulary so this test pins real alias semantics, not contrived
# ones.
ALIAS_TO_CANONICAL = [
    ("states_event", "asserts_factual_event"),
    ("defines_market", "asserts_market_definition"),
    ("asserts_monopoly_power", "asserts_market_dominance"),
    ("asserts_shall", "asserts_obligation"),
    ("warrants", "asserts_representation_warranty"),
    ("rejects_fact", "denies_factual_assertion"),
    ("cites_proof", "cites_evidence"),
]


@pytest.mark.parametrize(("alias", "canonical"), ALIAS_TO_CANONICAL)
def test_resolve_alias_returns_canonical(alias: str, canonical: str) -> None:
    vocab = load_vocabulary(GENERIC_VOCAB_PATH)
    assert vocab.resolve(alias) == canonical


@pytest.mark.parametrize(("alias", "canonical"), ALIAS_TO_CANONICAL)
def test_has_predicate_true_for_alias(alias: str, canonical: str) -> None:
    vocab = load_vocabulary(GENERIC_VOCAB_PATH)
    assert vocab.has_predicate(alias) is True
    # Sanity check the canonical also resolves to itself.
    assert vocab.has_predicate(canonical) is True


def test_resolve_canonical_returns_self() -> None:
    vocab = load_vocabulary(GENERIC_VOCAB_PATH)
    for entry in vocab.entries:
        assert vocab.resolve(entry.predicate) == entry.predicate


def test_resolve_unknown_returns_none() -> None:
    vocab = load_vocabulary(GENERIC_VOCAB_PATH)
    assert vocab.resolve("not_in_vocab") is None
    assert vocab.resolve("") is None


def test_entries_by_predicate_cached_property() -> None:
    vocab = load_vocabulary(GENERIC_VOCAB_PATH)
    table = vocab.entries_by_predicate
    assert len(table) == len(vocab.entries)
    # Re-access returns the same object (cached_property semantics).
    assert vocab.entries_by_predicate is table
    # Spot-check: a canonical key maps to the right entry.
    entry = table["asserts_obligation"]
    assert entry.predicate == "asserts_obligation"
    assert "asserts_shall" in entry.aliases


def test_alias_collision_from_resolution_angle(tmp_path: Path) -> None:
    """``predicate=x, aliases=[y]`` and ``predicate=y, []`` must fail to load.

    This is the resolution-side framing of the same rule the loader
    tests already cover, written here to make the test file
    self-contained for readers focused on alias semantics.
    """
    bad_path = tmp_path / "ambiguous.yaml"
    bad_path.write_text(
        yaml.safe_dump(
            {
                "name": "ambiguous",
                "version": "0.0.1",
                "entries": [
                    {
                        "predicate": "x_canonical",
                        "aliases": ["y_canonical"],
                        "operand_types": [],
                        "qualifier_required": False,
                        "notes": "x",
                    },
                    {
                        "predicate": "y_canonical",
                        "aliases": [],
                        "operand_types": [],
                        "qualifier_required": False,
                        "notes": "y",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(VocabularyLoadError, match="collides with"):
        load_vocabulary(bad_path)


def test_alias_equal_to_own_predicate_rejected(tmp_path: Path) -> None:
    """An entry whose alias equals its own predicate is malformed."""
    bad_path = tmp_path / "self_alias.yaml"
    bad_path.write_text(
        yaml.safe_dump(
            {
                "name": "self-alias",
                "version": "0.0.1",
                "entries": [
                    {
                        "predicate": "asserts_a",
                        "aliases": ["asserts_a"],
                        "operand_types": [],
                        "qualifier_required": False,
                        "notes": "self-aliased",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(VocabularyLoadError, match="own predicate"):
        load_vocabulary(bad_path)
