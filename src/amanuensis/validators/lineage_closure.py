"""``lineage_closure`` — every atom a Relation references must exist.

A Relation expresses a Toulmin-style warrant between two atoms in the
same distillation. ``lineage_closure`` confirms both endpoints
(``from_atom_id`` and ``to_atom_id``) resolve to real atom files under
``relation.source_id``. Without this, a relation could point at an
atom-id that was never written, leaving the warrant dangling.

This validator has no numbered invariant in INVARIANTS.md (it's a named
structural property in support of INV-8 substrate-as-truth). It exists
so the auditor surface can report dangling relations by name.

Design notes
------------
- Relation schema uses ``from_atom_id`` / ``to_atom_id`` (the brief
  referred to ``subject_atom_id`` / ``object_atom_id``; the on-disk
  schema is the source of truth, so we use the actual field names).
- Failure reports the FIRST broken endpoint we encounter (``from`` is
  checked before ``to``); "first failure wins" mirrors the project-wide
  validator contract.
- ``SubstrateInvalidId`` is caught alongside ``SubstrateNotFound``: a
  malformed atom-id pointer is, from the validator's perspective, an
  unfollowable pointer.
"""

from __future__ import annotations

from amanuensis.fs import Substrate, SubstrateInvalidId, SubstrateNotFound
from amanuensis.schemas import Relation

from ._result import ValidationResult

VALIDATOR_NAME = "lineage_closure"


def lineage_closure(relation: Relation, *, substrate: Substrate) -> ValidationResult:
    """Pass iff both atoms referenced by ``relation`` exist on the substrate."""
    for side, atom_id in (("from", relation.from_atom_id), ("to", relation.to_atom_id)):
        try:
            substrate.get_atom(relation.source_id, atom_id)
        except SubstrateNotFound:
            return ValidationResult.fail(
                VALIDATOR_NAME,
                f"lineage_closure violation: {side} atom {atom_id!r} not found "
                f"in source {relation.source_id!r}",
                subject_id=relation.id,
            )
        except SubstrateInvalidId as exc:
            return ValidationResult.fail(
                VALIDATOR_NAME,
                f"lineage_closure violation: {side} atom_id is not a valid path component ({exc})",
                subject_id=relation.id,
            )
    return ValidationResult.ok(VALIDATOR_NAME, subject_id=relation.id)
