"""Cluster enumeration + dispatch enqueue for the Phase 2c Hierarchize phase.

The Hierarchize role proposes ``Probandum`` records of ``kind="interim"``
plus ``ProbandumEdge`` records that fan out beneath a parent
**penultimate** probandum in a Wigmore argument tree. This module is the
orchestrator-side half of the M7 reconciler (``_process_hierarchize_output``
in ``dispatch/reconcile.py``).

Phase shape
-----------
1. :func:`enumerate_hierarchize_clusters` walks the substrate, locates
   every penultimate probandum that has at least one child (atom,
   cross-doc-relation, or interim probandum) attached via an outgoing
   probandum-edge, and yields one :class:`HierarchizeCluster` per
   penultimate. Orphan penultimates (no upward path to an ``ultimate``)
   are skipped — the reconciler will eventually clarify them via a
   ``lineage-incomplete`` clarification raised by the auditor.
2. :func:`enqueue_hierarchize_clusters` writes one dispatch queue entry
   per cluster, content-addressable by an ``inputs_hash`` derived from
   the cluster's canonical form.
3. :func:`run_hierarchize_phase` drives the phase end-to-end: enumerate
   → enqueue → reconcile. Real-LLM dispatch is deferred to the
   supervisor's ``amanuensis dispatch`` invocation between phases,
   mirroring the Phase 2a/2b first-engagement contract.

What this module is NOT
-----------------------
- It does not invoke an LLM harness. The driver lives in
  ``dispatch/driver.py`` and consumes whatever the queue + harness
  produces; reconciliation lives in ``dispatch/reconcile.py``.
- It does not write ``Probandum`` or ``ProbandumEdge`` records.
  That's the reconciler's job
  (``_process_hierarchize_output``).
- It does not enforce INV-16/17/18 at enqueue time — those are
  substrate invariants the gate enforces on write. The orchestrator
  just gathers the candidate work.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources
from typing import Any

from amanuensis.dispatch.queue import enqueue
from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import Substrate
from amanuensis.fs._errors import SubstrateNotFound
from amanuensis.llm.queue import DispatchQueueEntry

__all__ = [
    "HierarchizeCluster",
    "HierarchizePhaseReport",
    "enqueue_hierarchize_clusters",
    "enumerate_hierarchize_clusters",
    "run_hierarchize_phase",
]


# Default harness model id for hierarchize-role queue entries. Mirrors
# the map-resolve / map-audit / connect defaults.
_DEFAULT_MODEL_ID: str = "claude-opus-4-7"


@dataclass(frozen=True)
class HierarchizeCluster:
    """One penultimate-anchored cluster of evidence to send to the Hierarchize role.

    Attributes:
        parent_probandum_id: The penultimate probandum's substrate id.
        parent_statement: The penultimate's statement text (verbatim).
        ultimate_probandum: ``{"id": <ultimate-id>, "statement":
            <ultimate-statement>}`` for the first ``ultimate`` reached
            by walking incoming probandum-edges from the penultimate.
        candidate_evidence: A list of dicts describing existing children
            already attached to the penultimate. Mixed kinds:
            atoms (``{"kind": "atom", ...}``), cross-doc relations
            (``{"kind": "cross-doc-relation", ...}``), and interim
            probanda (``{"kind": "probandum", ...}``).
        walton_schemes: Closed-vocabulary scheme names (strings) loaded
            from the active Walton snapshot at enumeration time.
    """

    parent_probandum_id: str
    parent_statement: str
    ultimate_probandum: dict[str, Any]
    candidate_evidence: list[dict[str, Any]]
    walton_schemes: list[str]


@dataclass(slots=True)
class HierarchizePhaseReport:
    """Structured outcome of one :func:`run_hierarchize_phase` invocation.

    Attributes:
        enqueued: Number of dispatch queue entries written.
        probanda_committed: Ids of ``Probandum`` records committed by
            the hierarchize-role reconciler during the phase.
        edges_committed: Ids of ``ProbandumEdge`` records committed by
            the hierarchize-role reconciler.
        clarifications_raised: Ids of clarifications auto-raised by
            the hierarchize-role reconcile path (INV-17 lineage
            failures, INV-18 scheme-missing rejections).
        outputs_consumed: Number of hierarchize-role outputs the
            reconciler moved into ``dispatch/outputs/_consumed/``
            during the phase.
    """

    enqueued: int = 0
    probanda_committed: list[str] = field(default_factory=list)
    edges_committed: list[str] = field(default_factory=list)
    clarifications_raised: list[str] = field(default_factory=list)
    outputs_consumed: int = 0


# ---------------------------------------------------------------------------
# T8.1 — cluster enumeration
# ---------------------------------------------------------------------------


def _find_first_ultimate_id(
    substrate: Substrate,
    penultimate_id: str,
) -> str | None:
    """Walk incoming probandum-edges from ``penultimate_id`` to find an ultimate.

    BFS over incoming probandum-to-probandum edges (the penultimate is
    the ``child_id`` side; the parent is one hop closer to an ultimate).
    Returns the id of the FIRST ultimate found, or ``None`` if no
    ultimate is reachable within 100 hops.

    Mirrors the semantics of :meth:`Substrate._walk_to_ultimate` but
    returns the id rather than a bool — the cluster payload needs the
    actual ultimate substrate id, not just its presence.

    Superseded probandum-edges are excluded from the walk so retracted
    state cannot anchor lineage (parity with the Substrate helper).
    """
    # Materialise once; ``list_probandum_edges`` re-walks the directory
    # on each call.
    superseded = substrate._superseded_probandum_edge_ids()
    incoming_probandum_edges = [
        e for e in substrate.list_probandum_edges(child_kind="probandum") if e.id not in superseded
    ]

    visited: set[str] = {penultimate_id}
    queue: deque[str] = deque([penultimate_id])
    depth = 0
    while queue and depth < 100:
        depth += 1
        next_layer: deque[str] = deque()
        while queue:
            node = queue.popleft()
            for edge in incoming_probandum_edges:
                if edge.child_id != node:
                    continue
                parent_p = substrate.latest_probandum_for(edge.parent_probandum_id)
                if parent_p is None:
                    continue
                if parent_p.kind == "ultimate":
                    return parent_p.id
                if parent_p.id not in visited:
                    visited.add(parent_p.id)
                    next_layer.append(parent_p.id)
        queue = next_layer
    return None


def enumerate_hierarchize_clusters(
    substrate: Substrate,
) -> Iterator[HierarchizeCluster]:
    """Yield one :class:`HierarchizeCluster` per qualifying penultimate.

    Walks ``mappings/probanda/`` for every ``kind="penultimate"``
    probandum (ordered by id) and, for each:

    1. Locates its ultimate ancestor via :func:`_find_first_ultimate_id`.
       Penultimates with no upward path to an ultimate are skipped.
    2. Collects existing children via outgoing probandum-edges:
       ``atom`` children dereference to substrate atoms;
       ``cross-doc-relation`` children carry their warrant +
       shared-entity payload; ``probandum`` children (existing interim
       probanda) carry their statement.
    3. Skips clusters with no existing children — nothing to fan out
       from.
    4. Reads the pinned Walton-scheme snapshot for the cluster payload.
       The snapshot is required (raises ``SubstrateNotFound`` if
       missing); the operator pins it via ``amanuensis map vocabulary
       walton snapshot`` (or the bundled default is pinned on first
       ``amanuensis map`` invocation).

    Determinism:
        Penultimate probanda are iterated in id-lex order; per-cluster
        children are sorted by (kind, id) so the inputs_hash is stable
        across runs that touch edges in a different filesystem-iter
        order.

    Args:
        substrate: A bound ``Substrate`` handle for the workspace.

    Yields:
        :class:`HierarchizeCluster` records, one per qualifying
        penultimate.

    Raises:
        SubstrateNotFound: if the Walton-scheme snapshot has not been
            pinned.
    """
    snapshot = substrate.load_walton_scheme_snapshot()
    if snapshot is None:
        raise SubstrateNotFound(
            f"Walton-scheme snapshot not found at "
            f"{substrate.walton_scheme_snapshot_path()}; "
            "run `amanuensis map` (which pins the bundled default) or "
            "`amanuensis map vocabulary walton snapshot` first"
        )
    walton_schemes = [s.name for s in snapshot.schemes]

    for penultimate in sorted(
        substrate.list_probanda(kind="penultimate"),
        key=lambda p: p.id,
    ):
        ultimate_id = _find_first_ultimate_id(substrate, penultimate.id)
        if ultimate_id is None:
            # Orphan penultimate — the reconciler will eventually raise
            # a lineage-incomplete clarification via the auditor.
            continue
        ultimate = substrate.latest_probandum_for(ultimate_id)
        if ultimate is None:
            continue  # defensive: chain says ultimate exists but file is gone

        # Walk outgoing probandum-edges from this penultimate.
        candidate_evidence: list[dict[str, Any]] = []
        for edge in substrate.list_probandum_edges(parent_probandum_id=penultimate.id):
            if edge.child_kind == "atom":
                if edge.child_source_id is None:
                    continue  # malformed edge; defensive
                try:
                    atom = substrate.get_atom(edge.child_source_id, edge.child_id)
                except SubstrateNotFound:
                    continue
                candidate_evidence.append(
                    {
                        "kind": "atom",
                        "id": atom.id,
                        "source_id": atom.source_id,
                        "text": atom.narrative,
                        "predicate": atom.predicate,
                    }
                )
            elif edge.child_kind == "cross-doc-relation":
                try:
                    xrel = substrate.get_cross_doc_relation(edge.child_id)
                except SubstrateNotFound:
                    continue
                candidate_evidence.append(
                    {
                        "kind": "cross-doc-relation",
                        "id": xrel.id,
                        "warrant": xrel.warrant,
                        "shared_entities": list(xrel.shared_entities),
                    }
                )
            elif edge.child_kind == "probandum":
                child = substrate.latest_probandum_for(edge.child_id)
                if child is None:
                    continue
                candidate_evidence.append(
                    {
                        "kind": "probandum",
                        "id": child.id,
                        "statement": child.statement,
                    }
                )
            # Unknown child kinds: defensive skip.

        if not candidate_evidence:
            continue  # no existing evidence to fan out from

        # Sort evidence by (kind, id) so the inputs_hash is stable
        # across runs that touch edges in a different filesystem-iter
        # order.
        candidate_evidence.sort(key=lambda e: (e["kind"], e["id"]))

        yield HierarchizeCluster(
            parent_probandum_id=penultimate.id,
            parent_statement=penultimate.statement,
            ultimate_probandum={"id": ultimate.id, "statement": ultimate.statement},
            candidate_evidence=candidate_evidence,
            walton_schemes=walton_schemes,
        )


# ---------------------------------------------------------------------------
# T8.2 — per-cluster enqueue
# ---------------------------------------------------------------------------


def _cluster_inputs_hash(cluster: HierarchizeCluster) -> str:
    """Content-addressable hash of a cluster's canonical form.

    The hash covers the parent (id + statement), the ultimate
    (id + statement), every candidate-evidence entry, and the Walton
    scheme list. Two calls with byte-identical cluster content produce
    identical hashes; any change to evidence or the active Walton
    snapshot flips the hash and forces a fresh dispatch event.
    """
    canonical = json.dumps(
        {
            "candidate_evidence": cluster.candidate_evidence,
            "parent_probandum_id": cluster.parent_probandum_id,
            "parent_statement": cluster.parent_statement,
            "ultimate_probandum": cluster.ultimate_probandum,
            "walton_schemes": cluster.walton_schemes,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _load_hierarchize_skill_prompt() -> str:
    """Return the ``map_hierarchize.md`` skill body for embedding in the queue entry."""
    return (
        resources.files("amanuensis.skills")
        .joinpath("map_hierarchize.md")
        .read_text(encoding="utf-8")
    )


def enqueue_hierarchize_clusters(substrate: Substrate) -> int:
    """Enumerate every qualifying penultimate cluster and write one queue entry each.

    Each queue entry's payload carries the cluster shape the Hierarchize
    role consumes (``parent_probandum_id``, ``parent_statement``,
    ``ultimate_probandum``, ``candidate_evidence``, ``walton_schemes``).
    The ``inputs_hash`` is the canonical-form hash of the cluster so
    re-runs of identical clusters are byte-identical writes (idempotent
    at the queue-entry layer; the cache layer keys on the same hash so
    the driver short-circuits on a second invocation).

    Args:
        substrate: A bound ``Substrate`` handle for the workspace.

    Returns:
        The number of clusters enqueued. ``0`` when the substrate has
        no qualifying penultimate clusters (no penultimate probanda,
        all orphans, no children, etc.).
    """
    prompt_body = _load_hierarchize_skill_prompt()
    now = datetime.now(UTC)
    count = 0
    for cluster in enumerate_hierarchize_clusters(substrate):
        inputs_hash = _cluster_inputs_hash(cluster)
        entry = DispatchQueueEntry(
            role="hierarchize",
            prompt=prompt_body,
            inputs={
                "parent_probandum_id": cluster.parent_probandum_id,
                "parent_statement": cluster.parent_statement,
                "ultimate_probandum": cluster.ultimate_probandum,
                "candidate_evidence": cluster.candidate_evidence,
                "walton_schemes": cluster.walton_schemes,
            },
            model_id=_DEFAULT_MODEL_ID,
            inputs_hash=inputs_hash,
            enqueued_at=now,
        )
        enqueue(substrate.root, entry)
        count += 1
    return count


# ---------------------------------------------------------------------------
# T8.3 — phase orchestrator
# ---------------------------------------------------------------------------


def run_hierarchize_phase(substrate: Substrate) -> HierarchizePhaseReport:
    """Drive the full Hierarchize phase: enumerate → enqueue → reconcile.

    Mirrors :func:`run_connect_phase`'s shape:

    - **Enqueue**: one queue entry per qualifying penultimate cluster,
      content-addressable by ``inputs_hash``. Always runs; idempotent
      on identical substrate state.
    - **Reconcile**: drain any
      ``dispatch/outputs/hierarchize-*/output.yaml`` files into the
      substrate. Only does work if a previous dispatch driver run
      (or a test fixture) placed outputs there.

    Real-LLM dispatch is the supervisor's responsibility via
    ``amanuensis dispatch`` between phases.

    Re-entrant flock note: ``enqueue_hierarchize_clusters`` writes only
    content-addressable queue files (no flock needed);
    ``reconcile_outputs`` re-acquires the workspace flock internally.
    Callers (notably the ``amanuensis map`` orchestrator callback)
    MUST release the resolve/audit flock before invoking this
    function; otherwise the inner flock acquisition deadlocks.

    Args:
        substrate: A bound ``Substrate`` handle for the workspace.

    Returns:
        A populated :class:`HierarchizePhaseReport`.
    """
    enqueued = enqueue_hierarchize_clusters(substrate)
    reconcile_result = reconcile_outputs(
        substrate=substrate,
        workspace_root=substrate.root,
    )
    # Filter reconcile counters to the hierarchize role.
    # ``reconcile_outputs`` drains EVERY pending output, so we count
    # only the hierarchize-role consumption for the phase report.
    hierarchize_consumed = [
        p for p in reconcile_result.outputs_consumed if p.parent.name.startswith("hierarchize-")
    ]
    return HierarchizePhaseReport(
        enqueued=enqueued,
        probanda_committed=list(reconcile_result.hierarchize_probanda_committed),
        edges_committed=list(reconcile_result.hierarchize_edges_committed),
        clarifications_raised=list(reconcile_result.hierarchize_clarifications_raised),
        outputs_consumed=len(hierarchize_consumed),
    )
