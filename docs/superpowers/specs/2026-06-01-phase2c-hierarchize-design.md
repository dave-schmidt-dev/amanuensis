# Phase 2c (Hierarchize) — Design Spec

**Project:** amanuensis
**Phase:** 2c (probandum hierarchies) — third and final sub-project of Phase 2 (Map)
**Status:** spec drafted 2026-06-01
**Authoritative invariants:** [`INVARIANTS.md`](../../../INVARIANTS.md)
**Architecture reference:** [`docs/architecture.md`](../../architecture.md)
**Predecessor:** Phase 2b (Connect) shipped 2026-06-01 — see `HISTORY.md`
**Research basis:** the Wigmore + Walton + ACH triad established in
`synthesis/distillation-pipeline-architecture-2026-05-28.md` (Layer 4).

---

## Scope decomposition (why Phase 2c is its own spec)

Phase 2 (Map) decomposes into three sub-projects with strict dependency
order: Resolve → Connect → Hierarchize.

- **Phase 2a (Resolve) — shipped 2026-05-31.** Cross-document entity
  identity; `mappings/entities/`, `mappings/resolutions/`, INV-12/13/14.
- **Phase 2b (Connect) — shipped 2026-06-01.** Cross-document
  support/attack/undercut edges between atoms; `mappings/relations/`,
  INV-15.
- **Phase 2c (Hierarchize)** — this spec. Probandum trees built on top
  of Phase 2b's cross-doc edges.

Phase 2c is the third and final Phase 2 sub-project. After Phase 2c
ships, Phase 3 (Extend) and Phase 4 (Synthesize) follow.

---

## Goal

Phase 2c (Hierarchize) builds the **probandum-hierarchy** layer of the
project's evidence chart — the Wigmore-style tree that connects the
"ultimate proposition" being investigated down through penultimate +
interim probanda to evidentiary leaves (atoms and cross-doc edges).

The mechanism extends the existing extractor+auditor pattern:

- A **macroscopic** pass (CLI-driven): the supervisor declares the
  ultimate probandum + penultimate probanda from the engagement's
  controlling-law / engagement-scope artifacts. Top-down.
- A **microscopic** pass (LLM-driven): a new `amanuensis:map:hierarchize`
  skill proposes interim probanda + probandum-edge candidates that
  fan-out below each penultimate probandum. Bottom-up to meet the top.
- The existing (Phase 2b-extended) `amanuensis:map:audit` skill
  validates each candidate (warrant defensibility + lineage + scheme
  classification + alternatives discipline).
- Reconciliation auto-raises clarifications on broken lineage, missing
  scheme classification, or absent alternatives.

Phase 2b's `CrossDocRelation` records carry the join keys Phase 2c needs:
every probandum-edge whose child is a `cross-doc-relation` references a
record that already passes INV-15 (shared resolved entities). This makes
Phase 2b's substrate the deterministic precondition for Phase 2c's
trees, formalized as new invariants INV-16 / INV-17 / INV-18.

---

## In scope

1. `Probandum` schema — a proposition statement at a hierarchy level
   (`ultimate` / `penultimate` / `interim`).
2. `ProbandumEdge` schema — supports/attacks/undercuts edge from a
   parent probandum to a child (probandum, atom, or cross-doc-relation).
3. `ProbandumSupersede` + `ProbandumEdgeSupersede` schemas — mirror
   Phase 2a / 2b supersede pattern; immutability per INV-13.
4. **INV-16** — Probandum hierarchy is a tree (no cycles in the
   probandum-edge graph).
5. **INV-17** — Every probandum's lineage traces upward to an
   `ultimate` probandum (lineage completeness).
6. **INV-18** — Every `interim` and `penultimate` probandum has at
   least one child via `ProbandumEdge` (no leaf probanda above the
   atom level).
7. Walton-scheme catalogue: `Probandum.scheme` is a closed-vocabulary
   field validated against a per-engagement Walton-scheme registry
   (mirrors INV-10's predicate-vocabulary pinning).
8. ACH-style alternative-hypothesis enforcement: every `penultimate`
   and `interim` probandum carries `alternatives_considered:
   list[str]`; the macroscopic pass requires ≥1 alternative on each.
9. Hierarchize role (`amanuensis:map:hierarchize`) — proposes interim
   probanda + edge candidates from atom + cross-doc-relation clusters
   anchored under a penultimate probandum.
10. Auditor role extension (`amanuensis:map:audit`) — gains a code path
    for `Probandum` + `ProbandumEdge` candidate validation.
11. Reconciliation-gate extension — `_build_probandum_edge` mirrors
    Phase 2b `_build_cross_doc_relation`; auto-raises
    `lineage-incomplete` and `scheme-missing` clarifications.
12. `amanuensis map probandum` CLI sub-family (`add`, `list`, `show`,
    `lineage`, `link`, `supersede`).
13. Web-app additions: `/probanda` list + detail routes; tree
    visualization (Cytoscape's tree layout) replacing the section-graph
    when a probandum is selected.
14. Static-export additions: per-probandum-lineage report page; full
    probandum tree appendix.
15. Per-engagement Walton-scheme registry snapshot (parallels Phase 2a
    entity-kinds registry, with the same `INV-10` snapshot discipline).
16. Integration-based gate: extension of the Phase 2b 3-document
    fixture asserting ≥1 ultimate probandum + ≥2 penultimate + ≥3 interim
    probanda + complete lineage to leaves.
17. End-to-end Playwright spec exercising the supervisor macroscopic
    flow (declare ultimate + penultimate) + microscopic auditor view.

## Out of scope (deferred to Phase 2c.5 or beyond)

- **Full Walton critical-questions checklist per scheme.** Phase 2c
  ships the scheme as a closed-vocab field; the per-scheme critical-
  questions matrix + PASS/FAIL/N/A tracking is Phase 2c.5.
- **Full ACH matrix.** Phase 2c ships `alternatives_considered` as a
  free-text list field; the structured per-alternative consistency
  matrix is Phase 2c.5.
- **Tetlock-style confidence calibration.** Phase 2c uses the existing
  `confidence: high/medium/low` enum; full Tetlock calibration is a
  Phase 4 (Synthesize) delivery-time concern.
- **Hand-authored probandum edges via web POST.** Edges enter the
  substrate via the macroscopic CLI flow or via Hierarchizer dispatch
  + Auditor gate; no web POST endpoint.
- **Multi-tree probandum graphs.** Phase 2c assumes ONE ultimate
  probandum per workspace (the "engagement question"). Multiple
  parallel trees become a Phase 3 concern.
- **Probandum-edge attacks on Phase 1 intra-doc relations.** Phase 2c
  edge children are limited to `probandum` / `atom` / `cross-doc-relation`.
  Intra-doc `Relation` records can become edge children in a later
  cycle if needed.
- **Pre-population of probanda from engagement-spec documents.**
  Phase 2c ships the macroscopic CLI; auto-extraction of the engagement
  scope into top-level probanda is a Phase 4 capability.

---

## Data model

### Probandum

A new Pydantic class in `src/amanuensis/schemas/probandum.py`:

```python
class Probandum(BaseModel):
    """A proposition statement in the probandum hierarchy.

    Notes
    -----
    - ``kind`` ∈ {ultimate, penultimate, interim} captures position
      in the Wigmore tree.
    - ``scheme`` is the Walton argument scheme classification; closed
      vocabulary per-engagement (INV-10 snapshot pattern).
    - ``alternatives_considered`` is the ACH-discipline ledger; ≥1
      entry required on penultimate + interim per INV-19 (future).
    - ``provenance_id`` is volatile for canonical-form hashing.
    """

    model_config = ConfigDict(strict=True, extra="forbid")
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    id: str                               # p-<hash> ; content-addressable
    statement: str                        # the proposition itself
    kind: Literal["ultimate", "penultimate", "interim"]
    scheme: str                           # Walton scheme name (closed vocab)
    alternatives_considered: list[str]    # ACH alternative hypotheses
    confidence: Literal["high", "medium", "low"]
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1
```

**Id prefix:** `p-` (probandum).

**Field rationale:**
- `statement` is free-text (no closed vocab) because the proposition
  is the engagement's own subject matter.
- `kind`'s three-level Wigmore taxonomy (Anderson/Schum/Twining 2005)
  is fixed; matching the synthesis doc.
- `scheme` is a closed-vocabulary field; allowed values come from the
  per-engagement Walton-scheme snapshot under
  `mappings/walton-scheme-snapshot.yaml`.
- `alternatives_considered` is REQUIRED non-empty for `penultimate`
  and `interim` per ACH discipline; the gate test enforces this.

### ProbandumEdge

A new Pydantic class in `src/amanuensis/schemas/probandum_edge.py`:

```python
class ProbandumEdge(BaseModel):
    """Directed warrant-bearing edge from a parent probandum to a child.

    Children may be other probanda, atoms, or cross-doc relations —
    forming the Wigmore tree's evidence-to-conclusion paths.
    """

    model_config = ConfigDict(strict=True, extra="forbid")
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    id: str                               # q-<hash> ; content-addressable
    parent_probandum_id: str              # p-<hash> of parent
    child_id: str                         # p-/a-/x- prefixed child id
    child_kind: Literal["probandum", "atom", "cross-doc-relation"]
    child_source_id: str | None           # required when child_kind=atom
    kind: Literal["supports", "attacks", "undercuts"]
    warrant: str
    warrant_defensibility: Literal[
        "literature-backed", "methodology-derived",
        "conventional", "contested",
    ]
    warrant_basis: str
    confidence: Literal["high", "medium", "low"]
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1
```

**Id prefix:** `q-` (edges, picking the next available letter after
Phase 2b's `x-` for cross-doc).

**`child_source_id`:** required ONLY when `child_kind == "atom"`
(matches the Atom schema's `source_id` resolution; for `probandum` and
`cross-doc-relation` children, the source is implicit).

**Why a separate edge class** (vs. embedding child refs on Probandum):
mirror the Phase 1 `Relation` + Phase 2b `CrossDocRelation` pattern —
edges are first-class records with their own provenance, supersede
chain, and content-addressable identity. Embedding child lists would
break the immutability-by-content-hash discipline.

### Supersede classes

`ProbandumSupersede` (prefix `u-`) and `ProbandumEdgeSupersede` (prefix
`o-`) mirror Phase 2a/2b supersede patterns exactly:

```python
class ProbandumSupersede(BaseModel):
    id: str                               # u-<hash>
    supersedes_id: str                    # p-<hash>
    superseded_by_id: str                 # p-<hash>
    kind: Literal["probandum"] = "probandum"
    reason: str
    provenance_id: str
    role_attributions: list[RoleAttribution]
    at: AwareDatetime
    schema_version: int = 1

class ProbandumEdgeSupersede(BaseModel):
    id: str                               # o-<hash>
    supersedes_id: str                    # q-<hash>
    superseded_by_id: str                 # q-<hash>
    kind: Literal["probandum-edge"] = "probandum-edge"
    reason: str
    provenance_id: str
    role_attributions: list[RoleAttribution]
    at: AwareDatetime
    schema_version: int = 1
```

Both kinds get the immutability guard + non-empty reason validator
established for Phase 2b's supersede in the M2b cleanup pass.

### Walton-scheme registry

A new YAML registry at `mappings/walton-scheme-snapshot.yaml` (parallels
`mappings/entity-vocabulary-snapshot.yaml`). Schema:

```yaml
version: 1
schemes:
  - name: argument-from-expert-opinion
    description: An expert E asserts P; therefore P.
  - name: argument-from-witness-testimony
    description: Witness W reports observing P; therefore P.
  - name: argument-from-temporal-correlation
    description: Event A preceded event B; therefore A caused B.
  - name: argument-from-cluster-heuristic
    description: Entity X shares cluster-defining attributes with class C; therefore X is in C.
  # ... per-engagement additions
```

A generic starter registry ships at
`vocabularies/generic/walton-schemes.yaml` (parallels
`vocabularies/generic/entity-kinds.yaml`); per-engagement extensions
land via `amanuensis map walton-scheme snapshot --extend`.

---

## Filesystem layout

Extends the `mappings/` namespace established in Phase 2a + 2b:

```text
mappings/
  entities/e-<hash>.md                       (existing — Phase 2a)
  resolutions/j-<hash>.yaml                  (existing — Phase 2a)
  relations/x-<hash>.yaml                    (existing — Phase 2b)
  supersedes/t-<hash>.yaml                   (existing — Phase 2a EntitySupersede)
  supersedes/s-<hash>.yaml                   (existing — Phase 2a ResolutionSupersede)
  supersedes/v-<hash>.yaml                   (existing — Phase 2b CrossDocRelationSupersede)
  supersedes/u-<hash>.yaml                   (NEW — ProbandumSupersede)
  supersedes/o-<hash>.yaml                   (NEW — ProbandumEdgeSupersede)
  probanda/p-<hash>.md                       (NEW — Probandum records)
  probandum-edges/q-<hash>.yaml              (NEW — ProbandumEdge records; pure YAML)
  walton-scheme-snapshot.yaml                (NEW — closed scheme vocabulary)
  walton-scheme-archive/<hash>.yaml          (NEW — prior snapshots)
  entity-vocabulary-snapshot.yaml            (existing)
  provenance/<prov-id>.yaml                  (existing — extended for new activities)
  replay-log/                                (existing — extended)
```

---

## Invariant additions

### INV-16 (new) — Probandum hierarchy is a tree (no cycles)

- **Status:** active (gated)
- **Established:** Phase 2c
- **Property:** The directed graph induced by `ProbandumEdge` records
  with `child_kind == "probandum"` MUST be acyclic. Walking parent-to-
  child via probandum-only edges from any node reaches a leaf set
  (atoms / cross-doc-relations / probanda with no outgoing edges) in
  finite steps. Attempting to write a `ProbandumEdge` whose
  parent-to-child relation would close a cycle raises
  `ProbandumCycleViolation` at `Substrate.add_probandum_edge`.
- **Gate test:** `tests/invariants/test_probandum_tree.py` — five
  cases: (1) clean tree passes; (2) self-loop (`p1 → p1`) rejected;
  (3) two-cycle (`p1 → p2 → p1`) rejected; (4) three-cycle rejected;
  (5) deep linear chain (10 levels) passes.
- **Rationale:** Wigmore trees are trees; cycles would make lineage
  walking non-terminating + provenance attribution ambiguous.

### INV-17 (new) — Probandum lineage completes to an `ultimate`

- **Status:** active (gated)
- **Established:** Phase 2c
- **Property:** Every non-`ultimate` probandum has at least one parent
  probandum-edge AND its transitive parent-walk reaches at least one
  `ultimate` probandum. Orphan probanda (kind=interim or penultimate
  with no parent edge) are violations.
- **Gate test:** `tests/invariants/test_probandum_lineage.py` — four
  cases: (1) clean tree with full lineage passes; (2) orphan interim
  probandum rejected; (3) penultimate without parent (linking to an
  ultimate) rejected; (4) chain that ends at a `penultimate` instead
  of an `ultimate` rejected.
- **Rationale:** matches the synthesis doc's "probandum lineage check"
  verification step. Findings without an ultimate-rooted lineage are
  not part of the engagement's answer.

### INV-18 (new) — Closed Walton-scheme vocabulary

- **Status:** active (gated)
- **Established:** Phase 2c
- **Property:** Every `Probandum`'s `scheme` field MUST appear in the
  per-engagement `mappings/walton-scheme-snapshot.yaml`. Unknown
  schemes are rejected by `Substrate.add_probandum`.
- **Gate test:** `tests/invariants/test_probandum_scheme.py` — three
  cases: (1) scheme in snapshot passes; (2) scheme absent from snapshot
  rejected; (3) snapshot file missing causes
  `SubstrateNotFound`.
- **Rationale:** matches INV-5 (closed predicate vocabulary) + INV-10
  (per-distillation snapshot) discipline for the synthesis layer's
  warrant-typology field.

### INV-9 (existing, EXTENDED)

Phase 2c gate test extends `tests/invariants/test_intra_doc_only.py`
with one new case: no probandum (`p-`) or probandum-edge (`q-`) file
exists under `distillations/<src>/`. Same pattern as Phase 2b's INV-9
extension for cross-doc relation files.

### INV-12 (existing, EXTENDED gate)

`tests/invariants/test_mappings_namespace_scoped.py` gains cases:
- A `ProbandumEdge` whose `child_kind == "atom"` and `child_id` /
  `child_source_id` reference a non-existent atom is a violation.
- A `ProbandumEdge` whose `child_kind == "cross-doc-relation"` and
  `child_id` references a non-existent cross-doc relation is a
  violation.
- A `Probandum` filed outside `mappings/probanda/` is a violation.

### INV-13 (existing, unchanged)

`Probandum`, `ProbandumEdge`, and their supersedes inherit immutability.
`tests/invariants/test_mappings_immutability.py` parametrized to add
the four new record kinds.

---

## Role decomposition + dispatch

### Hierarchize role (NEW)

- **Skill file:** `src/amanuensis/skills/map_hierarchize.md`
- **Frontmatter:** `name: map_hierarchize`, `role: hierarchize`,
  `command: amanuensis map hierarchize`, `stub: false`.
- **Input contract:** a JSON cluster keyed by a penultimate probandum:

  ```json
  {
    "parent_probandum_id": "p-<hash>",
    "parent_statement": "<text>",
    "ultimate_probandum": {"id": "p-<hash>", "statement": "..."},
    "candidate_evidence": [
      {"kind": "atom", "id": "a-<hash>", "source_id": "...", "text": "...", "predicate": "..."},
      {"kind": "cross-doc-relation", "id": "x-<hash>", "warrant": "...", "shared_entities": [...]},
      ...
    ],
    "walton_schemes": ["scheme-name", ...]
  }
  ```

- **Output contract:** a JSON list of proposed interim Probanda + edge
  candidates linking them to the parent. Two-part output:

  ```json
  {
    "interim_probanda": [{"statement": "...", "kind": "interim", "scheme": "...", "alternatives_considered": ["..."], "confidence": "medium"}, ...],
    "probandum_edges": [{"parent_probandum_id": "p-...", "child_kind": "probandum", "child_id": "<index-into-interim-probanda>", "kind": "supports", "warrant": "...", "warrant_defensibility": "...", "warrant_basis": "...", "confidence": "..."}, ...]
  }
  ```

  The reconciler resolves `<index>` references after writing the
  interim probanda + computing their content-addressable ids.

### Auditor role (EXTENDED)

Existing `amanuensis:map:audit` skill gains the probandum branch:

1. **Shape compliance** — required fields present per Probandum +
   ProbandumEdge schemas.
2. **INV-17 lineage precondition** — every proposed edge's parent must
   already trace to an ultimate via existing edges (the auditor walks
   `latest_probandum_for` chains).
3. **INV-18 closed-vocab** — `scheme` in the snapshot.
4. **ACH discipline** — `alternatives_considered` non-empty for
   `penultimate`/`interim` probanda.
5. **Cycle detection** — auditor pre-checks INV-16 to avoid noisy
   reconciler rejections.
6. **Warrant defensibility** — same as Phase 2b's edge audit.

### Dispatch flow

`amanuensis map` orchestrator gains a new phase after Connect:

1. **Macroscopic preflight.** Verify ≥1 `Probandum` with
   `kind=ultimate` exists. If not, the phase is a no-op (supervisor
   must declare the ultimate via CLI first).
2. **Penultimate enumeration.** For each `penultimate` probandum,
   gather candidate evidence: (a) atoms whose resolutions point to
   entities that the parent's existing children reference, (b)
   cross-doc relations whose `shared_entities` touch the same entity
   set, (c) interim probanda already linked.
3. **Dispatch enqueue.** One Hierarchize call per penultimate (or per
   missing-branch hint).
4. **Reconciliation.** `_build_probandum_edge` + `_build_probandum`
   per candidate; INV-16 / INV-17 / INV-18 failures raise
   clarifications.
5. **Replay-log entry.**

---

## Reconciliation gate

The existing `src/amanuensis/dispatch/reconcile.py` module gains:

### `_build_probandum(candidate, substrate, prov, role_attributions) -> Probandum | None`

Same pattern as Phase 2b's `_build_cross_doc_relation`. Validates
shape → checks INV-18 scheme → checks INV-19 (alternatives non-empty
for non-ultimate) → writes via `substrate.add_probandum`. Auto-raises
`scheme-missing` clarification on INV-18 failure.

### `_build_probandum_edge(candidate, substrate, prov, role_attributions) -> ProbandumEdge | None`

Validates shape → resolves child by `(child_kind, child_id,
child_source_id)` → checks INV-16 (no cycle) → INV-17 (parent traces
to ultimate) → writes via `substrate.add_probandum_edge`. Auto-raises
`lineage-incomplete` clarification on INV-17 failure.

### `_auto_raise_lineage_clarification(...)` + `_auto_raise_scheme_clarification(...)` helpers

Mirror `_auto_raise_resolution_clarification` from Phase 2b. Two new
Clarification kinds:
- `lineage-incomplete` — proposed edge cannot reach an ultimate.
- `scheme-missing` — proposed probandum's scheme not in snapshot.

The Clarification schema's `kind` Literal gets extended additively.

---

## CLI surface

New sub-commands under `amanuensis map probandum`:

| Sub-command | Behavior |
|---|---|
| `map probandum add <statement> --kind {ultimate,penultimate,interim} --scheme NAME --alternatives "..." [--confidence ...]` | Supervisor authors a probandum (typically macroscopic-pass: ultimate + penultimate). Takes the workspace flock. |
| `map probandum list [--kind K] [--scheme S]` | Filterable list. Read-only. |
| `map probandum show <id>` | Detail: statement, kind, scheme, alternatives, confidence, lineage (up + down), provenance, supersede chain. Read-only. |
| `map probandum lineage <id>` | Walks the lineage from this probandum up to root and down to leaves. Renders as an indented tree. Read-only. |
| `map probandum link <parent-id> <child-id> --kind {supports,attacks,undercuts} --warrant "..." --warrant-basis "..." [--warrant-defensibility ...] [--confidence ...]` | Supervisor manually authors an edge (typically connecting penultimate → ultimate). Takes the flock. |
| `map probandum supersede <old-id> <new-id> --reason "..."` | Correction for a probandum record. Takes the flock. |
| `map probandum-edge supersede <old-id> <new-id> --reason "..."` | Correction for an edge record. Takes the flock. |

New sub-commands under `amanuensis map walton-scheme`:

| Sub-command | Behavior |
|---|---|
| `map walton-scheme show` | Display current snapshot. Read-only. |
| `map walton-scheme snapshot [--extend]` | Pin the active registry as `mappings/walton-scheme-snapshot.yaml`. `--extend` archives the prior and writes a new one. Takes the flock. |

---

## Web app additions

### New routes

In `src/amanuensis/web/routes/probanda.py`:

| Method | Path | Behavior |
|---|---|---|
| GET | `/probanda` | Filterable list (`?kind=`, `?scheme=`). HTML page. |
| GET | `/probanda/<id>` | Detail page: statement, lineage (up + down), edges (incoming + outgoing), provenance, supersede chain. |
| GET | `/probanda/<id>/tree` | Cytoscape tree visualization rooted at this probandum (lazy-loaded JSON fragment for the cytoscape data). |

In `src/amanuensis/web/routes/probandum_edges.py`:

| Method | Path | Behavior |
|---|---|---|
| GET | `/probandum-edges/<id>` | Detail page: endpoints (parent + child), warrant, provenance, supersede chain. |

### Entity-detail page extension

The existing `/entities/<id>` page gains a "Probanda referencing this
entity" section listing probanda whose statements mention the entity's
canonical name (cross-reference via simple substring match — heuristic,
acceptable per spec).

### Cytoscape tree visualization

A new view at `/probanda/<id>/tree` uses Cytoscape's `dagre` or `cose`
hierarchical layout. Nodes: probanda (filled circles, color by kind),
atoms (squares), cross-doc relations (diamonds). Edges: colored by
`kind`. Replaces the section-relation graph for this view.

Soft-cap fallback: if tree node count exceeds 500, default to
collapsed-by-default; supervisor expands branches manually.

---

## Static export additions

`amanuensis export`:

1. **New page: `probandum-tree.html`** — full tree of every ultimate
   probandum in the workspace, expandable per-branch.
2. **Per-probandum lineage page** — for each probandum, a page showing
   its full ancestry + descendants.
3. **Workspace-appendix bundle extension** — the new pages are
   emitted alongside Phase 2b's `cross-doc-relations.html` +
   `entities/<id>.html`.
4. **INV-8 render-purity** — same substrate → same bytes.

---

## Gate tests + validation

### New / extended test files

| Test file | Purpose | New / Extended |
|---|---|---|
| `tests/schemas/test_probandum.py` | Probandum schema. | NEW |
| `tests/schemas/test_probandum_edge.py` | Edge schema. | NEW |
| `tests/schemas/test_probandum_supersede.py` | Supersede schema. | NEW |
| `tests/schemas/test_probandum_edge_supersede.py` | Edge supersede schema. | NEW |
| `tests/fs/test_probandum_io.py` | Substrate IO. | NEW |
| `tests/fs/test_probandum_edge_io.py` | Substrate IO. | NEW |
| `tests/fs/test_walton_scheme_snapshot.py` | Snapshot IO. | NEW |
| `tests/invariants/test_probandum_tree.py` | INV-16, 5 cases. | NEW |
| `tests/invariants/test_probandum_lineage.py` | INV-17, 4 cases. | NEW |
| `tests/invariants/test_probandum_scheme.py` | INV-18, 3 cases. | NEW |
| `tests/invariants/test_intra_doc_only.py` | EXTEND — probandum/edge under distillations/. | EXTEND |
| `tests/invariants/test_mappings_namespace_scoped.py` | EXTEND — missing-atom/relation refs. | EXTEND |
| `tests/invariants/test_mappings_immutability.py` | EXTEND — probandum + 3 new record kinds. | EXTEND |
| `tests/dispatch/test_probandum_reconcile.py` | Reconciler tests. | NEW |
| `tests/dispatch/test_role_write_isolation.py` | EXTEND — hierarchize role. | EXTEND |
| `tests/cli/test_map_probandum.py` | CLI tests. | NEW |
| `tests/cli/test_map_walton_scheme.py` | CLI tests. | NEW |
| `tests/web/test_probanda_routes.py` | Web routes. | NEW |
| `tests/export/test_static_export_probandum.py` | Export additions. | NEW |
| `tests/integration/test_phase2c_hierarchize_end_to_end.py` | 3-doc fixture extended. | NEW |
| `tests/e2e/test_phase2c_tree_flow.py` | Playwright. | NEW |

### Final-validation gate

Pass criteria (extending Phase 2b's):

- ≥1100 fast pytest cases pass (1019 baseline + ~80–100 new)
- 54 invariants pass (51 Phase 2b baseline + 3 new INV-16/17/18)
- pyright strict 0 errors
- ruff + vulture clean
- 16 Playwright specs pass (15 baseline + 1 new)
- Structural smoke on the 3-distillation fixture produces ≥1 ultimate
  + ≥2 penultimate + ≥3 interim probanda with complete lineage.

---

## Risks + deferrals

### Risks (mitigation candidates)

1. **Tree-vs-DAG temptation.** Some legal-reasoning patterns produce
   probanda that legitimately participate in multiple lineages (e.g.,
   a witness's credibility is evidence for several distinct findings).
   *Mitigation:* INV-16 enforces tree; deal with DAG semantics by
   duplicating sub-trees when the same evidence participates in
   multiple branches. The synthesis doc supports this — Wigmore
   charts use copy-by-reference at presentation time, not at data
   time.
2. **Walton-scheme catalogue scope.** A generic scheme catalogue may
   not cover engagement-specific argument patterns. *Mitigation:* the
   `--extend` flow on `map walton-scheme snapshot` lets the supervisor
   add per-engagement schemes; the per-engagement registry is
   archived.
3. **Macroscopic-pass adoption friction.** A supervisor MUST author the
   ultimate + penultimate probanda before Hierarchize can run anything
   useful; this is a hard prerequisite. *Mitigation:* the CLI provides
   clear errors + an `amanuensis map probandum --bootstrap` helper
   that scaffolds an empty tree.
4. **Cycle detection cost.** INV-16 walks must be efficient at scale
   (1000+ probanda). *Mitigation:* incremental cycle detection
   (compute child-side reachability set on each edge write); store
   cached set in memory only (substrate stays content-addressable).
5. **ACH text-field drift.** `alternatives_considered: list[str]` is
   free text; supervisors can write "n/a" and pass the gate.
   *Mitigation:* INV-19 (deferred to Phase 2c.5) will enforce
   structured alternative-hypothesis records. For Phase 2c, the
   non-empty check is the floor.
6. **Pre-engagement template absence.** Phase 2c assumes a generic
   Walton scheme registry covers the first engagement. *Mitigation:*
   document this in HISTORY's deferred items.

### Deferrals (explicit; not bugs)

- **Full Walton critical-questions matrix.** Phase 2c.5.
- **Full ACH inconsistency matrix.** Phase 2c.5.
- **Tetlock-style confidence calibration.** Phase 4 (delivery).
- **Multiple ultimate probanda per workspace.** Phase 3 candidate.
- **Probandum-edge attacks on intra-doc Relations.** Phase 3 candidate.
- **Auto-extraction of engagement-spec into top-level probanda.**
  Phase 4 (delivery).

---

## Module decomposition impact

| Module | Purpose | Depends on |
|---|---|---|
| `amanuensis.schemas.probandum` | `Probandum` schema | `schemas._shared` |
| `amanuensis.schemas.probandum_edge` | `ProbandumEdge` schema | `schemas._shared` |
| `amanuensis.schemas.probandum_supersede` | `ProbandumSupersede` schema | `schemas._shared` |
| `amanuensis.schemas.probandum_edge_supersede` | `ProbandumEdgeSupersede` schema | `schemas._shared` |
| `amanuensis.fs` (EXTENDED) | `add_probandum*`, `list_probandum*`, `latest_probandum_for`, `add_probandum_edge*`, `list_probandum_edges`, cycle detection helper, lineage walker | (extension only) |
| `amanuensis.vocabulary.walton_schemes` | Per-engagement Walton scheme registry loader | `schemas`, `fs` |
| `amanuensis.dispatch.reconcile` (EXTENDED) | `_build_probandum`, `_build_probandum_edge`, two new clarification auto-raisers | (extension only) |
| `amanuensis.dispatch.hierarchize_orchestrator` | Penultimate cluster enumeration + dispatch | `schemas`, `fs` |
| `amanuensis.cli.map` (EXTENDED) | `map probandum / walton-scheme` sub-commands | (extension only) |
| `amanuensis.web.routes.probanda` | Read-only probandum routes + tree fragment | `schemas`, `fs` |
| `amanuensis.web.routes.probandum_edges` | Edge detail route | `schemas`, `fs` |
| `amanuensis.export.workspace_appendix` (EXTENDED) | Probandum-tree page + per-probandum lineage pages | (extension only) |
| `amanuensis.skills.map_hierarchize` | Hierarchize skill markdown | (none) |
| `amanuensis.skills.map_audit` (EXTENDED) | Audit probandum candidates | (none) |

---

## Milestone breakdown (preliminary)

- **M1 — Schema foundation.** Four new schemas + content-addressable
  ids + immutability.
- **M2 — Substrate IO.** `add_probandum*` / `add_probandum_edge*` /
  `list_*` / `latest_probandum_for`.
- **M3 — Walton-scheme registry + snapshot pinning.** Registry loader
  + INV-18 substrate gate.
- **M4 — INV-16 (cycle detection) + INV-17 (lineage) gates.**
  Substrate-side + invariant test files.
- **M5 — INV-9 / INV-12 / INV-13 extensions** for new record kinds.
- **M6 — Reconciliation gate.** `_build_probandum*` +
  `_build_probandum_edge*` + two new clarification auto-raisers.
- **M7 — Hierarchize skill + Auditor extension.** Skill markdown +
  smoke.
- **M8 — Dispatch orchestrator.** Penultimate enumeration + cluster
  dispatch.
- **M9 — CLI surface.** `map probandum` + `map walton-scheme`
  sub-commands.
- **M10 — Web routes + Cytoscape tree visualization.**
- **M11 — Static export additions.**
- **M12 — INV charter promotion + documentation sweep.**
- **M13 — Integration + E2E + final validation.**

**Total tasks (estimate):** ~80–95 across 13 milestones.
**Estimated commits:** ~70–85.

---

## See also

- [`docs/architecture.md`](../../architecture.md)
- [`INVARIANTS.md`](../../../INVARIANTS.md)
- [`2026-05-31-phase2a-resolve-design.md`](./2026-05-31-phase2a-resolve-design.md)
- [`2026-05-31-phase2b-connect-design.md`](./2026-05-31-phase2b-connect-design.md)
- `synthesis/distillation-pipeline-architecture-2026-05-28.md` — Layer 4
  source material (Wigmore + Walton + ACH).
- `HISTORY.md` 2026-06-01 entries — Phase 2b ship + cleanup records.
