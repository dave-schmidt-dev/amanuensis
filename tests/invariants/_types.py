"""Shared factory-callable types for ``tests/invariants/``.

Mirrors the pattern in ``tests/validators/_types.py``: factory aliases
live alongside ``conftest.py`` (not inside it) because conftest is
loaded by pytest as a discovery-time hook, not as an importable module
along a stable path.
"""

from __future__ import annotations

from collections.abc import Callable

from amanuensis.schemas import Atom, ProvenanceRecord

MatchedAtomFactory = Callable[..., tuple[Atom, ProvenanceRecord]]
