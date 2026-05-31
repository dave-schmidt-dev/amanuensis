# pyright: reportPrivateUsage=false
"""Gate test for INV-13 (Entity and Resolution records are immutable).

Quoting the Phase 2a design spec INV-13 verbatim:

    Once written, ``Entity`` / ``Resolution`` records are not rewritten.
    ``EntitySupersede`` / ``ResolutionSupersede`` records carry corrections
    with PROV.

What this gate certifies
------------------------
Four cases:

1. ``add_entity`` is idempotent for identical content (same canonical form
   written twice does not raise).

2. ``add_entity`` raises ``MutationOfImmutableRecord`` when a different
   entity (different non-volatile content) is forged on disk at the same
   path as an existing entity, then the original entity is re-added via
   the Substrate API. The existing forged content diverges from the
   incoming entity, so the guard fires.

3. ``add_resolution`` is idempotent for identical content (same resolution
   written twice does not raise).

4. A supersede chain allows corrections without triggering the immutability
   guard: a ``ResolutionSupersede`` is written for the first resolution,
   and the substrate's ``latest_resolution_for`` walker correctly returns
   the replacement.

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
from amanuensis.fs._errors import MutationOfImmutableRecord
from amanuensis.fs._serialize import serialize_entity_md, serialize_yaml
from amanuensis.schemas import AgentAttribution, RoleAttribution
from tests.invariants.conftest import (
    _MAPPINGS_ATOM_ID,
    _MAPPINGS_SOURCE_ID,
    _build_entity,
    _build_resolution,
    _build_resolution_supersede,
)

pytestmark = pytest.mark.invariants

# Stable timestamp for all test-local constructions.
_AT = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)

# Shared test-local attribution helpers — same shape as conftest fixtures.
_AGENT = AgentAttribution(
    kind="llm",
    identifier="claude-opus-4-7",
    role="map-resolve",
)
_RA = RoleAttribution(agent=_AGENT, activity="proposed", at=_AT)


# ---------------------------------------------------------------------------
# Case 1: add_entity idempotent for identical content
# ---------------------------------------------------------------------------


def test_entity_add_idempotent(populated_mappings_workspace: Path) -> None:
    """add_entity is a no-op on second write of identical content."""
    s = Substrate(populated_mappings_workspace)
    entities_before = list(s.list_entities())
    assert len(entities_before) == 1, f"expected 1 entity, got {entities_before!r}"

    entity = entities_before[0]
    # Re-adding the same entity must not raise.
    s.add_entity(entity)
    entities_after = list(s.list_entities())
    assert len(entities_after) == 1, "add_entity duplicated the entity"


# ---------------------------------------------------------------------------
# Case 2: add_entity raises MutationOfImmutableRecord on content change
# ---------------------------------------------------------------------------


def test_entity_mutation_raises(tmp_path: Path) -> None:
    """add_entity raises MutationOfImmutableRecord when on-disk content diverges.

    Strategy:
    - Build entity_v1 with kind="organization" and write it via the
      substrate normally.
    - Forge entity_v1's on-disk file with kind="person" directly
      (bypassing the substrate guard via atomic_write_text + model_copy).
    - Call substrate.add_entity(entity_v1): the id check passes (v1's id
      matches its own content), but the on-disk file now has kind="person",
      so the non-volatile comparison fires MutationOfImmutableRecord.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: inv13-mutation-test\n",
        encoding="utf-8",
    )
    s = Substrate(tmp_path)

    # Build and write entity_v1 normally.
    entity_v1, prov_v1 = _build_entity(_RA, _AGENT, kind="organization")
    atomic_write_text(s.mappings_provenance_path(prov_v1.id), serialize_yaml(prov_v1))
    s.add_entity(entity_v1)

    # Forge the on-disk file: same id, different non-volatile field (kind).
    forged = entity_v1.model_copy(update={"kind": "person"})
    atomic_write_text(s.entity_path(entity_v1.id), serialize_entity_md(forged))

    # Re-adding entity_v1 (id matches its own hash) against forged disk content
    # must raise MutationOfImmutableRecord.
    with pytest.raises(MutationOfImmutableRecord):
        s.add_entity(entity_v1)


# ---------------------------------------------------------------------------
# Case 3: add_resolution idempotent for identical content
# ---------------------------------------------------------------------------


def test_resolution_add_idempotent(populated_mappings_workspace: Path) -> None:
    """add_resolution is a no-op on second write of identical content."""
    s = Substrate(populated_mappings_workspace)
    resolutions_before = list(s.list_resolutions())
    assert len(resolutions_before) == 1, f"expected 1 resolution, got {resolutions_before!r}"

    resolution = resolutions_before[0]
    # Re-adding the same resolution must not raise.
    s.add_resolution(resolution)
    resolutions_after = list(s.list_resolutions())
    assert len(resolutions_after) == 1, "add_resolution duplicated the resolution"


# ---------------------------------------------------------------------------
# Case 4: supersede chain allows corrections without triggering mutation guard
# ---------------------------------------------------------------------------


def test_supersede_chain_allows_correction(tmp_path: Path) -> None:
    """A ResolutionSupersede corrects a resolution without hitting the immutability guard.

    Writes resolution_v1, adds a ResolutionSupersede pointing to
    resolution_v2, then verifies that latest_resolution_for returns v2.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: inv13-supersede-test\n",
        encoding="utf-8",
    )
    s = Substrate(tmp_path)

    # Build entity first.
    entity, entity_prov = _build_entity(_RA, _AGENT)
    atomic_write_text(s.mappings_provenance_path(entity_prov.id), serialize_yaml(entity_prov))
    s.add_entity(entity)

    # Write resolution_v1 (confidence=high).
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

    # Write resolution_v2 (different basis) directly — bypasses duplicate-triple guard.
    res_v2, prov_v2 = _build_resolution(
        _RA,
        _AGENT,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
        confidence="medium",
        basis="supervisor override",
    )
    atomic_write_text(s.mappings_provenance_path(prov_v2.id), serialize_yaml(prov_v2))
    atomic_write_text(s.resolution_path(res_v2.id), serialize_yaml(res_v2))

    # Write the supersede record: v1 → v2.
    supersede, sup_prov = _build_resolution_supersede(
        _RA,
        _AGENT,
        superseded_resolution_id=res_v1.id,
        replacement_resolution_id=res_v2.id,
    )
    atomic_write_text(s.mappings_provenance_path(sup_prov.id), serialize_yaml(sup_prov))
    s.add_resolution_supersede(supersede)

    # latest_resolution_for must return v2 (v1 is superseded).
    latest = s.latest_resolution_for(_MAPPINGS_SOURCE_ID, _MAPPINGS_ATOM_ID, operand_index=0)
    assert latest is not None, "expected a non-None latest resolution"
    assert latest.id == res_v2.id, (
        f"expected latest resolution to be {res_v2.id!r}, got {latest.id!r}"
    )
    # v1 is still on disk (immutable — not deleted).
    assert s.resolution_path(res_v1.id).is_file(), (
        "resolution v1 should still exist on disk (immutability: no deletion)"
    )
