"""``entity_kind_in_vocabulary`` — INV-12 enforcement.

INV-12: every Entity's ``kind`` must be drawn from the per-distillation
entity-kind vocabulary snapshot. Validators route the lookup through the
vocabulary to enforce the closed set of acceptable kinds.

Per INV-10, callers MUST pass the per-distillation snapshot vocabulary
(obtained via ``Substrate.snapshot_entity_vocabulary(source_id)``), not the
global registry. Snapshot-lookup is the caller's responsibility — this
validator stays pure (no substrate handle, no global state) so it can be
unit-tested in isolation and so auditor surfaces can route the snapshot to
it explicitly.
"""

from __future__ import annotations

from amanuensis.schemas import Entity
from amanuensis.vocabulary.entity_registry import EntityVocabulary

from ._result import ValidationResult

VALIDATOR_NAME = "entity_kind_in_vocabulary"


class EntityKindNotInSnapshot(Exception):
    """Raised when an Entity's kind is not in the vocabulary snapshot.

    This is a hard error — it indicates the entity was created with a kind
    that was not valid at extraction time, violating INV-12.
    """


def entity_kind_in_vocabulary(entity: Entity, *, vocabulary: EntityVocabulary) -> ValidationResult:
    """Pass iff ``entity.kind`` is in the vocabulary snapshot.

    The caller is responsible for supplying the per-distillation snapshot
    vocabulary (INV-10) rather than the global registry.

    Args:
        entity: The Entity to validate.
        vocabulary: The per-distillation EntityVocabulary snapshot.

    Returns:
        ValidationResult with passed=True if the kind is in the vocabulary.

    Raises:
        EntityKindNotInSnapshot: If the entity's kind is not in the
            vocabulary snapshot.
    """
    valid_kinds = {kind.id for kind in vocabulary.kinds}
    if entity.kind in valid_kinds:
        return ValidationResult.ok(VALIDATOR_NAME, subject_id=entity.id)

    sorted_ids = sorted(valid_kinds)
    raise EntityKindNotInSnapshot(
        f"entity kind {entity.kind!r} not in snapshot; valid: {sorted_ids}"
    )
