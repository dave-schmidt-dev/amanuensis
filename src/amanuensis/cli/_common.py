"""Shared CLI helpers — workspace + vocabulary + distillation discovery.

Centralised so each command module does not re-derive these. Pure
helpers: no Typer / sys-exit / printing; callers translate errors to
user-facing messages.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import yaml

from amanuensis.fs import Substrate
from amanuensis.schemas import (
    OperandTypeSchema,
    Vocabulary,
    VocabularyEntry,
)
from amanuensis.vocabulary import VocabularyLoadError, load_vocabulary


def load_workspace_config(workspace_root: Path) -> dict[str, Any]:
    """Parse ``amanuensis.yaml`` at the workspace root.

    Returns an empty dict if the file is missing (the marker check that
    proves it exists has already run via ``@require_marker``; this
    safety net is for callers that get here independently). Returns an
    empty dict if the file parses to ``None`` (the YAML allows for an
    empty document beyond the marker).
    """
    marker = workspace_root / Substrate.MARKER_FILENAME
    if not marker.is_file():
        return {}
    raw = marker.read_text(encoding="utf-8")
    parsed: Any = yaml.safe_load(raw)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return cast("dict[str, Any]", parsed)


def _placeholder_vocabulary() -> Vocabulary:
    """Single-entry placeholder vocabulary used when no registry resolves.

    Returned as an absolute floor so commands that need a vocabulary
    (e.g. ``ingest``) still work out-of-the-box in a fresh workspace
    that has not configured ``domain.vocabulary_registry``. The bundled
    generic registry should normally fill this role; the placeholder
    fires only when even that is unreachable.
    """
    return Vocabulary(
        name="placeholder",
        version="0.0.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_factual_event",
                aliases=[],
                operand_types=[
                    OperandTypeSchema(name="subject", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="placeholder predicate; configure domain.vocabulary_registry",
            ),
        ],
    )


def _candidate_vocabulary_paths(workspace_root: Path) -> list[Path]:
    """Return vocabulary YAML paths to try, in priority order.

    Priority:
    1. ``domain.vocabulary_registry`` from the workspace's amanuensis.yaml
       (expanded via ``~`` and ``$VAR``); accepts either a file or a
       directory containing ``predicates.yaml``.
    2. The bundled ``vocabularies/generic/predicates.yaml`` at the
       package's source-tree root (relative to this module).
    """
    candidates: list[Path] = []
    config = load_workspace_config(workspace_root)
    domain = config.get("domain")
    if isinstance(domain, dict):
        domain_dict = cast("dict[str, Any]", domain)
        registry_value = domain_dict.get("vocabulary_registry")
        if isinstance(registry_value, str) and registry_value:
            expanded = Path(os.path.expandvars(os.path.expanduser(registry_value)))
            if expanded.is_dir():
                candidates.append(expanded / "predicates.yaml")
            else:
                candidates.append(expanded)

    # Bundled generic vocabulary at <repo>/vocabularies/generic/predicates.yaml.
    # __file__ is src/amanuensis/cli/_common.py → parents[3] = repo root.
    bundled = Path(__file__).resolve().parents[3] / "vocabularies" / "generic" / "predicates.yaml"
    candidates.append(bundled)
    return candidates


def load_active_vocabulary(workspace_root: Path) -> Vocabulary:
    """Resolve the active vocabulary, falling back through the candidate chain.

    Tries each candidate in order; returns the first that loads cleanly.
    If every candidate fails (file missing or unparseable), returns the
    in-memory placeholder so the CLI never hard-fails on a fresh
    workspace.
    """
    for candidate in _candidate_vocabulary_paths(workspace_root):
        if not candidate.is_file():
            continue
        try:
            return load_vocabulary(candidate)
        except VocabularyLoadError:
            # Try the next candidate; the placeholder is the absolute floor.
            continue
    return _placeholder_vocabulary()


def list_distillations(substrate: Substrate) -> list[str]:
    """Return source_ids of distillations on disk (sorted; empty if none)."""
    dist_root = substrate.root / "distillations"
    if not dist_root.is_dir():
        return []
    return sorted(p.name for p in dist_root.iterdir() if p.is_dir())
