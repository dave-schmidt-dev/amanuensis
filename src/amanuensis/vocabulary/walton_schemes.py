"""Walton-scheme vocabulary loader (Phase 2c M3 substrate).

A ``WaltonSchemeRegistry`` declares the closed set of Walton argument
schemes (Walton/Reed/Macagno 2008) that the hierarchize substrate
accepts at probandum write-time (INV-18 closed-vocabulary gate). Each
``WaltonScheme`` names one scheme by canonical id plus a human-readable
description.

Mirrors the structural template of
``amanuensis.vocabulary.entity_registry`` so the per-engagement snapshot
discipline (pin once, evolve via ``--extend``) is shared across both
closed vocabularies.

This module provides:

- ``WaltonScheme`` — one scheme registered in a registry.
- ``WaltonSchemeRegistry`` — a versioned collection of schemes.
- ``WaltonSchemeRegistryError`` — raised on load / validation failure.
- ``load_walton_schemes`` — read + validate a registry YAML file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, field_validator


class WaltonScheme(BaseModel):
    """One Walton argument scheme entry.

    ``name`` is the closed-vocabulary id stored on
    ``Probandum.scheme`` (e.g. ``"argument-from-expert-opinion"``).
    ``description`` is the canonical one-line gloss.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str
    description: str


class WaltonSchemeRegistry(BaseModel):
    """A versioned collection of Walton schemes.

    Declares the closed set of schemes accepted at probandum write-time.
    Currently pinned to version 1.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    version: int
    schemes: list[WaltonScheme]

    @field_validator("schemes")
    @classmethod
    def check_unique_names(cls, schemes: list[WaltonScheme]) -> list[WaltonScheme]:
        """Reject duplicate scheme names.

        Each scheme name must be unique within the registry so
        ``has_scheme`` is a total function on the loaded registry.
        """
        names = [s.name for s in schemes]
        if len(set(names)) != len(names):
            seen: set[str] = set()
            for s in schemes:
                if s.name in seen:
                    raise ValueError(f"duplicate Walton scheme name: {s.name!r}")
                seen.add(s.name)
        return schemes

    def has_scheme(self, name: str) -> bool:
        """Return True iff ``name`` matches the ``name`` of some entry."""
        return any(s.name == name for s in self.schemes)


class WaltonSchemeRegistryError(Exception):
    """Raised when a Walton-scheme registry YAML file cannot be loaded.

    Covers three failure classes:

    - YAML parse failure (malformed file).
    - Pydantic schema-validation failure (missing field, wrong type,
      forbidden extra key, etc.).
    - Structural rule failure (duplicate scheme names).

    The original exception is preserved via ``from exc`` to allow
    callers to inspect the root cause if needed.
    """


def load_walton_schemes(path: Path | str) -> WaltonSchemeRegistry:
    """Read + validate a Walton-scheme registry YAML file.

    Performs three checks in order: YAML parse, schema validation
    (Pydantic strict), and structural rules (no duplicate names).

    Args:
        path: The filesystem path to the YAML file.

    Returns:
        A ``WaltonSchemeRegistry`` instance with all validations passed.

    Raises:
        WaltonSchemeRegistryError: If the file cannot be read, parsed
            as YAML, validated against the schema, or contains duplicate
            scheme names.
    """
    file_path = Path(path)

    try:
        raw = file_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise WaltonSchemeRegistryError(
            f"Walton-scheme registry file not found: {file_path}"
        ) from exc
    except OSError as exc:
        raise WaltonSchemeRegistryError(
            f"could not read Walton-scheme registry file {file_path}: {exc}"
        ) from exc

    try:
        parsed_any: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise WaltonSchemeRegistryError(
            f"Walton-scheme registry file {file_path} is not valid YAML: {exc}"
        ) from exc

    if not isinstance(parsed_any, dict):
        raise WaltonSchemeRegistryError(
            f"Walton-scheme registry file {file_path} top-level must be a mapping, "
            f"got {type(parsed_any).__name__}"
        )

    payload = cast("dict[str, Any]", parsed_any)

    try:
        registry = WaltonSchemeRegistry(**payload)
    except Exception as exc:
        raise WaltonSchemeRegistryError(
            f"Walton-scheme registry file {file_path} failed validation: {exc}"
        ) from exc

    return registry
