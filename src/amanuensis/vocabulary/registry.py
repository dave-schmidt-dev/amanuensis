"""Vocabulary loader + lookup helpers (INV-5 + INV-10 substrate).

Two responsibilities collected here:

1. **Load + structurally validate a vocabulary YAML file.** Beyond
   schema validation (Pydantic strict, ``extra="forbid"``), the loader
   enforces the two structural rules the closed-vocabulary gate (INV-5)
   needs in order to make ``has_predicate`` / ``resolve`` total
   functions on the registry:

   - No duplicate canonical predicates.
   - Aliases are globally unambiguous: an alias declared on entry A
     must not equal another entry's canonical predicate, and the same
     alias must not appear on two different entries.

2. **Provide alias-aware lookup** on ``Vocabulary`` via three methods
   attached to the schema class (``has_predicate``, ``resolve``,
   ``entries_by_predicate``). Validators in M2.4 will route every
   predicate check through these to ensure the snapshot is the source
   of truth (INV-10).

The module is pure with respect to substrate state: ``load`` reads a
single file path; it never traverses the workspace or writes anything.
Snapshot-write semantics live in ``amanuensis.fs.substrate``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from amanuensis.schemas import Vocabulary


class VocabularyLoadError(Exception):
    """Raised when a vocabulary YAML file cannot be loaded into a
    validated ``Vocabulary``.

    Covers three failure classes:

    - YAML parse failure (malformed file).
    - Pydantic schema-validation failure (missing field, wrong type,
      forbidden extra key, etc.).
    - Structural rule failure (duplicate canonical predicate, alias
      collision with another entry's predicate or alias).

    The message always includes the offending file path so callers can
    surface it to users without re-stringifying the exception.
    """


def load_vocabulary(path: Path | str) -> Vocabulary:
    """Read + validate a vocabulary YAML file into a ``Vocabulary``.

    Performs three checks in order: YAML parse, schema validation,
    structural rules (no duplicate predicates; aliases unambiguous).
    The structural checks are what the ``has_predicate`` / ``resolve``
    helpers depend on — without them lookups become ambiguous and the
    closed-vocabulary gate (INV-5) cannot be enforced deterministically.
    """
    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VocabularyLoadError(f"could not read vocabulary file {file_path}: {exc}") from exc
    try:
        parsed_any: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise VocabularyLoadError(f"vocabulary file {file_path} is not valid YAML: {exc}") from exc
    if not isinstance(parsed_any, dict):
        raise VocabularyLoadError(
            f"vocabulary file {file_path} top-level must be a mapping, "
            f"got {type(parsed_any).__name__}"
        )
    payload = cast("dict[str, Any]", parsed_any)
    try:
        vocab = Vocabulary(**payload)
    except ValidationError as exc:
        raise VocabularyLoadError(
            f"vocabulary file {file_path} failed schema validation: {exc}"
        ) from exc
    _check_structural_rules(vocab, file_path)
    return vocab


def _check_structural_rules(vocab: Vocabulary, file_path: Path) -> None:
    """Enforce uniqueness of canonical predicates and alias unambiguity.

    Three errors are detectable here that schema validation cannot catch:

    - An entry whose own ``aliases`` list contains duplicates (the same
      alias declared twice on a single entry — checked first so the
      message names the specific predicate/alias rather than mis-blaming
      a cross-entry collision).
    - Two entries with the same ``predicate`` (silent shadowing).
    - An alias on entry A that collides with another entry's canonical
      predicate or alias (ambiguous resolution).
    """
    # Within-entry alias duplicates first — most specific error message.
    for entry in vocab.entries:
        if len(set(entry.aliases)) != len(entry.aliases):
            seen_aliases: set[str] = set()
            for alias in entry.aliases:
                if alias in seen_aliases:
                    raise VocabularyLoadError(
                        f"vocabulary file {file_path}: entry "
                        f"{entry.predicate!r} declares alias {alias!r} "
                        "more than once"
                    )
                seen_aliases.add(alias)

    seen_predicates: set[str] = set()
    for entry in vocab.entries:
        if entry.predicate in seen_predicates:
            raise VocabularyLoadError(
                f"vocabulary file {file_path}: duplicate predicate "
                f"{entry.predicate!r} appears in more than one entry"
            )
        seen_predicates.add(entry.predicate)

    # Aliases must not collide with any canonical predicate (including
    # their own entry's, which would be redundant), nor with another
    # entry's alias. We track every "claimed name" with the entry that
    # claims it and refuse double-claims.
    claimed: dict[str, str] = {}  # name -> "predicate=<p>" or "alias of <p>"
    for entry in vocab.entries:
        claimed[entry.predicate] = f"predicate={entry.predicate}"
    for entry in vocab.entries:
        for alias in entry.aliases:
            if alias == entry.predicate:
                raise VocabularyLoadError(
                    f"vocabulary file {file_path}: entry "
                    f"{entry.predicate!r} lists its own predicate as an alias"
                )
            existing = claimed.get(alias)
            if existing is not None:
                raise VocabularyLoadError(
                    f"vocabulary file {file_path}: alias {alias!r} on "
                    f"entry {entry.predicate!r} collides with {existing}"
                )
            claimed[alias] = f"alias of {entry.predicate}"
