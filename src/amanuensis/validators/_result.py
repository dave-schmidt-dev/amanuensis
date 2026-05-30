"""``ValidationResult`` — the unified return type for canonical validators.

Each validator in ``amanuensis.validators`` returns a ``ValidationResult``
naming itself, recording pass/fail, the human-readable failure reason
(empty on pass), and the id of the subject artifact that failed (when
applicable). Auditor surfaces (M7) and the CLI (M4) aggregate these
results; keeping the shape uniform across all seven validators lets the
aggregator render uniformly.

Design notes
------------
- ``frozen=True`` + ``slots=True``: a result is an immutable record. The
  auditor builds long lists of them; ``slots`` keeps memory predictable
  and ``frozen`` prevents accidental mutation while accumulating.
- "First failure wins" — a validator returns a single ``ValidationResult``
  per call. Surfaces that need multi-failure granularity (e.g. an atom
  with three vocabulary violations across different fields) re-run
  validators against each subject; we do not encode multi-error on the
  result itself.
- ``subject_id`` is ``str | None`` because some validators (``schema_check``
  on a raw dict that lacks an id) legitimately have no subject to name.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of a single canonical-validator invocation."""

    passed: bool
    validator: str
    reason: str
    subject_id: str | None = None

    @classmethod
    def ok(cls, validator: str, *, subject_id: str | None = None) -> ValidationResult:
        """Convenience constructor for the pass case (empty reason)."""
        return cls(passed=True, validator=validator, reason="", subject_id=subject_id)

    @classmethod
    def fail(
        cls,
        validator: str,
        reason: str,
        *,
        subject_id: str | None = None,
    ) -> ValidationResult:
        """Convenience constructor for the fail case."""
        return cls(passed=False, validator=validator, reason=reason, subject_id=subject_id)
