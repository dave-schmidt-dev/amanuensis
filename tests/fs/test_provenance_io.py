"""Round-trip + not-found semantics for ``Substrate.get_provenance``.

Added in M2.4 alongside the ``provenance_completeness`` validator: the
validator needs a substrate-blessed read path for ProvenanceRecord
files. ``get_provenance`` mirrors ``get_atom`` (lookup by canonical
path; raise ``SubstrateNotFound`` if absent).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import Substrate, SubstrateNotFound
from amanuensis.schemas import ProvenanceRecord


def test_get_provenance_round_trip(tmp_workspace: Path, provenance: ProvenanceRecord) -> None:
    sub = Substrate(tmp_workspace)
    sub.add_provenance("src-fixture-001", provenance)
    loaded = sub.get_provenance("src-fixture-001", provenance.id)
    assert loaded == provenance


def test_get_provenance_raises_substrate_not_found(tmp_workspace: Path) -> None:
    sub = Substrate(tmp_workspace)
    with pytest.raises(SubstrateNotFound):
        sub.get_provenance("src-fixture-001", "p-does-not-exist")
