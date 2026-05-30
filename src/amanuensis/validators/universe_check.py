"""``universe_check`` — atom.source_id must refer to a known source.

Phase 1's distillation substrate cites a source by id. If an atom's
``source_id`` does not appear in the set of source-mirror documents the
substrate knows about, the atom is citing a universe member that was
never ingested — a soft equivalent of a dangling pointer. This validator
makes that check explicit and named.

This validator has no numbered invariant (it's a named structural
property, not a charter-level commitment). It exists so the auditor
surface can report "atom references unknown source" with a stable name.

Design notes
------------
- The known-source-id set is passed in by the caller rather than
  rediscovered from the substrate. The Substrate does not (yet) expose a
  ``list_source_ids`` method; wiring that is a substrate change that
  belongs to its own task. Keeping the validator pure also lets callers
  test it against synthetic universes without filesystem state.
"""

from __future__ import annotations

from amanuensis.schemas import Atom

from ._result import ValidationResult

VALIDATOR_NAME = "universe_check"


def universe_check(atom: Atom, *, known_source_ids: set[str]) -> ValidationResult:
    """Pass iff ``atom.source_id`` is in ``known_source_ids``."""
    if atom.source_id in known_source_ids:
        return ValidationResult.ok(VALIDATOR_NAME, subject_id=atom.id)
    return ValidationResult.fail(
        VALIDATOR_NAME,
        f"atom.source_id={atom.source_id!r} not in known sources",
        subject_id=atom.id,
    )
