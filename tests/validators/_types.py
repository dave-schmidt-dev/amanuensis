"""Shared factory-callable types for ``tests/validators/``.

Lives alongside ``conftest.py`` (not inside it) because ``conftest`` is
loaded by pytest as a discovery-time hook, not as an importable module
along a stable path. Defining the factory aliases here lets test files
import them via ``from tests.validators._types import AtomFactory`` (or
the equivalent relative form) without coupling to pytest's collection
internals.
"""

from __future__ import annotations

from collections.abc import Callable

from amanuensis.schemas import Atom, ProvenanceRecord, Relation

AtomFactory = Callable[..., Atom]
ProvenanceFactory = Callable[..., ProvenanceRecord]
RelationFactory = Callable[..., Relation]
