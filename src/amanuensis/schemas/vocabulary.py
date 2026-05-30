"""Vocabulary — closed predicate registry for the distillation substrate.

A ``Vocabulary`` declares the predicates that Atoms are allowed to use
(closed-vocabulary discipline, INV-5). Each ``VocabularyEntry`` names
one predicate, its accepted aliases, the operand positions it requires,
and whether a qualifier is mandatory.

The Phase 1 closure check is M2.4 and is NOT enforced here; this module
defines the schema and the alias-aware lookup helpers
(``has_predicate``, ``resolve``, ``entries_by_predicate``) plus the
``load`` classmethod that produces a structurally-validated instance.

INV-5 (closed predicate vocabulary) and INV-10 (vocabulary pinned per
distillation) both depend on ``has_predicate`` / ``resolve`` being
total, unambiguous functions; ``Vocabulary.load`` enforces the
structural rules (no duplicate predicate, no alias collision) that make
that property hold.

Design note
-----------
``OperandTypeSchema`` mirrors the shape of ``OperandRef`` from
``_shared.py``: the latter is a runtime value (this Atom *has* these
operands), the former is a registry-level expectation (this predicate
*expects* operands matching this shape). ``OperandTypeSchema`` lives
here, not in ``_shared.py``, because it is a vocabulary-domain concept.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from typing import Self


class OperandTypeSchema(BaseModel):
    """Schema describing one operand position a predicate expects.

    For example, predicate ``asserts_payment`` might require two
    operands: one of ``kind="entity"`` (the payer) and one of
    ``kind="literal"`` with ``type_hint="money"`` (the amount). The
    Vocabulary registry uses this to validate atoms at the closed-
    vocabulary gate (M2.4 / INV-5).

    Mirrors the value-side shape of ``amanuensis.schemas.OperandRef``;
    kept here because it is vocabulary-domain configuration.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str
    kind: Literal["entity", "literal", "doc_span"]
    required: bool = True
    type_hint: str | None = None


class VocabularyEntry(BaseModel):
    """One predicate registered in a Vocabulary."""

    model_config = ConfigDict(strict=True, extra="forbid")

    predicate: str
    aliases: list[str] = []
    operand_types: list[OperandTypeSchema]
    qualifier_required: bool
    notes: str


class Vocabulary(BaseModel):
    """A named, versioned closed predicate registry."""

    # ``ignored_types`` lets Pydantic v2 see ``cached_property`` as a
    # descriptor rather than treating it as a model field. Without it
    # ``entries_by_predicate`` would be silently dropped (or worse,
    # parsed as a field at construction).
    model_config = ConfigDict(strict=True, extra="forbid", ignored_types=(cached_property,))

    name: str
    version: str
    entries: list[VocabularyEntry]

    @classmethod
    def load(cls, path: Path | str) -> Self:
        """Read + validate a vocabulary YAML file.

        Thin facade over ``amanuensis.vocabulary.registry.load_vocabulary``;
        kept here so callers with only the schema imported still have
        ``Vocabulary.load(...)`` available. Raises
        ``VocabularyLoadError`` on parse / schema / structural failure.
        """
        # Local import to keep schemas/ a leaf module (no upward import
        # of the vocabulary package at module load time).
        from amanuensis.vocabulary.registry import load_vocabulary

        loaded = load_vocabulary(path)
        # ``load_vocabulary`` returns a ``Vocabulary``; in subclass usage
        # we want ``Self`` semantics, so re-validate through ``cls`` when
        # ``cls`` is not the exact ``Vocabulary`` class.
        if type(loaded) is cls:
            return loaded  # type: ignore[return-value]
        return cls.model_validate(loaded.model_dump())

    @cached_property
    def entries_by_predicate(self) -> dict[str, VocabularyEntry]:
        """Map canonical predicate -> entry for O(1) lookup.

        Cached on first access; safe because ``Vocabulary`` is treated as
        immutable in practice (every mutation goes through a fresh
        validation via Pydantic). Validators in M2.4 will reach for
        this through ``has_predicate`` and ``resolve``.
        """
        return {entry.predicate: entry for entry in self.entries}

    def has_predicate(self, name: str) -> bool:
        """True iff ``name`` resolves to a canonical predicate.

        Accepts either the canonical predicate or one of its declared
        aliases. The structural rules enforced at ``load`` time
        guarantee at most one entry can match any given name.
        """
        return self.resolve(name) is not None

    def resolve(self, name: str) -> str | None:
        """Return the canonical predicate for ``name`` (predicate or alias).

        Returns ``None`` if ``name`` is not registered. Identity case
        (``name`` is already a canonical predicate) returns ``name``
        unchanged.
        """
        if name in self.entries_by_predicate:
            return name
        for entry in self.entries:
            if name in entry.aliases:
                return entry.predicate
        return None
