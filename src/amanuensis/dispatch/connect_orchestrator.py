"""Cluster enumeration + dispatch enqueue for the Phase 2b Connector phase.

The Connector role is cross-doc only: it proposes ``CrossDocRelation``
candidates between atoms in DIFFERENT distillations that share a
canonical entity. This module is the orchestrator-side half of the
Connect phase — the upstream of the M5 reconciler (which lives in
``dispatch/reconcile.py``).

Phase shape
-----------
1. :func:`enumerate_connect_clusters` walks the substrate, groups
   resolved atoms by canonical entity, and yields one
   :class:`ConnectCluster` per entity whose atoms span ≥2 distinct
   sources. Non-terminal entities (those superseded by another) are
   skipped — the cluster surface is the canonical merged identity.
2. :func:`enqueue_connect_clusters` writes one dispatch queue entry
   per cluster, content-addressable by an ``inputs_hash`` derived from
   the cluster's canonical form. Re-enqueueing identical clusters is a
   byte-identical overwrite of the existing queue entry (idempotent).
3. :func:`run_connect_phase` drives the phase end-to-end: enumerate →
   enqueue → reconcile. (The driver-side harness invocation is deferred
   to first-engagement, mirroring Phase 2a's M11.2 contract — the
   queue entries are written but real-LLM dispatch happens via
   ``amanuensis dispatch`` and the supervisor's harness.)

What this module is NOT
-----------------------
- It does not invoke an LLM harness. The driver lives in
  ``dispatch/driver.py`` (M6.2 surface for Phase 1) and is unchanged
  by Phase 2b — connect outputs are consumed via the same generic
  output-discovery path as map outputs.
- It does not write CrossDocRelation records. That's the reconciler's
  job (``_process_connect_output`` in ``dispatch/reconcile.py``).
- It does not enforce INV-15 at enqueue time — INV-15 is a substrate
  invariant the gate enforces on write. The orchestrator just gathers
  the candidate work.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from amanuensis.dispatch.queue import enqueue
from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import Substrate
from amanuensis.fs._errors import (
    SubstrateNotFound,
    SupersedeChainTooDeep,
    SupersedeCycleDetected,
)
from amanuensis.llm.queue import DispatchQueueEntry

__all__ = [
    "ConnectCluster",
    "ConnectPhaseReport",
    "enqueue_connect_clusters",
    "enumerate_connect_clusters",
    "run_connect_phase",
]


# Default harness model id for the connect-role queue entries. Mirrors
# the map-resolve / map-audit default in ``cli/map.py``.
_DEFAULT_MODEL_ID: str = "claude-opus-4-7"


@dataclass(frozen=True)
class ConnectCluster:
    """One canonical-entity cluster of atoms to send to the Connector role.

    Attributes:
        entity_id: Terminal (post-supersede) canonical entity id.
        entity_kind: The entity's kind (drawn from the vocabulary
            snapshot; passed through unchanged).
        atoms: Per-atom payloads carrying ``atom_id``, ``source_id``,
            ``text`` (the atom's narrative), ``predicate``, and
            ``operand_refs`` (a list of operand dicts the Connector can
            inspect when deciding whether two atoms refer to the same
            real-world claim).
    """

    entity_id: str
    entity_kind: str
    atoms: list[dict[str, Any]]


@dataclass(slots=True)
class ConnectPhaseReport:
    """Structured outcome of one :func:`run_connect_phase` invocation.

    Attributes:
        enqueued: Number of dispatch queue entries written.
        outputs_consumed: Number of connect-role outputs the reconciler
            moved into ``dispatch/outputs/_consumed/`` during the phase.
        relations_committed: List of ``CrossDocRelation`` ids the
            reconciler committed during the phase (empty when the
            driver hasn't run yet — first-engagement mode).
        clarifications_raised: List of clarification ids the reconciler
            raised (typically resolution-ambiguous; INV-15 misses).
        errors: ``(path, reason)`` pairs surfaced by the reconciler for
            outputs that failed to process.
    """

    enqueued: int = 0
    outputs_consumed: int = 0
    relations_committed: list[str] = field(default_factory=list)
    clarifications_raised: list[str] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# T6.1 — cluster enumeration
# ---------------------------------------------------------------------------


def enumerate_connect_clusters(substrate: Substrate) -> Iterator[ConnectCluster]:
    """Yield one :class:`ConnectCluster` per multi-source canonical entity.

    Walks ``mappings/entities`` and, for each entity that is the terminal
    in its supersede chain, gathers every ``Resolution`` pointing at it.
    Atoms referenced by those resolutions are dereferenced via
    :meth:`Substrate.get_atom`; the resulting list is emitted as the
    cluster's ``atoms`` payload.

    Filters:
        - Entities superseded by another entity are skipped (the cluster
          surface is always the canonical merged identity).
        - Clusters with fewer than 2 atoms are skipped (a single atom has
          no within-cluster pair).
        - Clusters whose atoms come from a single ``source_id`` are
          skipped (the Connector role is cross-doc only — INV per
          ``map_connect.md``).

    Determinism:
        Entities are iterated in lexicographic ``entity_id`` order so the
        emitted cluster order is stable across runs.

    Args:
        substrate: A bound ``Substrate`` handle for the workspace.

    Yields:
        :class:`ConnectCluster` records, one per qualifying entity.
    """
    for entity in sorted(substrate.list_entities(), key=lambda e: e.id):
        # Skip non-terminal entities (superseded by another via t-* records).
        try:
            terminus = substrate.latest_entity_for(entity.id)
        except (SubstrateNotFound, SupersedeCycleDetected, SupersedeChainTooDeep):
            # Defensive: a corrupt supersede chain should not poison the
            # whole enumeration. Skip this entity; the operator can fix
            # the chain via `amanuensis map entity show` and re-run.
            continue
        if terminus.id != entity.id:
            continue  # entity is superseded; its cluster lives under the terminus

        atoms: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        for res in substrate.list_resolutions(where_entity_id=entity.id):
            try:
                atom = substrate.get_atom(res.source_id, res.atom_id)
            except SubstrateNotFound:
                # The resolution points at an atom that's no longer on
                # disk — surface nothing and continue. (Should be rare;
                # the reconciler holds the flock during its own writes.)
                continue
            atoms.append(
                {
                    "atom_id": atom.id,
                    "source_id": atom.source_id,
                    "text": atom.narrative,
                    "predicate": atom.predicate,
                    "operand_refs": [op.model_dump(mode="python") for op in atom.operands],
                }
            )
            seen_sources.add(atom.source_id)

        if len(atoms) < 2 or len(seen_sources) < 2:
            continue

        # Sort atoms inside the cluster by (source_id, atom_id) so the
        # downstream inputs_hash is stable across re-runs that touch
        # resolutions in a different filesystem-iter order.
        atoms.sort(key=lambda a: (a["source_id"], a["atom_id"]))

        yield ConnectCluster(
            entity_id=entity.id,
            entity_kind=entity.kind,
            atoms=atoms,
        )


# ---------------------------------------------------------------------------
# T6.2 — per-cluster enqueue
# ---------------------------------------------------------------------------


def _cluster_inputs_hash(cluster: ConnectCluster) -> str:
    """Content-addressable hash of a cluster's canonical form.

    The hash covers entity_id + entity_kind + every atom payload in
    sorted (source_id, atom_id) order. Two calls with byte-identical
    cluster content produce identical hashes; any change to an atom's
    narrative / predicate / operand list flips the hash and forces a
    fresh dispatch event.

    Why this isn't the substrate-state digest the map-resolve hash
    uses: the connect phase is per-entity, not per-workspace. A change
    to one entity's atoms must not invalidate the cache for every other
    entity's already-dispatched cluster.
    """
    canonical = json.dumps(
        {
            "entity_id": cluster.entity_id,
            "entity_kind": cluster.entity_kind,
            "atoms": cluster.atoms,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _load_connect_skill_prompt() -> str:
    """Return the ``map_connect.md`` skill body for embedding in the queue entry."""
    return (
        resources.files("amanuensis.skills").joinpath("map_connect.md").read_text(encoding="utf-8")
    )


def enqueue_connect_clusters(substrate: Substrate) -> int:
    """Enumerate every multi-source cluster and write one queue entry each.

    Each queue entry's payload carries the cluster shape the Connector
    role consumes (``entity_id``, ``entity_kind``, ``atoms``). The
    ``inputs_hash`` is the canonical-form hash of the cluster so re-runs
    of identical clusters are byte-identical writes (idempotent at the
    queue-entry layer; the cache layer keys on the same hash so the
    driver short-circuits on a second invocation).

    Args:
        substrate: A bound ``Substrate`` handle for the workspace.

    Returns:
        The number of clusters enqueued. ``0`` when the substrate has
        no multi-source clusters (e.g., empty workspace, all clusters
        single-source).
    """
    prompt_body = _load_connect_skill_prompt()
    now = datetime.now(UTC)
    count = 0
    for cluster in enumerate_connect_clusters(substrate):
        inputs_hash = _cluster_inputs_hash(cluster)
        entry = DispatchQueueEntry(
            role="connect",
            prompt=prompt_body,
            inputs={
                "entity_id": cluster.entity_id,
                "entity_kind": cluster.entity_kind,
                "atoms": cluster.atoms,
            },
            model_id=_DEFAULT_MODEL_ID,
            inputs_hash=inputs_hash,
            enqueued_at=now,
        )
        enqueue(substrate.root, entry)
        count += 1
    return count


# ---------------------------------------------------------------------------
# T6.3 — phase orchestrator
# ---------------------------------------------------------------------------


def run_connect_phase(substrate: Substrate) -> ConnectPhaseReport:
    """Drive the full Connect phase: enumerate → enqueue → reconcile.

    The phase is split into two distinct halves:

    - **Enqueue**: one queue entry per multi-source cluster, content-
      addressable by ``inputs_hash``. Always runs; idempotent on
      identical substrate state.
    - **Reconcile**: drain any ``dispatch/outputs/connect-*/output.yaml``
      files into the substrate. Only does work if a previous dispatch
      driver run (or a test fixture) placed outputs there.

    Real-LLM dispatch is the supervisor's responsibility via
    ``amanuensis dispatch`` between phases — this mirrors Phase 2a's
    first-engagement contract (queue entries are written; the operator
    drives the harness; outputs land in ``dispatch/outputs/``; the next
    phase invocation reconciles them).

    Args:
        substrate: A bound ``Substrate`` handle for the workspace.

    Returns:
        A populated :class:`ConnectPhaseReport`.
    """
    enqueued = enqueue_connect_clusters(substrate)
    reconcile_result = reconcile_outputs(
        substrate=substrate,
        workspace_root=substrate.root,
    )
    # Filter reconcile counters down to the connect role: ``reconcile_outputs``
    # drains EVERY pending output, so we count just the connect-role
    # consumption for the phase report.
    connect_consumed = [
        p for p in reconcile_result.outputs_consumed if p.parent.name.startswith("connect-")
    ]
    return ConnectPhaseReport(
        enqueued=enqueued,
        outputs_consumed=len(connect_consumed),
        relations_committed=list(reconcile_result.relations_committed),
        clarifications_raised=list(reconcile_result.clarifications_raised),
        errors=list(reconcile_result.errors),
    )
