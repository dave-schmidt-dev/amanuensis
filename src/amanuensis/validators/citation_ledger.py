"""``citation_ledger`` — INV-7 enforcement.

INV-7: every atom resolves to a precise source span via the four-tuple
``(source_id, section_path, paragraph_index, char_span)``. Pydantic
already enforces presence of each field (no default, ``extra="forbid"``)
and Atom's ``char_span`` validator already enforces ``start < end``.
This validator adds the semantic checks Pydantic cannot easily express:

- ``source_id`` is non-empty.
- ``section_path`` is a non-empty list of non-empty strings.
- ``paragraph_index >= 0``.
- ``char_span[0] >= 0`` (Atom rejects ``start >= end``; this rejects
  negative starts too — together the pair confirms ``0 <= start < end``).

Pass message is empty (project-wide convention). Fail messages start
with ``"INV-7 violation: "`` so auditor surfaces can group by invariant.
"""

from __future__ import annotations

from amanuensis.schemas import Atom

from ._result import ValidationResult

VALIDATOR_NAME = "citation_ledger"


def citation_ledger(atom: Atom) -> ValidationResult:
    """Verify the citation four-tuple (INV-7) on ``atom``."""
    if not atom.source_id:
        return ValidationResult.fail(
            VALIDATOR_NAME,
            "INV-7 violation: source_id is empty",
            subject_id=atom.id,
        )
    if not atom.section_path:
        return ValidationResult.fail(
            VALIDATOR_NAME,
            "INV-7 violation: section_path is empty",
            subject_id=atom.id,
        )
    for idx, segment in enumerate(atom.section_path):
        if not segment:
            return ValidationResult.fail(
                VALIDATOR_NAME,
                f"INV-7 violation: section_path[{idx}] is empty",
                subject_id=atom.id,
            )
    if atom.paragraph_index < 0:
        return ValidationResult.fail(
            VALIDATOR_NAME,
            f"INV-7 violation: paragraph_index={atom.paragraph_index} is negative",
            subject_id=atom.id,
        )
    start, end = atom.char_span
    if start < 0:
        return ValidationResult.fail(
            VALIDATOR_NAME,
            f"INV-7 violation: char_span start={start} is negative",
            subject_id=atom.id,
        )
    # Atom's field_validator enforces ``start < end`` at construction, so
    # this branch is only reachable via post-construction mutation
    # (e.g., ``object.__setattr__``). Defending it anyway mirrors the
    # ``scale_anchor`` validator's stance on out-of-band mutation: keep
    # every validator total over the type so the Auditor never raises.
    if not start < end:
        return ValidationResult.fail(
            VALIDATOR_NAME,
            f"INV-7 violation: char_span start must be < end (got start={start}, end={end})",
            subject_id=atom.id,
        )
    return ValidationResult.ok(VALIDATOR_NAME, subject_id=atom.id)
