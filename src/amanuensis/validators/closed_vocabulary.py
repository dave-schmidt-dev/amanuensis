"""``closed_vocabulary`` — INV-5 enforcement.

INV-5: every atom's ``predicate`` must be drawn from the project's
closed predicate vocabulary. Validators route the lookup through
``Vocabulary.has_predicate`` so aliases resolve correctly (a predicate
named under one of an entry's declared aliases counts as registered).

Per INV-10, callers MUST pass the per-distillation snapshot vocabulary
(obtained via ``Substrate.get_vocabulary_snapshot(source_id)``), not the
global ``~/.amanuensis/vocabularies/`` registry. Snapshot-lookup is the
caller's responsibility — this validator stays pure (no substrate
handle, no global state) so it can be unit-tested in isolation and so
auditor surfaces can route the snapshot to it explicitly.
"""

from __future__ import annotations

from amanuensis.schemas import Atom, Vocabulary

from ._result import ValidationResult

VALIDATOR_NAME = "closed_vocabulary"


def closed_vocabulary(atom: Atom, *, vocabulary: Vocabulary) -> ValidationResult:
    """Pass iff ``atom.predicate`` resolves in ``vocabulary``.

    Resolution is alias-aware (delegated to ``Vocabulary.has_predicate``).
    The caller is responsible for supplying the per-distillation snapshot
    vocabulary (INV-10) rather than the global registry.
    """
    if vocabulary.has_predicate(atom.predicate):
        return ValidationResult.ok(VALIDATOR_NAME, subject_id=atom.id)
    return ValidationResult.fail(
        VALIDATOR_NAME,
        f"predicate {atom.predicate!r} not in vocabulary {vocabulary.name!r}",
        subject_id=atom.id,
    )
