# Phase 2b (Connect) — Design Spec

**Project:** amanuensis
**Phase:** 2b (cross-document support/attack edges) — second sub-project of Phase 2 (Map)
**Status:** spec drafted 2026-05-31; awaiting user review before plan
**Authoritative invariants:** [`INVARIANTS.md`](../../../INVARIANTS.md)
**Architecture reference:** [`docs/architecture.md`](../../architecture.md)
**Predecessor:** Phase 2a (Resolve) shipped 2026-05-31 — see `HISTORY.md`

---

## Scope decomposition (why Phase 2b is its own spec)

Phase 2 (Map) was decomposed in the Phase 2a spec into three sub-projects
with a strict dependency order: Resolve → Connect → Hierarchize. Phase 2a
(Resolve) shipped 2026-05-31 with the entity-resolution substrate
(Entity / Resolution / EntitySupersede / ResolutionSupersede schemas;
mappings/ namespace; INV-12/13/14 active).

Phase 2b (Connect) is the second sub-project: cross-document support /
attack / undercut edges built on top of Phase 2a's resolved entities.
Phase 2c (Hierarchize) — probandum hierarchies — depends on Phase 2b's
edges and is deferred to its own brainstorm cycle.

---

## Goal

Phase 2b (Connect) builds the cross-document edge layer of the project's
evidence chart. Where Phase 1 produces intra-document edges (paragraphs
within one source supporting / attacking each other) and Phase 2a
produces cross-document entity identity (Smith-in-doc-A and Smith-in-doc-B
are the same canonical entity), Phase 2b produces cross-document edges
between specific atom claims, grounded in shared entity identity.

The mechanism mirrors the Phase 1 + Phase 2a extractor+auditor pattern:
a new `amanuensis:map:connect` skill proposes candidate cross-doc edges;
the existing (Phase 2a-extended) `amanuensis:map:audit` skill validates
each candidate; edges that propose connections over not-yet-resolved
operand pairs auto-raise clarifications resolved by the supervisor via
the existing web-app surface.

Phase 2a's `Resolution` records carry the join keys Phase 2b needs:
every cross-doc edge must reference at least one canonical entity
resolved by both endpoints. This makes Phase 2a's substrate the
deterministic precondition for Phase 2b's reasoning, formalized as a
new invariant (INV-15).

---

## In scope

1. `CrossDocRelation` schema — a cross-document support / attack /
   undercut edge between two atoms in different distillations.
2. `CrossDocRelationSupersede` schema — supervisor corrections that
   preserve immutability (mirrors Phase 2a's `EntitySupersede` /
   `ResolutionSupersede` pattern).
3. INV-15 — every `CrossDocRelation` has a non-empty `shared_entities`
   list, AND every listed entity is genuinely resolved by both endpoint
   atoms via Phase 2a `Resolution` records.
4. Connector role (`amanuensis:map:connect`) — proposes cross-doc edge
   candidates from entity-keyed atom clusters.
5. Auditor role extension (`amanuensis:map:audit`) — gains a code path
   for validating `CrossDocRelation` candidates against INV-15, warrant
   defensibility, and kind-direction consistency.
6. Reconciliation-gate extension — `_build_cross_doc_relation` mirrors
   the Phase 2a `_build_resolution` pattern; auto-raises a
   `resolution-ambiguous` clarification on INV-15 failure.
7. Entity-driven dispatch: the orchestrator iterates over canonical
   entities (ordered by entity id) and submits one Connector call per
   cluster of atoms resolved to that entity.
8. `amanuensis map relation` CLI sub-family (`list`, `show`, `supersede`).
9. Web-app additions: cross-doc-relation list / detail routes;
   Cytoscape graph overlay; entity-detail "edges touching this entity"
   panel.
10. Static-export additions: cross-doc-relations appendix; per-entity
    edge listing on entity-detail pages.
11. Integration-based gate: extension of the Phase 2a 3-document
    synthetic fixture asserting ≥1 cross-doc edge of each kind is
    produced.
12. End-to-end Playwright spec exercising the cross-doc graph overlay
    + detail-page navigation.

## Out of scope (deferred to later sub-projects)

- **Probandum hierarchies (Phase 2c).** Phase 2b's edges become Phase 2c's
  inputs. The "what proposition does this edge ultimately support?"
  question is Phase 2c's job.
- **Hand-authored edge entry.** Edges enter the substrate only via the
  Connector dispatch + Auditor gate, or via supervisor supersede of an
  existing edge. No web POST endpoint for creating edges from scratch.
- **Multi-document chunking strategies.** Large clusters (a canonical
  entity referenced by 200+ atoms across many documents) are noted as
  a Phase 2b known limitation; chunking by source pair is a Phase 2b.5
  candidate.
- **Edge-kind vocabulary extension.** The Toulmin trio
  (`supports` / `attacks` / `undercuts`) is the closed cross-doc edge
  vocabulary in Phase 2b. Wigmore-flavored extensions (`corroborates`,
  `contradicts`, `qualifies`) are not introduced; Phase 2c may revisit.
- **Cross-doc-relation-derived analytics.** "How many of E_Smith's
  cross-doc edges are attacks?" queries are downstream of Phase 2c
  probandum aggregation; not Phase 2b.

---

## Data model

### CrossDocRelation

A new Pydantic class in `src/amanuensis/schemas/cross_doc_relation.py`:

```python
class CrossDocRelation(BaseModel):
    """Cross-document directed warrant-bearing edge between two atoms."""

    model_config = ConfigDict(strict=True, extra="forbid")
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    id: str                               # x-<hash> ; content-addressable
    from_atom_id: str                     # atom in distillations/<from_source_id>/atoms/
    from_source_id: str
    to_atom_id: str                       # atom in distillations/<to_source_id>/atoms/
    to_source_id: str                     # MUST != from_source_id (write-time gate)
    kind: Literal["supports", "attacks", "undercuts"]
    warrant: str
    warrant_defensibility: Literal[
        "literature-backed",
        "methodology-derived",
        "conventional",
        "contested",
    ]
    warrant_basis: str
    confidence: Literal["high", "medium", "low"]
    shared_entities: list[str]            # NON-EMPTY ; each is an Entity id in
                                          # mappings/entities/ AND is resolved by
                                          # BOTH endpoints (INV-15)
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1
```

**Id prefix:** `x-` (cross-doc; `r-` is reserved for intra-doc Phase 1
`Relation`).

**Volatile fields:** `provenance_id` only — same rationale as Phase 1
`Relation` and Phase 2a `Entity` / `Resolution`. PROV-O direction is
Activity → Entity, so the outbound provenance pointer is observational
metadata, not identity content. Content-addressable hashing excludes it.

**`from_source_id` vs `to_source_id`:** stored explicitly on the edge
even though they're derivable from each atom's `source_id` field. The
redundancy makes write-time and audit gates O(1) on the edge record
itself without requiring an atom lookup, and makes the "different
sources" constraint a single-record check.

**`shared_entities`:** non-empty list of canonical entity ids. Every id
must (a) exist as an `Entity` record in `mappings/entities/`, (b) be
resolved by at least one `Resolution` whose triple matches
`(from_source_id, from_atom_id, *)`, (c) be resolved by at least one
`Resolution` whose triple matches `(to_source_id, to_atom_id, *)`. INV-15
formalizes this.

### CrossDocRelationSupersede

A new Pydantic class in `src/amanuensis/schemas/cross_doc_relation_supersede.py`:

```python
class CrossDocRelationSupersede(BaseModel):
    """Correction record for a cross-doc relation."""

    model_config = ConfigDict(strict=True, extra="forbid")
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id", "at"})

    id: str                               # v-<hash>
    supersedes_id: str                    # x-<hash> of prior CrossDocRelation
    superseded_by_id: str                 # x-<hash> of new CrossDocRelation
    kind: Literal["cross-doc-relation"] = "cross-doc-relation"
    reason: str
    provenance_id: str
    role_attributions: list[RoleAttribution]
    at: AwareDatetime                     # volatile (matches Phase 2a supersede pattern)
    schema_version: int = 1

    @field_validator("reason")
    @classmethod
    def _reason_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason must be non-empty")
        return v
```

**Id prefix:** `v-` (revision). Mirrors Phase 2a's `EntitySupersede`
(`t-` prefix) and `ResolutionSupersede` (`s-` prefix) by giving each
supersede class its own letter.

**Pattern:** identical to Phase 2a's two supersede classes; immutability
+ chain-walking semantics inherit from INV-13.

---

## Filesystem layout

Extends the `mappings/` namespace established in Phase 2a:

```text
mappings/
  entities/e-<hash>.md                   (existing — Phase 2a)
  resolutions/j-<hash>.yaml              (existing — Phase 2a)
  supersedes/t-<hash>.yaml               (existing — Phase 2a, EntitySupersede)
  supersedes/s-<hash>.yaml               (existing — Phase 2a, ResolutionSupersede)
  supersedes/v-<hash>.yaml               (NEW — CrossDocRelationSupersede)
  relations/x-<hash>.yaml                (NEW — CrossDocRelation; pure YAML)
  provenance/<prov-id>.yaml              (existing — extended for cross-doc activities)
  replay-log/                            (existing — Phase 2a mappings-scoped log)
  entity-vocabulary-snapshot.yaml        (existing — Phase 2a)
```

No new top-level directories under `mappings/`. The `relations/` and
`supersedes/` subdirectories already exist; `relations/x-<hash>.yaml`
files coexist alongside `mappings/`'s other artifacts under INV-12.

---

## Invariant additions

### INV-15 (new) — Cross-doc edges are grounded in shared resolved entities

- **Status:** active (gated)
- **Established:** 2026-05-31 (Phase 2b M3)
- **Property:** Every `CrossDocRelation` record has a non-empty
  `shared_entities` list, AND every listed entity id satisfies all
  three conditions: (a) it exists as an `Entity` record in
  `mappings/entities/`; (b) at least one `Resolution` record exists
  with `source_id == from_source_id`, `atom_id == from_atom_id`, and
  `entity_id` matching the listed id (or its supersede chain
  terminus); (c) at least one `Resolution` record exists with
  `source_id == to_source_id`, `atom_id == to_atom_id`, and same
  matching condition. Empty `shared_entities`, references to missing
  entities, or references to entities not resolved by both endpoints
  raise `SharedEntityGateViolation` at `Substrate.add_cross_doc_relation`
  and are caught by the gate test.
- **Gate test:** `tests/invariants/test_cross_doc_shared_entity.py` —
  five cases: (1) a workspace with bilateral resolutions and one
  valid edge passes; (2) a relation with `shared_entities: []` is
  caught; (3) a relation referencing an entity id with no on-disk
  Entity record is caught; (4) a relation whose from-endpoint lacks
  a Resolution to the shared entity is caught; (5) the to-endpoint
  mirror is caught.
- **Rationale:** Without this gate, cross-doc edges become open-ended
  in the same way Phase 1 atom extraction would have been without
  INV-5's closed vocabulary. INV-15 makes Phase 2a's `Resolution`
  substrate the deterministic backbone of cross-doc reasoning:
  Phase 2a stops being "a thing Phase 2b uses" and becomes the
  precondition without which Phase 2b cannot write.

### INV-9 (existing, EXTENDED gate)

The existing `tests/invariants/test_intra_doc_only.py` gains a new
case asserting that no `CrossDocRelation` file (`x-<hash>.yaml`)
exists under `distillations/<src>/relations/`. INV-9's textual
property is unchanged.

### INV-12 (existing, EXTENDED gate)

The existing `tests/invariants/test_mappings_namespace_scoped.py`
gains a new case: a `CrossDocRelation` whose `from_atom_id` or
`to_atom_id` references an atom that does not exist under the
corresponding `distillations/<src>/atoms/` directory is a violation.

### INV-13 (existing, unchanged)

`CrossDocRelation` and `CrossDocRelationSupersede` inherit
immutability from INV-13. `add_cross_doc_relation` is idempotent on
identical content (same id, same canonical form) and raises
`MutationOfImmutableRecord` on diverging content at the same id. No
separate gate test required — the existing
`tests/invariants/test_mappings_immutability.py` is parametrized in
this spec to add `CrossDocRelation` to its existing Entity /
Resolution cases.

---

## Role decomposition + dispatch

### Connector role (NEW)

- **Skill file:** `src/amanuensis/skills/map_connect.md`
- **Frontmatter command:** `amanuensis map connect`
- **Input contract:** a JSON cluster of the shape

  ```json
  {
    "entity_id": "e-<hash>",
    "entity_kind": "<kind>",
    "atoms": [
      {
        "atom_id": "a-<hash>",
        "source_id": "<src>",
        "text": "<atom narrative>",
        "predicate": "<predicate>",
        "operand_refs": [...]
      },
      ...
    ]
  }
  ```

- **Output contract:** a JSON list of candidate `CrossDocRelation`
  records (without ids; the reconciler computes ids and writes).
  Each candidate carries the full warrant fields.
- **Write-isolation:** subprocess writes only under
  `dispatch/outputs/connect-<inputs_hash>/`. Same INV-11 contract as
  Phase 2a roles.

### Auditor role (EXTENDED)

The existing `amanuensis:map:audit` skill gains a branch for
auditing `CrossDocRelation` candidates. Skill content extension only;
no new skill file.

Audit checks per candidate:
1. **Shape:** all required fields present, types match.
2. **INV-15 precondition check:** every entity in `shared_entities`
   resolves correctly on both endpoints. (Auditor reads `Resolution`
   records.)
3. **Different-source check:** `from_source_id != to_source_id`.
4. **Warrant defensibility:** the proposed `warrant_basis` matches
   the asserted `warrant_defensibility` category.
5. **Kind-direction consistency:** the `kind` choice
   (`supports` / `attacks` / `undercuts`) matches the warrant's
   stated direction.
6. **Confidence floor:** confidence not contradicted by warrant
   defensibility (e.g., `confidence=high` with
   `warrant_defensibility=contested` triggers a downgrade signal).

Candidates failing checks 1, 3 are silently rejected (slop).
Candidates failing check 2 (INV-15 precondition) raise a
`resolution-ambiguous` clarification through the reconciler.
Candidates failing checks 4–6 are downgraded (warrant_defensibility
flipped to `contested`) and proceed to the supervisor's review queue
rather than the substrate; this matches the Phase 1 pattern where
contested warrants auto-raise clarifications.

### Dispatch flow

The existing `amanuensis map` orchestrator gains a new phase between
the Phase 2a `resolve` phase and the (future) Phase 2c `hierarchize`
phase:

1. **Cluster enumeration.** For each `Entity` in `mappings/entities/`
   (ordered by entity id, supersede-chain-resolved to its terminus),
   walk all `Resolution` records under `mappings/resolutions/` whose
   `entity_id` matches. Collect the unique `(source_id, atom_id)`
   pairs. Skip the entity if fewer than 2 atoms or all atoms share
   the same `source_id`.
2. **Dispatch enqueue.** For each surviving cluster, compute
   `inputs_hash = hash(canonical_form(cluster))`; enqueue
   `dispatch/queue/connect-<inputs_hash>.yaml`. Cache hit short-
   circuits (INV-4).
3. **Subprocess execution.** Dispatch driver invokes the harness CLI
   bound to the Connector role; subprocess writes candidates to
   `dispatch/outputs/connect-<inputs_hash>/`.
4. **Reconciliation.** `dispatch.reconcile` (extended) reads
   candidates, invokes `_build_cross_doc_relation` per candidate.
   Surviving candidates are written to `mappings/relations/`.
   Clarifications on INV-15 failures are written to the relevant
   `distillations/<src>/clarifications/open/`.
5. **Replay-log entry.** Standard mappings-scoped replay log entry
   per dispatch event (INV-4 pattern).

Cost discipline: cluster dedup by content-addressable id means a
single atom-pair appearing under multiple shared entities produces
the same edge id on second appearance and the immutability gate
(INV-13) makes the second write a no-op.

---

## Reconciliation gate

The existing `src/amanuensis/dispatch/reconcile.py` module gains:

### `_build_cross_doc_relation(candidate, substrate, prov_record) -> CrossDocRelation | None`

Mirrors the `_build_resolution` pattern from Phase 2a M6:

1. Parse the candidate dict into the `CrossDocRelation` shape, with
   `provenance_id` set from `prov_record.id`.
2. Compute content-addressable `id` via the standard hashing
   pipeline; reject if `from_source_id == to_source_id`.
3. **INV-15 check.** Walk each entity in `shared_entities`:
   - Verify the entity exists in `mappings/entities/` (resolve
     supersede chain if needed).
   - Verify at least one `Resolution` matches
     `(from_source_id, from_atom_id, *)` with that entity.
   - Verify at least one `Resolution` matches
     `(to_source_id, to_atom_id, *)` with that entity.
4. On any INV-15 failure, write a `Clarification` of kind
   `resolution-ambiguous` referencing the two atoms and the missing
   entity overlap. Return `None`.
5. On success, return the `CrossDocRelation`. The caller writes via
   `substrate.add_cross_doc_relation(rel)`.

### `_auto_raise_resolution_clarification(...)` helper

Writes a `Clarification` to the appropriate distillation's
`clarifications/open/` directory. Reuses the existing
`Substrate.add_clarification` API. The `Clarification.kind` value
matches the existing `resolution-ambiguous` constant added in
Phase 2a M8.

### Idempotency

Repeated reconciliation runs over the same dispatch output produce
byte-identical substrate state (INV-4 / INV-8). The combination of
content-addressable ids + INV-13 immutability + INV-15 deterministic
gate is sufficient — no additional dedup logic needed in the
reconciler.

---

## CLI surface

Three new sub-commands under the existing `amanuensis map` Typer
sub-app (no new top-level verb; the orchestrator `amanuensis map`
already runs all phases of the mapping pass):

| Sub-command | Flags | Behavior |
|---|---|---|
| `map relation list` | `--kind {supports,attacks,undercuts}`, `--from-source SRC`, `--to-source SRC`, `--shared-entity ENTITY_ID`, `--limit N` | Lists cross-doc relations matching filters, sorted by id. Read-only. |
| `map relation show <id>` | (none) | Detail view: endpoints (with atom narratives), `kind`, warrant, `shared_entities`, provenance, supersede chain (forward + back). Read-only. |
| `map relation supersede <old-id> <new-id> --reason "..."` | `--reason TEXT` (required) | Writes a `CrossDocRelationSupersede` record. Both ids must exist. Mutates substrate; takes the workspace flock. |

No POST endpoints in the web app; supervisor corrections to existing
edges go through the CLI supersede verb. This matches Phase 2a's
discipline (entity merge and resolution supersede are CLI-only).

---

## Web app additions

### New routes

In `src/amanuensis/web/routes/cross_doc_relations.py`:

| Method | Path | Behavior |
|---|---|---|
| GET | `/cross-doc-relations` | Filterable list (`?kind=`, `?from_source=`, `?to_source=`, `?shared_entity=`). HTML page with table + filter form. |
| GET | `/cross-doc-relations/<id>` | Detail page: endpoints (with atom narrative excerpts), warrant, shared entities (each linking to entity-detail), provenance link, supersede chain. |

### Cytoscape graph extension

The existing `/distillations/<src>/relations/` graph view gains a
`?cross_doc=1` query param. When set, the renderer:

1. Includes the intra-doc edges as before.
2. Walks `mappings/relations/` for every `CrossDocRelation` where
   `from_source_id == src` OR `to_source_id == src`.
3. Renders the cross-doc edges with a distinct style: dashed line,
   orange stroke (matches Phase 2a's entity-hover-highlight color).
4. Edge clicks navigate to `/cross-doc-relations/<id>`.
5. The `view-by-section` graceful-degradation mode (Phase 1) extends
   to cross-doc edges: when total edge count exceeds the Cytoscape
   soft cap (2000 edges), the user picks a section path and the
   graph renders scoped.

### Entity-detail page extension

The existing `/entities/<id>` page (Phase 2a) gains a new section
"Cross-doc edges touching this entity" listing every
`CrossDocRelation` where `id` appears in `shared_entities`. Grouped
by `kind`. Each row links to the relation-detail page.

### Static fragment endpoint

The existing `/distillations/<src>/relations/atom-entity-index`
JSON fragment endpoint (Phase 2a) gains an optional
`?include_cross_doc=1` flag that surfaces cross-doc edges in the
same shape as intra-doc relations. Used by the Cytoscape overlay
JavaScript.

---

## Static export additions

`amanuensis export`:

1. **New page: `cross-doc-relations.html`.** Lists every
   `CrossDocRelation` in the substrate, grouped by `kind`. Each
   entry: from-atom excerpt → to-atom excerpt, warrant, shared
   entities (anchor-linked to per-entity pages).
2. **Per-entity page extension.** Each `entities/<id>.html` page
   gains a "Cross-doc edges touching this entity" section parallel
   to the web app surface.
3. **Cytoscape overlay parity.** The static graph (when present)
   includes cross-doc edges in the same styled overlay as the web
   app.
4. **INV-8 render-purity.** Same substrate → same bytes. Existing
   render-purity smoke test (`tests/export/test_static_export_smoke.py`)
   extended to include a fixture with at least one cross-doc edge,
   asserting deterministic output.

---

## Gate tests + validation

Mirrors Phase 2a's M10 / M11 final-validation pattern.

### New / extended test files

| Test file | Purpose | New / Extended |
|---|---|---|
| `tests/schemas/test_cross_doc_relation.py` | Schema-level field validation, content-addressable id stability, volatile-field exclusion. | NEW |
| `tests/schemas/test_cross_doc_relation_supersede.py` | Same for supersede class. | NEW |
| `tests/fs/test_cross_doc_relation_io.py` | `Substrate.add_cross_doc_relation` writes + reads; idempotency. | NEW |
| `tests/invariants/test_cross_doc_shared_entity.py` | INV-15 — five cases (see Invariant additions). | NEW |
| `tests/invariants/test_intra_doc_only.py` | EXTENDED — adds case for cross-doc relation under `distillations/`. | EXTEND |
| `tests/invariants/test_mappings_namespace_scoped.py` | EXTENDED — adds case for cross-doc relation referencing non-existent atom. | EXTEND |
| `tests/invariants/test_mappings_immutability.py` | EXTENDED — parametrizes existing Entity/Resolution cases to also cover `CrossDocRelation`. | EXTEND |
| `tests/dispatch/test_cross_doc_reconcile.py` | Reconciler — three cases: (1) valid candidate reaches substrate; (2) INV-15 failure raises clarification; (3) supersede flow end-to-end. | NEW |
| `tests/dispatch/test_role_write_isolation.py` | EXTENDED — parametrizes existing role cases to cover `connect` role. | EXTEND |
| `tests/cli/test_map_relation.py` | CLI surface — list / show / supersede. | NEW |
| `tests/web/test_cross_doc_relation_routes.py` | Web routes — list / detail; filter combinations; supersede-chain rendering. | NEW |
| `tests/web/test_cytoscape_overlay.py` | Overlay style + edge-click navigation; soft-cap fallback. | NEW |
| `tests/export/test_static_export_cross_doc.py` | Static-export additions; INV-8 render-purity. | NEW |
| `tests/integration/test_phase2b_connect_end_to_end.py` | 3-distillation fixture extension: resolve → connect → assert ≥1 edge of each `kind`. | NEW |
| `tests/e2e/test_phase2b_overlay_flow.py` | Playwright: open graph view, toggle cross-doc overlay, click edge, see detail page. | NEW |

### Final-validation gate (Phase 2b M11)

Pass criteria (extending Phase 2a's):

- ≥950 fast pytest cases pass (874 Phase 2a baseline + ~75 new)
- 51 invariants pass (50 Phase 2a baseline + 1 new INV-15)
- pyright strict 0 errors
- ruff clean
- vulture 0 findings
- 13 Playwright specs pass (12 Phase 2a baseline + 1 new T11.4 cross-doc overlay)
- Structural smoke on the 3-distillation fixture produces ≥1
  cross-doc edge of each `kind`

---

## Risks + deferrals

These are the items the warp-tier brainstorm cycle (self-contrarian →
external dispatch → premortem) will specifically be asked to stress-test
during the plan-writing step.

### Risks (in-scope, mitigation candidates)

1. **Cluster explosion.** A canonical entity referenced by 200+ atoms
   across many documents (e.g., a major party name in a long matter)
   creates a giant cluster that exceeds the Connector LLM's effective
   context. *Mitigation candidate:* chunk by source pair when cluster
   size exceeds a configurable threshold (default 50 atoms); surface as
   a known limitation initially with a clear "this cluster was
   chunked" provenance marker.

2. **Clarification cycle.** Connector proposes an edge → INV-15 fails
   (missing resolution) → clarification raised → supervisor resolves
   it (creating a new Resolution) → next dispatch run proposes the
   same edge again. The cache layer (cache hit on
   `inputs_hash`) saves the LLM call cost but the orchestrator still
   needs to surface "this edge was previously rejected for missing
   resolution X, now resolved" so the supervisor sees continuity.
   *Mitigation:* the `provenance_id` chain on the second attempt
   captures the prior rejection; explicit test in
   `test_cross_doc_reconcile.py`.

3. **Cross-doc edges referencing superseded entities.** If `E_v1` is
   superseded by `E_v2` after a `CrossDocRelation` is written
   referencing `E_v1` in `shared_entities`, the gate must remain
   valid by walking the supersede chain. *Mitigation:* INV-15 gate
   walks supersede chains (already a Phase 2a pattern, reused via
   the existing `latest_entity_for` helper).

4. **Web app + Cytoscape performance under overlay.** Cross-doc
   overlay on a 750-atom graph (Phase 1's soft cap) plus 200+
   cross-doc edges could exceed the Cytoscape 2000-edge limit.
   *Mitigation:* `view-by-section` mode (Phase 1) already exists;
   overlay inherits it and the JS adapts the section filter to the
   cross-doc edge set.

5. **Connector LLM proposing implausible edges between weakly-related
   atoms.** Two atoms share entity E_Smith but are about wholly
   different topics (one about Smith's employment, another about
   Smith's vacation). The LLM might still propose an edge.
   *Mitigation:* Auditor's warrant-defensibility check (already in
   scope) is the primary gate; `confidence=low` candidates are
   surfaced for supervisor review rather than written.

6. **Supersede chain ambiguity on cross-doc relations.** If two
   supersedes are proposed for the same cross-doc relation
   concurrently (rare but possible during multi-session work), the
   replay log + workspace flock combination must serialize them.
   *Mitigation:* the existing flock discipline (Phase 1) applies;
   the supersede write goes through the same `add_*` substrate API
   that takes the flock.

### Deferrals (explicit; not bugs)

- **Auto-merge of supersede chains.** If a cross-doc relation is
  superseded twice, the chain is walked at read time. No compaction.
  (Same as Phase 2a.)
- **Cross-doc edge confidence rollup at entity level.** "What's the
  overall strength of attacks targeting E_Smith?" is a Phase 2c
  concern.
- **Auto-detection of edge contradictions.** If edge A says
  "atom-X supports atom-Y" and edge B says "atom-X attacks atom-Y"
  (same endpoints, conflicting kind), no automatic contradiction
  flag is raised. Both edges are written; the supervisor sees both
  in the detail-page list. Phase 2c probandum reasoning will
  introduce contradiction handling.
- **Edge-level export of just the cross-doc subgraph as a graph
  format (Cytoscape JSON, GraphML).** Static HTML covers the
  delivery surface in Phase 2b; programmatic graph export is a
  Phase 4 candidate.

---

## Module decomposition impact

Additions to the existing module DAG (per `docs/architecture.md`):

| Module | Purpose | Depends on | Public surface |
|---|---|---|---|
| `amanuensis.schemas.cross_doc_relation` | `CrossDocRelation` schema | `schemas._shared` | `CrossDocRelation` |
| `amanuensis.schemas.cross_doc_relation_supersede` | Supersede class | `schemas._shared` | `CrossDocRelationSupersede` |
| `amanuensis.fs` (EXTENDED) | New `add_cross_doc_relation`, `add_cross_doc_relation_supersede`, `list_cross_doc_relations`, `latest_cross_doc_relation_for` methods on `Substrate` | (no new deps) | (extension only) |
| `amanuensis.dispatch.reconcile` (EXTENDED) | `_build_cross_doc_relation`; `_auto_raise_resolution_clarification` helper | (no new deps) | (extension only) |
| `amanuensis.cli.map` (EXTENDED) | `map relation {list,show,supersede}` sub-commands | (no new deps) | 3 new verbs |
| `amanuensis.web.routes.cross_doc_relations` | Read-only relation browser routes | `schemas`, `fs` | `GET /cross-doc-relations`, `GET /cross-doc-relations/<id>` |
| `amanuensis.web` (EXTENDED) | Cytoscape overlay JS; entity-detail edge panel | (no new deps) | (extension only) |
| `amanuensis.export` (EXTENDED) | Cross-doc relations appendix; per-entity edge list | `schemas`, `fs` | (extension only) |
| `amanuensis.skills.map_connect` | Connector skill markdown | (none) | File installed to harness skill directories |
| `amanuensis.skills.map_audit` (EXTENDED) | Audit branch for `CrossDocRelation` candidates | (none) | (skill body extension) |

No cycle in the DAG; all additions are additive to the leaf modules
or to extension points the Phase 2a design already designated.

---

## Milestone breakdown (preliminary — full breakdown in tasks file)

The plan-writing step (warp-tier brainstorm → contrarian → external
dispatch → premortem → tasks) will produce the authoritative
milestone + per-task breakdown. The preliminary shape:

- **M1 — Schema foundation.** `CrossDocRelation` +
  `CrossDocRelationSupersede` schemas + content-addressable id +
  immutability tests.
- **M2 — Substrate IO.** `add_cross_doc_relation`,
  `add_cross_doc_relation_supersede`, `list_*`, `latest_*` methods +
  filesystem tests.
- **M3 — INV-15 gate test + invariant extensions (INV-9, INV-12,
  INV-13).** Gate-first; substrate API must respect the gate before
  any role runs.
- **M4 — Reconciliation gate.** `_build_cross_doc_relation` +
  clarification auto-raise + reconciler tests.
- **M5 — Connector skill + Auditor skill extension.** Skill markdown
  files + dispatch driver smoke (no real LLM).
- **M6 — Dispatch driver integration.** Orchestrator cluster
  enumeration + per-cluster enqueue + write-isolation parametrize.
- **M7 — CLI surface.** `map relation {list,show,supersede}`.
- **M8 — Web routes + Cytoscape overlay.** Routes + JS + entity-detail
  panel.
- **M9 — Static export additions.** New page + per-entity section +
  render-purity test.
- **M10 — INV-15 promotion to charter + documentation sweep.**
- **M11 — Integration + E2E + final validation.** 3-distillation
  fixture extension + Playwright spec + final-gate run.

---

## Open questions

(To be answered by the warp-tier brainstorm cycle in the
plan-writing step; listed here so they don't get lost.)

1. **Cluster ordering inside the Connector call.** Should atoms in
   the cluster be ordered by `source_id` then `paragraph_index`, or
   by `paragraph_index` only, or by atom id? Phase 2a's Resolver had
   a similar choice; check what's done there for consistency.
2. **Should the Connector role receive intra-doc Phase 1 Relations
   for context?** A Phase 1 relation `r-<hash>` linking atom-A1 and
   atom-A2 in the same source might inform cross-doc edge proposals
   touching A1 or A2. Cost-benefit not obvious; default no, revisit
   if Auditor catches "missed edge" patterns.
3. **Multiple-pass dispatch.** Should the orchestrator support
   `amanuensis map --connect-only` to re-run just the connect phase
   on an existing resolved substrate? Likely yes for development
   ergonomics; needs a flag-design pass in the plan.
4. **`view-by-section` cap interaction.** The 2000-edge soft cap is
   total edges (intra + cross). Should the overlay be hidden by
   default above the cap, or always toggleable with a graceful
   warning?
5. **Per-engagement vocabulary extension for warrant_basis.** Phase 1
   uses a closed warrant_basis taxonomy (literature-backed /
   methodology-derived / conventional / contested). Cross-doc edges
   may benefit from additional categories (e.g., "documentary
   corroboration", "cross-source attestation"). Defer; if needed,
   handle as a per-engagement vocabulary extension (mirrors INV-10
   for predicates).

---

## See also

- [`docs/architecture.md`](../../architecture.md) — three-surface
  system; module decomposition.
- [`INVARIANTS.md`](../../../INVARIANTS.md) — INV-1 through INV-14
  (active); INV-15 added by this phase.
- [`2026-05-31-phase2a-resolve-design.md`](./2026-05-31-phase2a-resolve-design.md)
  — Phase 2a spec (predecessor; entity substrate).
- `~/Documents/Projects/.plans/amanuensis/phase2a-resolve-2026-05-31{,-synthesis,-tasks}.md`
  — Phase 2a authoritative plan triple (structural template for the
  Phase 2b plan files).
- `HISTORY.md` 2026-05-31 entry — Phase 2a ship record (defects
  caught, deferred follow-ups, final-validation transcript).
