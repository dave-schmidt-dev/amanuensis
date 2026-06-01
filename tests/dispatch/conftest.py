# pyright: reportUnusedFunction=false, reportUntypedFunctionDecorator=false
"""Shared fixtures for ``tests/dispatch/`` — workspace marker + queue builders.

Phase 2b M4 additions
---------------------
The reconciliation gate for ``CrossDocRelation`` candidates is exercised by
``test_cross_doc_reconcile.py``. Those tests need a workspace pre-seeded with
the Phase 2a substrate state that the INV-15 gate consults — a shared Entity
plus the bilateral Resolutions for both endpoints. The fixtures below build
that scaffolding once so the tests stay focused on the reconciler's behavior.

- ``role_attribution`` / ``agent_attribution`` — stable, deterministic
  attribution records re-used across reconciler-gate tests.
- ``fake_provenance`` — a synthetic ProvenanceRecord with a stable id so
  the reconciler can stamp ``provenance_id`` on the candidates without
  needing a fully-wired Phase 2b prov harness.
- ``tmp_workspace`` — bare workspace with the INV-1 marker.
- ``tmp_workspace_with_bilateral_resolutions`` — workspace where atoms
  ``a-1`` / ``a-2`` are resolved to the same canonical entity ``e-smith``
  via Phase 2a Resolution records. This is the "happy path" precondition
  for INV-15.
- ``tmp_workspace_with_partial_resolutions`` — same as above but with the
  from-endpoint Resolution missing. The INV-15 gate must reject any
  CrossDocRelation built on this workspace; the reconciler should turn the
  rejection into a ``resolution-ambiguous`` clarification.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import (
    serialize_entity_md,
    serialize_resolution_yaml,
    serialize_yaml,
)
from amanuensis.llm import DispatchQueueEntry
from amanuensis.schemas import (
    AgentAttribution,
    Entity,
    ProvenanceRecord,
    Resolution,
    RoleAttribution,
    compute_id,
)

# Stable attribution timestamp; pinned so content-addressable ids that
# embed RoleAttribution.at stay deterministic across runs.
_STABLE_AT = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)

# Constants the bilateral-resolutions fixtures share so the
# CrossDocRelation candidate payloads in the tests can reference matching
# ids without re-deriving them.
SHARED_ENTITY_ID = "e-smith"
FROM_SOURCE_ID = "src-A"
FROM_ATOM_ID = "a-1"
TO_SOURCE_ID = "src-B"
TO_ATOM_ID = "a-2"


@pytest.fixture
def dispatch_workspace(tmp_path: Path) -> Path:
    """An empty tmpdir with the INV-1 marker, ready for dispatch tests."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: dispatch-test\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Empty workspace with the INV-1 marker (no substrate state)."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: dispatch-reconcile-test\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def agent_attribution() -> AgentAttribution:
    """Stable AgentAttribution for the Connector role."""
    return AgentAttribution(
        kind="llm",
        identifier="claude-opus-4-7",
        role="connect",
    )


@pytest.fixture
def role_attribution(agent_attribution: AgentAttribution) -> RoleAttribution:
    """Stable RoleAttribution used by the reconciler tests."""
    return RoleAttribution(
        agent=agent_attribution,
        activity="proposed",
        at=_STABLE_AT,
    )


@pytest.fixture
def fake_provenance(agent_attribution: AgentAttribution) -> ProvenanceRecord:
    """A synthetic ProvenanceRecord with a stable, computed id.

    Stamps ``entity_type="cross-doc-relation"`` so the record is shaped
    like a real Phase 2b PROV pointer. The id is the canonical-form hash
    of the contents so callers can use ``prov.id`` directly without
    further patching.
    """
    payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": "cross-doc-relation",
        "entity_id": "x-placeholder",
        "activity": "connect-reconcile",
        "activity_started_at": _STABLE_AT,
        "activity_ended_at": _STABLE_AT,
        "used_entity_ids": [],
        "was_attributed_to": agent_attribution,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    draft = ProvenanceRecord(**payload)
    payload["id"] = compute_id(draft)
    return ProvenanceRecord(**payload)


# --- Bilateral-resolution fixtures (INV-15 happy path) -----------------


def _plant_entity(workspace: Path, entity: Entity) -> None:
    """Write an Entity directly under ``mappings/entities/`` (bypasses gates)."""
    path = workspace / "mappings" / "entities" / f"{entity.id}.md"
    atomic_write_text(path, serialize_entity_md(entity))


def _plant_resolution(workspace: Path, resolution: Resolution) -> None:
    """Write a Resolution directly under ``mappings/resolutions/`` (bypasses gates)."""
    path = workspace / "mappings" / "resolutions" / f"{resolution.id}.yaml"
    atomic_write_text(path, serialize_resolution_yaml(resolution))


def _plant_distillation_dir(workspace: Path, source_id: str) -> None:
    """Plant an empty distillation directory so ``list_distillations`` finds it."""
    (workspace / "distillations" / source_id).mkdir(parents=True, exist_ok=True)


def _build_shared_entity(role_attribution: RoleAttribution) -> Entity:
    """Build the shared canonical Entity used by both endpoints."""
    return Entity(
        id=SHARED_ENTITY_ID,
        kind="party",
        canonical_name="Smith",
        aliases=[],
        notes=None,
        provenance_id="p-fixture00000000",
        role_attributions=[role_attribution],
        schema_version=1,
    )


def _build_resolution_for(
    *,
    source_id: str,
    atom_id: str,
    entity_id: str,
    role_attribution: RoleAttribution,
    slug: str,
) -> Resolution:
    """Build a Resolution record (literal id; bypasses content-addressability).

    The id is a fixture sentinel, not a real content hash — the INV-15
    gate walks ``mappings/resolutions/`` by path and only cares that the
    ``source_id`` / ``atom_id`` / ``entity_id`` triple is reachable.
    """
    return Resolution(
        id=f"j-fixture-{slug}",
        source_id=source_id,
        atom_id=atom_id,
        operand_index=0,
        entity_id=entity_id,
        confidence="high",
        basis="fixture-planted for cross-doc reconciler test",
        provenance_id="p-fixture00000001",
        role_attributions=[role_attribution],
        schema_version=1,
    )


def _plant_workspace_with_resolutions(
    tmp_path: Path,
    *,
    project_name: str,
    role_attribution: RoleAttribution,
    include_from_resolution: bool,
    include_to_resolution: bool,
) -> Path:
    """Plant a workspace with shared Entity + optional bilateral Resolutions."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        f"schema_version: 1\nproject_name: {project_name}\n",
        encoding="utf-8",
    )
    # Empty distillation dirs so list_distillations sees the sources.
    _plant_distillation_dir(tmp_path, FROM_SOURCE_ID)
    _plant_distillation_dir(tmp_path, TO_SOURCE_ID)

    entity = _build_shared_entity(role_attribution)
    _plant_entity(tmp_path, entity)
    if include_from_resolution:
        _plant_resolution(
            tmp_path,
            _build_resolution_for(
                source_id=FROM_SOURCE_ID,
                atom_id=FROM_ATOM_ID,
                entity_id=SHARED_ENTITY_ID,
                role_attribution=role_attribution,
                slug="from",
            ),
        )
    if include_to_resolution:
        _plant_resolution(
            tmp_path,
            _build_resolution_for(
                source_id=TO_SOURCE_ID,
                atom_id=TO_ATOM_ID,
                entity_id=SHARED_ENTITY_ID,
                role_attribution=role_attribution,
                slug="to",
            ),
        )
    return tmp_path


@pytest.fixture
def tmp_workspace_with_bilateral_resolutions(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace where atoms ``a-1`` / ``a-2`` are bilaterally resolved to ``e-smith``.

    Satisfies the INV-15 gate's preconditions for a CrossDocRelation
    between ``(src-A, a-1)`` and ``(src-B, a-2)`` listing ``e-smith`` as
    the shared entity.
    """
    return _plant_workspace_with_resolutions(
        tmp_path,
        project_name="m4-bilateral",
        role_attribution=role_attribution,
        include_from_resolution=True,
        include_to_resolution=True,
    )


@pytest.fixture
def tmp_workspace_with_partial_resolutions(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace where only the to-endpoint atom (``a-2``) is resolved to ``e-smith``.

    The from-endpoint Resolution is intentionally absent. The INV-15 gate
    must reject a CrossDocRelation built on this state; the reconciler
    must convert the rejection into a ``resolution-ambiguous`` clarification.
    """
    return _plant_workspace_with_resolutions(
        tmp_path,
        project_name="m4-partial",
        role_attribution=role_attribution,
        include_from_resolution=False,
        include_to_resolution=True,
    )


# --- Per-source clarification listing helper ---------------------------


def list_open_clarifications_for_source(
    substrate: Substrate, source_id: str, kind: str | None = None
) -> list[Any]:
    """Yield open Clarifications filed under ``distillations/<source_id>/``.

    ``Substrate.list_clarifications`` walks every distillation; this
    helper filters down to a single source by re-reading the per-source
    directory directly. Used in tests to assert on the ambiguous-
    clarification raise path.
    """
    from amanuensis.fs._serialize import parse_clarification_md

    bucket_dir = substrate.root / "distillations" / source_id / "clarifications" / "open"
    if not bucket_dir.is_dir():
        return []
    out: list[Any] = []
    for path in sorted(bucket_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".md") or ".tmp." in path.name:
            continue
        clar = parse_clarification_md(path.read_text(encoding="utf-8"))
        if kind is not None and clar.kind != kind:
            continue
        out.append(clar)
    return out


def make_entry(
    *,
    role: str = "extractor",
    prompt: str = "Extract atoms.",
    inputs: dict[str, object] | None = None,
    model_id: str = "claude-opus-4-7",
    inputs_hash: str | None = None,
) -> DispatchQueueEntry:
    """Build a syntactically-valid DispatchQueueEntry for protocol tests.

    ``inputs_hash`` is the cache key; tests usually pin a fake one so
    they can assert on canonical paths without having to recompute the
    SHA-256 of canonicalised inputs.
    """
    return DispatchQueueEntry(
        role=role,
        prompt=prompt,
        inputs=inputs or {"source_id": "fixture-src"},
        model_id=model_id,
        inputs_hash=inputs_hash or ("a" * 64),
        enqueued_at=datetime.now(UTC),
    )


# Public reuse by tests.
_ = serialize_yaml  # silence unused-import warnings in some pyright passes
