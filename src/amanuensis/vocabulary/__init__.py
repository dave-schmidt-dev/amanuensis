"""Vocabulary registry loader + lookup helpers.

Public surface:

- ``load_vocabulary`` — read + validate a vocabulary YAML file into a
  ``Vocabulary``. Also reachable as the classmethod ``Vocabulary.load``.
- ``VocabularyLoadError`` — raised when a file fails schema validation
  or violates the structural rules (duplicate predicate / alias
  collision) the closed-vocabulary gate (INV-5) depends on.

INV-5 (closed predicate vocabulary at extraction) and INV-10 (vocabulary
pinned per distillation) jointly require an unambiguous resolution from
any predicate-or-alias string to a single canonical entry. The loader's
duplicate / collision checks are what make ``Vocabulary.has_predicate``
/ ``Vocabulary.resolve`` total functions on the loaded registry.
"""

from .registry import VocabularyLoadError, load_vocabulary

__all__ = [
    "VocabularyLoadError",
    "load_vocabulary",
]
