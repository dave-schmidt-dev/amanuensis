# pyright: reportPrivateUsage=false
"""Gate test for INV-14 (Resolution records key off the normalized triple).

Quoting the Phase 2a design spec INV-14 verbatim:

    A ``Resolution`` record's identity is determined by what it resolves
    (the triple) plus what it resolves to (the entity). Two non-superseded
    resolutions for the same triple cannot coexist.

What this gate certifies
------------------------
Three cases:

1. A single resolution for a triple passes: ``latest_resolution_for``
   returns it and no ``ResolutionDuplicateTriple`` is raised.

2. Attempting to add a second distinct non-superseded resolution for the
   same ``(source_id, atom_id, operand_index)`` triple raises
   ``ResolutionDuplicateTriple`` (the ``add_resolution`` guard fires).

3. After superseding the first resolution (writing a ``ResolutionSupersede``
   record that points to a new replacement id), the chain terminal is not
   yet on disk, so ``latest_resolution_for`` returns ``None`` and
   ``add_resolution`` for the replacement succeeds without raising.

Scope
-----
Fixture substrates are hand-built. Gate lives in ``tests/invariants/``
and is wired into ``pytest -m invariants``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._errors import ResolutionDuplicateTriple
from amanuensis.fs._serialize import serialize_yaml
from amanuensis.schemas import AgentAttribution, RoleAttribution
from tests.invariants.conftest import (
    _MAPPINGS_ATOM_ID,
    _MAPPINGS_SOURCE_ID,
    _build_entity,
    _build_resolution,
    _build_resolution_supersede,
)

pytestmark = pytest.mark.invariants

# Stable timestamp / attribution for test-local constructions.
_AT = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)
_AGENT = AgentAttribution(
    kind="llm",
    identifier="claude-opus-4-7",
    role="map-resolve",
)
_RA = RoleAttribution(agent=_AGENT, activity="proposed", at=_AT)


def _setup_workspace(tmp_path: Path) -> Substrate:
    """Create a minimal workspace and return its Substrate."""
    (tmp_path / "amanuensis.yaml").write_text(
        "schema_version: 1\nproject_name: inv14-uniqueness-test\n",
        encoding="utf-8",
    )
    return Substrate(tmp_path)


# ---------------------------------------------------------------------------
# Case 1: Single resolution for a triple passes
# ---------------------------------------------------------------------------


def test_single_resolution_passes(tmp_path: Path) -> None:
    """A single resolution for a triple is accepted and queryable."""
    s = _setup_workspace(tmp_path)

    entity, entity_prov = _build_entity(_RA, _AGENT)
    atomic_write_text(s.mappings_provenance_path(entity_prov.id), serialize_yaml(entity_prov))
    s.add_entity(entity)

    res, prov = _build_resolution(
        _RA,
        _AGENT,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
    )
    atomic_write_text(s.mappings_provenance_path(prov.id), serialize_yaml(prov))
    s.add_resolution(res)  # Must not raise.

    latest = s.latest_resolution_for(_MAPPINGS_SOURCE_ID, _MAPPINGS_ATOM_ID, 0)
    assert latest is not None, "expected a resolution for the triple"
    assert latest.id == res.id


# ---------------------------------------------------------------------------
# Case 2: Duplicate triple raises ResolutionDuplicateTriple
# ---------------------------------------------------------------------------


def test_duplicate_triple_raises(tmp_path: Path) -> None:
    """A second non-superseded resolution for the same triple is rejected."""
    s = _setup_workspace(tmp_path)

    entity, entity_prov = _build_entity(_RA, _AGENT)
    atomic_write_text(s.mappings_provenance_path(entity_prov.id), serialize_yaml(entity_prov))
    s.add_entity(entity)

    # Write the first resolution normally.
    res_v1, prov_v1 = _build_resolution(
        _RA,
        _AGENT,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
        confidence="high",
    )
    atomic_write_text(s.mappings_provenance_path(prov_v1.id), serialize_yaml(prov_v1))
    s.add_resolution(res_v1)

    # Build a second resolution for the same triple (different confidence →
    # different content → different id, but same triple).
    res_v2, prov_v2 = _build_resolution(
        _RA,
        _AGENT,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
        confidence="medium",
    )
    atomic_write_text(s.mappings_provenance_path(prov_v2.id), serialize_yaml(prov_v2))

    with pytest.raises(ResolutionDuplicateTriple):
        s.add_resolution(res_v2)


# ---------------------------------------------------------------------------
# Case 3: After supersede, re-resolving the triple succeeds
# ---------------------------------------------------------------------------


def test_resolves_after_supersede(tmp_path: Path) -> None:
    """After superseding v1 → v2, add_resolution(v2) succeeds.

    Once ``ResolutionSupersede(superseded=v1.id, replacement=v2.id)`` is
    on disk but v2 is not yet, ``latest_resolution_for`` returns ``None``
    (chain terminal not found). ``add_resolution(v2)`` therefore passes
    the duplicate-triple guard and writes v2.
    """
    s = _setup_workspace(tmp_path)

    entity, entity_prov = _build_entity(_RA, _AGENT)
    atomic_write_text(s.mappings_provenance_path(entity_prov.id), serialize_yaml(entity_prov))
    s.add_entity(entity)

    # Write v1 normally.
    res_v1, prov_v1 = _build_resolution(
        _RA,
        _AGENT,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
        confidence="high",
    )
    atomic_write_text(s.mappings_provenance_path(prov_v1.id), serialize_yaml(prov_v1))
    s.add_resolution(res_v1)

    # Build v2 (replacement).
    res_v2, prov_v2 = _build_resolution(
        _RA,
        _AGENT,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
        confidence="medium",
        basis="supervisor override",
    )

    # Write the supersede record: v1 → v2. v2 not yet on disk.
    supersede, sup_prov = _build_resolution_supersede(
        _RA,
        _AGENT,
        superseded_resolution_id=res_v1.id,
        replacement_resolution_id=res_v2.id,
    )
    atomic_write_text(s.mappings_provenance_path(sup_prov.id), serialize_yaml(sup_prov))
    s.add_resolution_supersede(supersede)

    # Chain terminal (v2) not on disk → latest_resolution_for returns None.
    mid_latest = s.latest_resolution_for(_MAPPINGS_SOURCE_ID, _MAPPINGS_ATOM_ID, 0)
    assert mid_latest is None, "expected None before v2 is written (chain terminal not yet on disk)"

    # Now add v2 — duplicate-triple guard must pass.
    atomic_write_text(s.mappings_provenance_path(prov_v2.id), serialize_yaml(prov_v2))
    s.add_resolution(res_v2)  # Must not raise.

    # latest_resolution_for now returns v2.
    final_latest = s.latest_resolution_for(_MAPPINGS_SOURCE_ID, _MAPPINGS_ATOM_ID, 0)
    assert final_latest is not None
    assert final_latest.id == res_v2.id
