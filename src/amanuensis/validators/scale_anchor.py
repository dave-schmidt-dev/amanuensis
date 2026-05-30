"""``scale_anchor`` — INV-6 enforcement.

INV-6: every atom declares ``scale_anchor ∈ {sentence, paragraph,
section, document}``. Pydantic's ``Literal[...]`` on the field already
rejects out-of-vocabulary values at construction; this validator is a
named restatement of that invariant so the auditor surface can report
"atom violates INV-6" by name rather than by Pydantic error text.

For a normally-constructed ``Atom`` this is always a pass. The value of
having the validator is that it makes the INV-6 check addressable by
name (M7 / CLI surfaces will route by validator name). It is also a
defense-in-depth against unforeseen mutation: if some future code path
ever bypasses Pydantic strict validation (an exotic deserializer, an
``__init_subclass__`` quirk, etc.) and lands an out-of-vocab anchor,
this validator catches it.
"""

from __future__ import annotations

from typing import Final

from amanuensis.schemas import Atom

from ._result import ValidationResult

VALIDATOR_NAME = "scale_anchor"

_ALLOWED_ANCHORS: Final[frozenset[str]] = frozenset(
    {"sentence", "paragraph", "section", "document"}
)


def scale_anchor(atom: Atom) -> ValidationResult:
    """Verify ``atom.scale_anchor`` is in the closed INV-6 set."""
    # ``atom.scale_anchor`` is typed ``Literal[...]``; we still compare
    # against the runtime set so a post-construction mutation that the
    # type system cannot see would be caught.
    value: str = atom.scale_anchor
    if value in _ALLOWED_ANCHORS:
        return ValidationResult.ok(VALIDATOR_NAME, subject_id=atom.id)
    return ValidationResult.fail(
        VALIDATOR_NAME,
        f"INV-6 violation: scale_anchor={value!r} not in {sorted(_ALLOWED_ANCHORS)}",
        subject_id=atom.id,
    )
