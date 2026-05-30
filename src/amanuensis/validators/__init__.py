"""Canonical validators for the amanuensis distillation substrate.

Each validator is a pure function returning a ``ValidationResult`` that
names itself. Together they codify the project's named structural
checks plus the four numbered invariants directly enforceable on a
single artifact:

- ``schema_check`` — payload conforms to its Pydantic model.
- ``citation_ledger`` — Atom carries a well-formed citation four-tuple
  (INV-7).
- ``universe_check`` — Atom's ``source_id`` is in the set of known
  source-mirror documents.
- ``scale_anchor`` — Atom's ``scale_anchor`` is in the closed INV-6 set.
- ``closed_vocabulary`` — Atom's ``predicate`` is in the (snapshot)
  vocabulary (INV-5; callers must pass the per-distillation snapshot per
  INV-10).
- ``provenance_completeness`` — Atom's provenance pointer resolves to a
  matching PROV-O record (INV-3).
- ``lineage_closure`` — both atoms a Relation references exist on the
  substrate.

Downstream consumers (Auditor skill in M7, CLI in M4) import these
validators by name from this package. The ``ValidationResult`` shape is
uniform across all seven so aggregator surfaces can render uniformly.
"""

from ._result import ValidationResult
from .citation_ledger import citation_ledger
from .closed_vocabulary import closed_vocabulary
from .lineage_closure import lineage_closure
from .provenance_completeness import provenance_completeness
from .scale_anchor import scale_anchor
from .schema_check import schema_check
from .universe_check import universe_check

__all__ = [
    "ValidationResult",
    "citation_ledger",
    "closed_vocabulary",
    "lineage_closure",
    "provenance_completeness",
    "scale_anchor",
    "schema_check",
    "universe_check",
]
