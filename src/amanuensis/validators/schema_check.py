"""``schema_check`` — validate a payload against a Pydantic model.

This validator wraps ``BaseModel.model_validate`` so the auditor surface
(M7) can ask "does this dict / instance conform to its schema?" by name,
uniformly with the other six canonical validators.

Design notes
------------
- An already-constructed model instance passes by construction: Pydantic
  strict mode + ``extra="forbid"`` would have rejected it at the
  constructor; arriving here means it parsed cleanly.
- A dict payload is round-tripped through ``model_class.model_validate``.
  The first ``ValidationError`` is summarized into the result's ``reason``
  (``loc`` + ``msg``); the full multi-error structure can be re-rendered
  by the auditor by calling Pydantic directly when it wants the detail.
- "First failure wins" mirrors the project-wide validator contract; we
  do not aggregate multi-error reports inside ``ValidationResult``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from ._result import ValidationResult

VALIDATOR_NAME = "schema_check"


def schema_check(
    payload: BaseModel | dict[str, Any],
    *,
    model_class: type[BaseModel],
) -> ValidationResult:
    """Validate ``payload`` against ``model_class``.

    Already-constructed instances of ``model_class`` (or any subclass)
    pass trivially. Dict payloads are validated via
    ``model_class.model_validate``; the first error's location and
    message are returned as the failure reason. ``subject_id`` is the
    dict's ``id`` field when present, otherwise ``None``.
    """
    if isinstance(payload, model_class):
        return ValidationResult.ok(VALIDATOR_NAME, subject_id=_extract_id(payload))
    if isinstance(payload, BaseModel):
        # Different model class than expected — surface as a schema failure
        # rather than silently passing on a wrong-typed instance.
        return ValidationResult.fail(
            VALIDATOR_NAME,
            f"payload is {type(payload).__name__}; expected {model_class.__name__}",
            subject_id=_extract_id(payload),
        )
    subject_id = _extract_id(payload)
    try:
        model_class.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        msg = first.get("msg", "validation error")
        reason = f"{loc}: {msg}" if loc else msg
        return ValidationResult.fail(VALIDATOR_NAME, reason, subject_id=subject_id)
    return ValidationResult.ok(VALIDATOR_NAME, subject_id=subject_id)


def _extract_id(payload: BaseModel | dict[str, Any]) -> str | None:
    """Best-effort ``id`` extraction; ``None`` if absent or non-string."""
    if isinstance(payload, BaseModel):
        value = getattr(payload, "id", None)
        return value if isinstance(value, str) else None
    value = payload.get("id")
    return value if isinstance(value, str) else None
