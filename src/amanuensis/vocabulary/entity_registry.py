"""Entity kind vocabulary loader (Phase 2a M2 substrate).

An ``EntityVocabulary`` declares the entity kinds that the distillation
substrate accepts at extraction time (a closed-vocabulary gate). Each
``EntityKind`` names one kind and the resolution rules that govern its
deduplication logic.

This module provides:

- ``EntityKind`` — a single entity kind definition.
- ``EntityVocabulary`` — a versioned collection of entity kinds.
- ``EntityVocabularyError`` — raised on load / validation failure.
- ``load_entity_vocabulary`` — read + validate a vocabulary YAML file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntityKind(BaseModel):
    """One entity kind registered in an EntityVocabulary.

    Declares the canonical kind identifier, a human-readable description,
    and the resolution rules that govern deduplication of entities of
    this kind.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    description: str
    resolution_rules: list[str] = Field(min_length=1)


class EntityVocabulary(BaseModel):
    """A versioned collection of entity kinds.

    Declares the entity kinds that the distillation substrate accepts
    at extraction time. Currently pinned to version 1.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    version: int
    kinds: list[EntityKind]

    @field_validator("kinds")
    @classmethod
    def check_unique_ids(cls, kinds: list[EntityKind]) -> list[EntityKind]:
        """Reject duplicate entity kind IDs.

        Each entity kind must have a unique identifier within the
        vocabulary. This validator runs after Pydantic's standard
        validation, ensuring structural integrity.
        """
        ids = [kind.id for kind in kinds]
        if len(set(ids)) != len(ids):
            seen: set[str] = set()
            for kind in kinds:
                if kind.id in seen:
                    raise ValueError(f"duplicate entity kind id: {kind.id!r}")
                seen.add(kind.id)
        return kinds


class EntityVocabularyError(Exception):
    """Raised when an entity vocabulary YAML file cannot be loaded.

    Covers three failure classes:

    - YAML parse failure (malformed file).
    - Pydantic schema-validation failure (missing field, wrong type,
      forbidden extra key, empty resolution_rules, etc.).
    - Structural rule failure (duplicate entity kind IDs).

    The original exception is preserved via ``from exc`` to allow
    callers to inspect the root cause if needed.
    """


def load_entity_vocabulary(path: Path | str) -> EntityVocabulary:
    """Read + validate an entity vocabulary YAML file.

    Performs three checks in order: YAML parse, schema validation
    (Pydantic strict), and structural rules (no duplicate IDs).

    Args:
        path: The filesystem path to the YAML file.

    Returns:
        An ``EntityVocabulary`` instance with all validations passed.

    Raises:
        EntityVocabularyError: If the file cannot be read, parsed as YAML,
            validated against the schema, or contains duplicate entity
            kind IDs.
    """
    file_path = Path(path)

    try:
        raw = file_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EntityVocabularyError(f"entity vocabulary file not found: {file_path}") from exc
    except OSError as exc:
        raise EntityVocabularyError(
            f"could not read entity vocabulary file {file_path}: {exc}"
        ) from exc

    try:
        parsed_any: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise EntityVocabularyError(
            f"entity vocabulary file {file_path} is not valid YAML: {exc}"
        ) from exc

    if not isinstance(parsed_any, dict):
        raise EntityVocabularyError(
            f"entity vocabulary file {file_path} top-level must be a mapping, "
            f"got {type(parsed_any).__name__}"
        )

    payload = cast("dict[str, Any]", parsed_any)

    try:
        vocab = EntityVocabulary(**payload)
    except Exception as exc:
        raise EntityVocabularyError(
            f"entity vocabulary file {file_path} failed validation: {exc}"
        ) from exc

    return vocab
