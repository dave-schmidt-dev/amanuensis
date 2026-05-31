"""T3.6 — latest_entity_for + latest_resolution_for with cycle guard.

Covers:
- Chain depth 5 walks correctly to the terminal entity
- Deliberate cycle in entity chain raises SupersedeCycleDetected
- Chain longer than max_depth raises SupersedeChainTooDeep
- latest_resolution_for returns None when no resolution exists
- latest_resolution_for skips superseded resolutions and returns terminal
- latest_resolution_for raises SupersedeCycleDetected on cycle
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import (
    Substrate,
    SubstrateNotFound,
    SupersedeChainTooDeep,
    SupersedeCycleDetected,
)
from amanuensis.schemas import (
    Entity,
    EntitySupersede,
    Resolution,
    ResolutionSupersede,
    RoleAttribution,
    compute_id,
)
from tests.fs.conftest import make_entity, make_entity_supersede, make_resolution


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


# --- helpers ---------------------------------------------------------


def _entity_chain(
    role_attribution: RoleAttribution,
    *,
    length: int,
    kind: str = "party",
) -> list[Entity]:
    """Build a chain of ``length`` distinct entities (unique names)."""
    entities = []
    for i in range(length):
        name = f"Entity-{i:03d}"
        aliases = [f"alias-{i}"]
        payload: dict[str, Any] = {
            "kind": kind,
            "canonical_name": name,
            "aliases": aliases,
            "notes": None,
            "provenance_id": f"p-chainfix{i:07d}",
            "role_attributions": [role_attribution],
            "schema_version": 1,
        }
        payload["id"] = "e-" + "0" * 16
        draft = Entity(**payload)
        payload["id"] = compute_id(draft)
        entities.append(Entity(**payload))
    return entities


def _write_entity_chain(
    sub: Substrate,
    role_attribution: RoleAttribution,
    entities: list[Entity],
) -> None:
    """Write entities and the supersede chain linking them in order."""
    for ent in entities:
        sub.add_entity(ent)
    for i in range(len(entities) - 1):
        es = make_entity_supersede(role_attribution, entities[i], entities[i + 1])
        sub.add_entity_supersede(es)


# --- entity chain walk -----------------------------------------------


def test_latest_entity_for_depth_1(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    """Single entity with no supersede → returns itself."""
    sub = _new(tmp_workspace)
    chain = _entity_chain(role_attribution, length=1)
    _write_entity_chain(sub, role_attribution, chain)
    result = sub.latest_entity_for(chain[0].id)
    assert result.id == chain[0].id


def test_latest_entity_for_depth_5(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    """Chain of 5 entities → latest_entity_for returns the terminal (index 4)."""
    sub = _new(tmp_workspace)
    chain = _entity_chain(role_attribution, length=5)
    _write_entity_chain(sub, role_attribution, chain)
    result = sub.latest_entity_for(chain[0].id)
    assert result.id == chain[4].id


def test_latest_entity_for_from_middle_of_chain(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Walking from the middle of the chain still reaches the terminal."""
    sub = _new(tmp_workspace)
    chain = _entity_chain(role_attribution, length=5)
    _write_entity_chain(sub, role_attribution, chain)
    result = sub.latest_entity_for(chain[2].id)
    assert result.id == chain[4].id


def test_latest_entity_for_cycle_raises(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """A → B → A cycle raises SupersedeCycleDetected."""
    sub = _new(tmp_workspace)
    ent_a = make_entity(role_attribution, canonical_name="Entity A")
    ent_b = make_entity(role_attribution, canonical_name="Entity B", aliases=["B"])
    sub.add_entity(ent_a)
    sub.add_entity(ent_b)

    # A superseded by B
    es_ab = make_entity_supersede(role_attribution, ent_a, ent_b)
    sub.add_entity_supersede(es_ab)

    # Craft a B→A supersede manually (bypassing add_entity_supersede id check
    # by writing directly to the supersede path).
    cycle_payload: dict[str, Any] = {
        "kind": "entity",
        "superseded_entity_id": ent_b.id,
        "replacement_entity_id": ent_a.id,
        "reason": "deliberate cycle for test",
        "provenance_id": "p-cyclefix0000001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
        "id": "t-" + "0" * 16,
    }
    cycle_draft = EntitySupersede(**cycle_payload)
    cycle_payload["id"] = compute_id(cycle_draft)
    cycle_es = EntitySupersede(**cycle_payload)
    # Write directly so we bypass the duplicate-triple guard (which doesn't
    # exist for supersedes — they're always appendable).
    from amanuensis.fs._atomic import atomic_write_text
    from amanuensis.fs._serialize import serialize_entity_supersede_yaml

    atomic_write_text(
        sub.supersede_path(cycle_es.id),
        serialize_entity_supersede_yaml(cycle_es),
    )

    with pytest.raises(SupersedeCycleDetected):
        sub.latest_entity_for(ent_a.id)


def test_latest_entity_for_chain_too_deep(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Chain longer than max_depth raises SupersedeChainTooDeep."""
    sub = _new(tmp_workspace)
    chain = _entity_chain(role_attribution, length=5)
    _write_entity_chain(sub, role_attribution, chain)
    # max_depth=2 means we allow 3 hops (0,1,2) before raising on depth 3
    with pytest.raises(SupersedeChainTooDeep):
        sub.latest_entity_for(chain[0].id, max_depth=2)


def test_latest_entity_for_missing_terminal_raises(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """If the terminal entity record is missing, SubstrateNotFound is raised."""
    sub = _new(tmp_workspace)
    ent_a = make_entity(role_attribution, canonical_name="Entity A")
    ent_b = make_entity(role_attribution, canonical_name="Entity B", aliases=["B"])
    sub.add_entity(ent_a)
    # ent_b NOT written — only the supersede record pointing to it.
    es = make_entity_supersede(role_attribution, ent_a, ent_b)
    sub.add_entity_supersede(es)
    with pytest.raises(SubstrateNotFound):
        sub.latest_entity_for(ent_a.id)


# --- latest_resolution_for -------------------------------------------


def test_latest_resolution_for_none_when_no_resolution(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    result = sub.latest_resolution_for("src-fixture-001", "a-fixture0001000", 0)
    assert result is None


def test_latest_resolution_for_returns_single_resolution(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)
    res = make_resolution(role_attribution, ent, operand_index=0)
    sub.add_resolution(res)
    result = sub.latest_resolution_for(res.source_id, res.atom_id, res.operand_index)
    assert result is not None
    assert result.id == res.id


def test_latest_resolution_for_skips_superseded(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """After superseding res_old with res_new, latest_resolution_for returns res_new."""
    sub = _new(tmp_workspace)
    ent1 = make_entity(role_attribution, canonical_name="Alpha Ltd.")
    ent2 = make_entity(role_attribution, canonical_name="Beta Inc.", aliases=["Beta"])
    sub.add_entity(ent1)
    sub.add_entity(ent2)

    res_old = make_resolution(role_attribution, ent1, operand_index=0)
    sub.add_resolution(res_old)

    # Build a replacement for the same triple but pointing to ent2.
    # We must write it directly (bypassing add_resolution's duplicate guard
    # since res_old already occupies the triple) then add the supersede.
    res_new_payload: dict[str, Any] = {
        "source_id": res_old.source_id,
        "atom_id": res_old.atom_id,
        "operand_index": res_old.operand_index,
        "entity_id": ent2.id,
        "confidence": "medium",
        "basis": "Supervisor correction.",
        "provenance_id": "p-fixture00000099",
        "role_attributions": [role_attribution],
        "schema_version": 1,
        "id": "j-" + "0" * 16,
    }
    draft_new = Resolution(**res_new_payload)
    res_new_payload["id"] = compute_id(draft_new)
    res_new = Resolution(**res_new_payload)

    # Write res_new directly (bypassing duplicate guard).
    from amanuensis.fs._atomic import atomic_write_text
    from amanuensis.fs._serialize import serialize_resolution_yaml

    atomic_write_text(
        sub.resolution_path(res_new.id),
        serialize_resolution_yaml(res_new),
    )

    # Add a supersede: res_old → res_new
    rs_payload: dict[str, Any] = {
        "kind": "resolution",
        "superseded_resolution_id": res_old.id,
        "replacement_resolution_id": res_new.id,
        "reason": "Supervisor corrected entity mapping.",
        "provenance_id": "p-fixture00000098",
        "role_attributions": [role_attribution],
        "schema_version": 1,
        "id": "s-" + "0" * 16,
    }
    draft_rs = ResolutionSupersede(**rs_payload)
    rs_payload["id"] = compute_id(draft_rs)
    rs = ResolutionSupersede(**rs_payload)
    sub.add_resolution_supersede(rs)

    result = sub.latest_resolution_for(res_old.source_id, res_old.atom_id, res_old.operand_index)
    assert result is not None
    assert result.id == res_new.id


def test_latest_resolution_for_cycle_raises(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Cycle in resolution supersede chain raises SupersedeCycleDetected."""
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)

    res_a = make_resolution(role_attribution, ent, operand_index=0)
    # Write res_a directly (need it on disk but without triggering duplicate guard
    # before creating the cycle).
    from amanuensis.fs._atomic import atomic_write_text
    from amanuensis.fs._serialize import (
        serialize_resolution_supersede_yaml,
        serialize_resolution_yaml,
    )

    atomic_write_text(
        sub.resolution_path(res_a.id),
        serialize_resolution_yaml(res_a),
    )

    # Build a second resolution for a different operand so it can be written.
    res_b = make_resolution(role_attribution, ent, operand_index=1)
    atomic_write_text(
        sub.resolution_path(res_b.id),
        serialize_resolution_yaml(res_b),
    )

    # Create cycle: a→b and b→a supersedes
    def _make_rs(old_id: str, new_id: str, prov: str) -> ResolutionSupersede:
        payload: dict[str, Any] = {
            "kind": "resolution",
            "superseded_resolution_id": old_id,
            "replacement_resolution_id": new_id,
            "reason": "cycle test",
            "provenance_id": prov,
            "role_attributions": [role_attribution],
            "schema_version": 1,
            "id": "s-" + "0" * 16,
        }
        draft = ResolutionSupersede(**payload)
        payload["id"] = compute_id(draft)
        return ResolutionSupersede(**payload)

    rs_ab = _make_rs(res_a.id, res_b.id, "p-cycle0000000001")
    rs_ba = _make_rs(res_b.id, res_a.id, "p-cycle0000000002")
    atomic_write_text(
        sub.supersede_path(rs_ab.id),
        serialize_resolution_supersede_yaml(rs_ab),
    )
    atomic_write_text(
        sub.supersede_path(rs_ba.id),
        serialize_resolution_supersede_yaml(rs_ba),
    )

    with pytest.raises(SupersedeCycleDetected):
        sub.latest_resolution_for(res_a.source_id, res_a.atom_id, res_a.operand_index)
