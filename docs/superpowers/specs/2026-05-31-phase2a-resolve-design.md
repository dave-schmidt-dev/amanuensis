# Phase 2a (Resolve) — Design Spec

**Project:** amanuensis
**Phase:** 2a (entity resolution) — first sub-project of Phase 2 (Map)
**Status:** spec drafted 2026-05-31; awaiting user review before plan
**Authoritative invariants:** [`INVARIANTS.md`](../../../INVARIANTS.md)
**Architecture reference:** [`docs/architecture.md`](../../architecture.md)
**Predecessor:** Phase 1 (Distill) shipped 2026-05-30 — see `HISTORY.md`

---

## Scope decomposition (why Phase 2a is its own spec)

INV-9 names three Phase 2 (Map) deliverables: (1) cross-document entity
resolution, (2) cross-document support/attack edges, (3) probandum
hierarchies spanning sources. These have a strict dependency order —
edges can't reason across documents until operand-ref strings are
normalized; probandum trees can't aggregate atoms across sources until
edges exist. Together they're ~3x Phase 1's surface area in one spec,
which makes review and premortem coverage thin.

Phase 2 is therefore decomposed into three sub-projects, each getting
its own brainstorm → spec → plan → implementation cycle:

- **Phase 2a (Resolve)** — this spec. Entity resolution layer.
- **Phase 2b (Connect)** — future. Cross-doc support/attack edges built
  on top of Phase 2a's resolved entities.
- **Phase 2c (Hierarchize)** — future. Probandum hierarchies built on
  top of Phase 2b's cross-doc edges.

Each sub-project is independently shippable; each gets the full
brainstorm + external review + premortem discipline that caught 28+11
substantive issues in Phase 1.

---

## Goal

Phase 2a (Resolve) turns Phase 1's free-form `OperandRef.value` strings
(where `kind=entity`) into normalized cross-document canonical entity
ids, recorded as a separate substrate layer under a new workspace-level
`mappings/` namespace.

The mechanism mirrors Phase 1's extractor+auditor pattern: a
`amanuensis:map:resolve` skill proposes entity clusters and surface-form
aliases; an `amanuensis:map:audit` skill validates each cluster against
kind-specific rules; ambiguous cases auto-raise clarifications resolved
by the supervisor via the existing web-app surface.

Phase 1 atoms carry the join keys Phase 2a needs: every operand-ref of
`kind=entity` is a candidate target for resolution. Phase 1 deliberately
left `OperandRef.value` as a free-form string so this normalization
could happen without re-extraction.

---

## In scope

1. Canonical entity records (workspace-level, typed by a closed
   entity-kind vocabulary).
2. Resolution-event records (per `(source_id, atom_id, operand_index)
   → entity_id` join, immutable).
3. Supersede records (entity-level and resolution-level) for supervisor
   corrections that preserve immutability.
4. Resolver + Resolution-Auditor roles, dispatched through existing
   dispatch infrastructure (queue protocol, write-isolation, reconciliation
   gate — INV-11 reused).
5. `amanuensis map` CLI family (mirrors `distill` family shape).
6. Per-mapping entity-kind vocabulary snapshot (mirrors INV-10 at the
   mapping level).
7. Three new invariants (INV-12 / INV-13 / INV-14) governing the new
   substrate.
8. Two Phase-1-promised invariant gates that land here: the executable
   INV-9 intra-doc-only test, and the executable INV-2 no-harness-files
   test.
9. Web-app additions: entity list/show + resolution review + hover-by-
   entity highlighting in the existing Cytoscape graph view.
10. Static-export additions: entities + resolutions included in the
    per-source HTML bundle.
11. Integration-based gate: 3-document synthetic fixture with
    structurally-obvious right answers (~5 entities).

## Explicitly out of scope (Phase 2b / 2c / later)

- Cross-document support/attack edges — Phase 2b.
- Probandum hierarchies — Phase 2c.
- A separate intra-doc coreference pass — the resolver naturally clusters
  intra-doc and cross-doc surface forms under one canonical entity id;
  no separate intra-doc-only pass.
- Cross-vocabulary entity-kind reconciliation across workspaces — multi-
  workspace federation is Phase 3+.
- Redaction-aware ingest — already deferred from Phase 1's known-
  limitations list; remains deferred.
- Activating Constructive / Premortem stub roles in Phase 2a. Contrarian
  optionally activated for the brainstorm-review pass (per
  `~/.agent/prompts/plan.md`); Constructive overlaps the Resolution-
  Auditor; Premortem stays a stub.
- Prose-report surface and its dedicated INV-8 invariants-directory
  render-purity gate — explicitly deferred (Phase 4, or Phase 2c if a
  prose-report-of-mappings surface lands then).
- Hand-edit verifier for `source-mirror/paragraphs/` against manifest
  `content_sha256` (INV-8 escape hatch) — deferred to a future small
  task; not blocking 2a.

---

## Architecture overview

### Substrate additions (workspace-level)

```text
<workspace>/
  mappings/
    entity-vocabulary-snapshot.yaml       # closed entity-kind vocabulary; pinned at map init; INV-12
    entities/
      e-<hash>.md                         # frontmatter YAML + narrative body; immutable; INV-13
    resolutions/
      r-<hash>.yaml                       # pure YAML; one per (source, atom, operand-idx) → entity; immutable
    supersedes/
      s-<hash>.yaml                       # supersede record; old → new + reason + PROV
    replay-log/
      .next-seq                           # separate counter from distillations' replay-log
      <yyyy-mm-dd>/<seq:012d>.yaml        # one entry per map activity
    vocabulary-history/
      v-<hash>.yaml                       # superseded snapshots after governance-event extensions
    README.md                             # auto-generated index; INV-2 exception scoped under mappings/

  dispatch/outputs/
    map-resolve-<inputs-hash>/            # resolver workspace; INV-11 write-isolation
    map-audit-<inputs-hash>/              # audit workspace; INV-11
```

### Three new schemas

Added to `amanuensis.schemas` (one module per schema, mirroring Phase 1's
file-per-schema convention).

#### `Entity`
```python
class Entity(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    _VOLATILE_FIELDS = frozenset({"provenance_id"})

    id: str                              # content-addressable hash
    kind: str                            # MUST be in mappings/entity-vocabulary-snapshot.yaml
    canonical_name: str
    aliases: list[str]                   # surface forms seen across the corpus
    notes: str | None = None             # supervisor-authored disambiguation text
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1
```

#### `Resolution`
```python
class Resolution(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    _VOLATILE_FIELDS = frozenset({"provenance_id"})

    id: str
    source_id: str
    atom_id: str
    operand_index: int                   # zero-indexed into the atom's operands list
    entity_id: str
    confidence: Literal["high", "medium", "low"]
    basis: str                           # one-line rationale (rule fired / cluster cohesion / etc.)
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1
```

#### `ResolutionSupersede`
```python
class ResolutionSupersede(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    _VOLATILE_FIELDS = frozenset({"provenance_id"})

    id: str
    superseded_resolution_id: str
    replacement_resolution_id: str
    reason: str
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1
```

An analogous `EntitySupersede` is added for entity-level merges/splits;
shape mirrors `ResolutionSupersede` with `superseded_entity_id` /
`replacement_entity_id`.

### Module decomposition

No new top-level Python module. Additions:

- `amanuensis.schemas` — four new schema files (`entity.py`,
  `resolution.py`, `resolution_supersede.py`, `entity_supersede.py`)
  plus re-exports.
- `amanuensis.fs.Substrate` — new methods: `add_entity`,
  `add_resolution`, `add_resolution_supersede`, `add_entity_supersede`,
  `list_entities`, `list_resolutions`, `latest_resolution_for(source_id,
  atom_id, operand_index)`, `latest_entity_for(entity_id)`. Plus
  `list_distillations`, `list_relations`, `list_clarifications` as
  canonical enumerators (Phase-1 follow-up landed here).
- `amanuensis.validators` — new validators: `entity_kind_in_vocabulary`,
  `resolution_triple_exists`, `resolution_uniqueness_per_triple`.
- `amanuensis.cli` — new `map` subcommand group.
- `amanuensis.skills` — two new markdown skill files:
  `amanuensis-map-resolve.md` and `amanuensis-map-audit.md`.
- `amanuensis.web` — new routers for entities / resolutions /
  resolution-clarifications; extension to Cytoscape graph view for
  hover-by-entity highlighting.
- `amanuensis.export` — entity sidebar + inline resolution annotations
  in the single-source HTML bundle.

No new dispatch driver code path. The existing M6 driver, M7
reconciliation gate, and INV-11 write-isolation are reused unchanged
beyond parameterizing over the new role pair.

---

## Roles and dispatch shape

### Two new skills (bundled with the package)

- **`amanuensis:map:resolve`** — proposer. Reads `distillations/*/atoms/`
  + existing `mappings/entities/` (may be empty on first run) + the
  pinned `mappings/entity-vocabulary-snapshot.yaml`. Emits candidate
  entity records and candidate resolution records into
  `dispatch/outputs/map-resolve-<inputs-hash>/`. Skill body specifies
  the canonical workflow: cluster operand-ref surface forms by likely-
  same-entity using kind-specific rules; for each cluster propose either
  a new entity record or a link to an existing one. Forbidden from
  writing outside its dispatch subtree (INV-11).

- **`amanuensis:map:audit`** — validator. Reads
  `dispatch/outputs/map-resolve-*/` + the substrate. For each candidate:
  verify the kind matches the snapshot, verify cited operand-refs exist
  at the referenced `(source, atom, operand-index)` with `kind=entity`,
  verify cluster cohesion (no obvious cross-kind contamination), assign
  confidence. On disagreement → auto-raise a clarification (`kind ∈
  {resolution-disputed, resolution-ambiguous}`) via the existing
  clarification mechanism. Accepted candidates flow to `mappings/`;
  rejected ones flow to `dispatch/failures/`.

### Dispatch flow

```
orchestrator: amanuensis map
  → acquires workspace flock (5s timeout)
  → snapshots inputs_hash over (substrate state + entity-vocab snapshot)
  → enqueues dispatch/queue/map-resolve-<seq>.yaml
  → driver invokes :map:resolve skill (per-harness assignment in amanuensis.yaml)
  → resolver writes candidates to dispatch/outputs/map-resolve-<inputs-hash>/
  → orchestrator enqueues dispatch/queue/map-audit-<seq>.yaml (depends on resolver output)
  → driver invokes :map:audit skill
  → auditor writes verdicts to dispatch/outputs/map-audit-<inputs-hash>/
  → reconciliation: orchestrator reads verdicts, writes accepted (entity, resolution)
     records to mappings/, opens clarifications for disputed candidates,
     emits supersedes for any candidate that updates an existing resolution
  → writes mappings/replay-log entry; releases flock
```

Reconciliation reuses the existing M7.4 reconciliation-gate code path,
parameterized over the new role pair.

### CLI verbs (mirrors `distill` family)

- `amanuensis map` — run resolver + audit + reconcile once over current
  substrate.
- `amanuensis map status` — report (per-distillation and workspace-
  aggregate): operand-ref count, resolved count, unresolved count,
  open-clarification count, last map-run timestamp.
- `amanuensis map entity list` / `map entity show <id>` — read-only.
- `amanuensis map entity merge <a-id> <b-id> --canonical <id>
  --reason "..."` — emits `EntitySupersede` records (mutating).
- `amanuensis map resolution show <id>` — read-only; shows the supersede
  chain if any.
- `amanuensis map resolution supersede <old-id> --new-entity <entity-id>
  --reason "..."` — supervisor correction (mutating).
- `amanuensis map vocabulary show` — read-only.
- `amanuensis map vocabulary snapshot` — write/refresh the snapshot
  (governance event; archives prior snapshot to
  `mappings/vocabulary-history/`).

All `map *` commands check the INV-1 marker preflight. Read-only verbs
do NOT write to `mappings/replay-log/` (INV-4 read-only purity, mirrored
at the mapping layer). Mutating verbs acquire the workspace flock.

---

## Vocabulary discipline (entity-kind vocabulary)

Separate axis from Phase 1's predicate vocabulary. Snapshot lives at
`mappings/entity-vocabulary-snapshot.yaml`:

```yaml
schema_version: 1
mapping_id: <content-addressable hash of canonical workspace + snapshot time>
pinned_at: 2026-06-15T14:00:00Z
kinds:
  - id: party
    description: A named participant in the matter (plaintiff, defendant, intervenor, claimant).
    resolution_rules: [name-and-role-equivalence, organization-suffix-normalization]
  - id: person
    description: A natural person (witness, declarant, officer, counsel).
    resolution_rules: [full-name-parse, role-disambiguation]
  - id: organization
    description: A legal entity that is not itself a party (regulator, court, third party).
    resolution_rules: [organization-suffix-normalization, jurisdictional-disambiguation]
  - id: statute
    description: A statutory provision.
    resolution_rules: [bluebook-citation-parse]
  - id: case-citation
    description: A judicial decision cited as authority.
    resolution_rules: [bluebook-citation-parse, parallel-citation-merge]
  - id: instrument
    description: A document referenced in the matter (contract, exhibit, declaration, order).
    resolution_rules: [instrument-identifier-parse]
  - id: event
    description: A discrete dated occurrence (meeting, transaction, filing).
    resolution_rules: [date-and-participant-equivalence]
  - id: location
    description: A geographic or jurisdictional location.
    resolution_rules: [jurisdictional-canonicalization]
  - id: concept
    description: A defined or asserted abstraction (a market, a relationship type, a class).
    resolution_rules: [supervisor-only]   # always raises a clarification; no auto-rule
```

**Pinning** (mirrors INV-10):
- Snapshot is written ONCE at first `amanuensis map` invocation (or
  explicitly via `amanuensis map vocabulary snapshot`).
- Snapshot is content-addressed; hash recorded in the mapping's
  replay-log entry for the init activity.
- All resolver / audit / validator code reads the per-mapping snapshot.
  Never the global template.
- The global template lives at
  `~/.amanuensis/vocabularies/generic-entity-kinds.yaml` — a starting
  point, not a runtime dependency.

**Governance event for vocabulary extension** (mirrors Phase 1's
predicate-vocab governance pattern):
- Adding a new entity kind requires: human-proposed PR to the global
  template + test-suite validation + version-bumped registry commit.
- Then a per-mapping refresh: `amanuensis map vocabulary snapshot
  --extend` writes a NEW snapshot, archives the old one to
  `mappings/vocabulary-history/v-<hash>.yaml`. Resolutions written under
  the old snapshot are NOT auto-rewritten — they remain valid under the
  kind they were resolved against.

Phase 2a ships with the nine kinds above. The `concept` kind is
intentionally catch-all with `resolution_rules: [supervisor-only]` so
any operand-ref the resolver can't confidently kind-classify auto-raises
a clarification rather than being silently miscategorized.

---

## Lifecycle: resolution events and supersede

**Initial resolution** — orchestrator dispatches resolver + audit;
accepted resolutions write immutable, content-addressed YAML to
`mappings/resolutions/`. Every operand-ref of `kind=entity` must
either resolve, be tied to an open clarification, or fall outside scope
(operand `kind ≠ entity`).

**Supervisor correction (resolution-level).** When a supervisor needs to
retract or correct a resolution:
1. `amanuensis map resolution supersede <old-id> --new-entity <entity-id>
   --reason "..."`.
2. A new `Resolution` record is written for the same `(source, atom,
   operand_index)` triple pointing at the corrected entity.
3. A `ResolutionSupersede` record links old → new with reason and PROV.
4. Latest-state query walks the supersede chain (depth bounded in
   practice; typically 0-2).

**Supervisor correction (entity-level).** `amanuensis map entity merge
<a-id> <b-id> --canonical <a-id> --reason "..."` emits a new merged
`Entity` record plus per-target `EntitySupersede` records. Resolutions
pointing at the superseded entity are NOT auto-rewritten; the latest-
entity query walks the chain.

Storing supersedes at both layers keeps each layer's immutability tight
while making corrections cheap and audit-complete.

**Re-running `amanuensis map`.** Idempotent against fixed substrate.
Resolver sees existing entities + resolutions; only proposes
resolutions for un-resolved operand-refs OR raises supersede candidates
for low-confidence existing ones (with reason). The auditor gates as
always.

---

## New invariants

### INV-12 — `mappings/` is the home for all cross-document substrate artifacts
- **Status:** active (gated)
- **Property:** No cross-source artifact (entity record, resolution
  record, cross-doc relation [Phase 2b], probandum hierarchy [Phase 2c])
  is permitted outside `mappings/`. Per-distillation directories remain
  intra-doc.
- **Gate test:** `tests/invariants/test_mappings_namespace_scoped.py` —
  scans `distillations/<src>/` for any artifact referencing a different
  `source_id` and fails; scans `mappings/` and asserts every artifact
  either has no `source_id` (entity records) or references `source_id`s
  that exist in `distillations/`.
- **Rationale:** Makes the workspace's three-layer structure
  (per-source distillations / cross-source mappings / workspace-level
  iterations+delivery) deterministic. Future Phase 2b/2c artifacts have
  a known home.

### INV-13 — Entity and Resolution records are immutable; corrections issue supersede records
- **Status:** active (gated)
- **Property:** Once written, `Entity` / `Resolution` records are not
  rewritten. `EntitySupersede` / `ResolutionSupersede` records carry
  corrections with PROV.
- **Gate test:** `tests/invariants/test_mappings_immutability.py` —
  writes a resolution, attempts in-place rewrite via the Substrate API,
  asserts the rewrite refuses with `MutationOfImmutableRecord`. Plus a
  property test: same substrate + same `amanuensis map` run produces
  byte-identical `mappings/`.
- **Rationale:** Same content-addressing rationale as Phase 1's
  Atom/Relation immutability. Supersedes preserve audit trails (PROV-O
  direction: Activity → Entity).

### INV-14 — Resolution records key off the normalized `(source_id, atom_id, operand_index)` triple
- **Status:** active (gated)
- **Property:** A `Resolution` record's identity is determined by what
  it resolves (the triple) plus what it resolves to (the entity). Two
  non-superseded resolutions for the same triple cannot coexist.
- **Gate test:** `tests/invariants/test_resolution_uniqueness.py` — for
  every triple in the substrate, asserts at most one non-superseded
  `Resolution`. Catches the failure mode where a buggy resolver writes
  competing resolutions for the same operand.
- **Rationale:** The operand-ref is the unit of resolution; multiplicity
  would break "what entity does this operand point to?" — the most-used
  cross-doc query.

### Also lands during Phase 2a (Phase-1-promised gates)

- **`tests/invariants/test_intra_doc_only.py`** — INV-9's executable
  gate. With `mappings/` now existing, "cross-doc edges live in
  mappings/" is the contract this test enforces (no relation in
  `distillations/<src>/relations/` may reference an atom outside
  `<src>`).
- **`tests/invariants/test_no_harness_files.py`** — INV-2's executable
  gate. Scans the workspace root for forbidden filenames
  (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `README.md`).

---

## Web app and static export

### Web app additions
- `/entities` — list of entity records grouped by kind, with surface-
  form aliases. Search box (substring over `canonical_name` + `aliases`).
- `/entities/<id>` — entity detail: kind, canonical name, aliases, all
  resolutions pointing at it (linked back to per-source atoms),
  supersede chain if any.
- `/resolutions/<id>` — resolution detail: source/atom/operand triple,
  entity link, confidence, basis, PROV record, supersede chain.
- `/clarifications` — extended to show `kind ∈ {resolution-disputed,
  resolution-ambiguous}` clarifications alongside Phase 1's warrant-
  defensibility ones. Same resolve-form pattern; same flock discipline.
- Cytoscape graph view extended: hover an atom → highlight all atoms
  sharing any entity. Cross-doc edges themselves are Phase 2b; this is
  Phase 2a's visual cross-doc affordance.
- `Cache-Control: no-store` on substrate-derived responses (as Phase 1).

### Static export additions
- `amanuensis export --include-mappings` (default ON) — single self-
  contained HTML bundle that includes per-source atom listings PLUS the
  workspace-level entity registry as a sidebar. Resolutions are inlined
  into atom rendering (each `kind=entity` operand-ref shows the
  resolved entity name + a tooltip with the canonical id).
- INV-8 render-purity gate: existing
  `tests/export/test_static_export_smoke.py` extended to assert byte-
  identical output across runs given fixed substrate (including
  `mappings/`).
- The dedicated invariants-directory render-purity gate INV-8 promised
  "for Phase 2 when the prose-report surface lands" is NOT Phase 2a
  (still no prose-report surface). Defers to Phase 4 (or to whichever
  later Phase introduces a prose-report-of-mappings surface).

---

## Testing strategy (mirrors Phase 1 gates)

All of:
- pyright strict, ruff lint + format, vulture (min confidence 80) clean.
- Full pytest suite green.
- New invariants subset green (`pytest -m invariants`).
- Playwright E2E green.

### New test files
- `tests/schemas/test_entity.py` — validation, hashing, volatile-field-
  respect.
- `tests/schemas/test_resolution.py` — same.
- `tests/schemas/test_resolution_supersede.py` — same.
- `tests/schemas/test_entity_supersede.py` — same.
- `tests/validators/test_entity_kind_vocabulary.py` — kind ∈ snapshot;
  new kinds rejected.
- `tests/validators/test_resolution_triple_existence.py` — referenced
  atom + operand-index must exist; stale references rejected.
- `tests/fs/test_substrate_mappings.py` — `add_*` / `list_*` /
  `latest_*_for` semantics; atomic writes; supersede chain walk.
- `tests/skills/test_map_resolve_skill.py`,
  `tests/skills/test_map_audit_skill.py` — skill-frontmatter shape,
  JIT-loadable.
- `tests/dispatch/test_map_role_pair.py` — full resolver + audit +
  reconciliation flow against a synthetic 3-doc fixture; asserts entity
  records, resolution records, dispatched-role write-isolation (INV-11).
- `tests/cli/test_map_commands.py` — each `map` verb (marker preflight,
  flock, read-only purity, mutating-path replay-log writes).
- `tests/web/test_entities_routes.py`,
  `tests/web/test_resolutions_routes.py` — read-only routes +
  clarification-resolve form lock contention.
- `tests/integration/test_map_end_to_end.py` — the integration-based
  success gate. 3-doc synthetic fixture (two related contract drafts +
  a settlement instrument), ~5 shared entities. Runs `init → ingest x3
  → distill x3 → map → status → export`. Asserts the entity registry
  has the expected ~5 entities by canonical name and that the cross-doc
  query "atoms about entity X" returns the expected set.
- `tests/invariants/test_mappings_namespace_scoped.py`,
  `tests/invariants/test_mappings_immutability.py`,
  `tests/invariants/test_resolution_uniqueness.py`.
- `tests/invariants/test_intra_doc_only.py` (Phase-1-promised),
  `tests/invariants/test_no_harness_files.py` (Phase-1-promised).
- `tests/e2e/test_map_resolution_clarification.spec.ts` (Playwright) —
  supervisor opens an entity, opens a resolution-ambiguous
  clarification, resolves it, asserts the resolution gets written and
  the entity detail updates on reload.

### Synthetic fixture
Two related contract drafts plus a settlement instrument, ~5 shared
entities — kinds drawn from {party, person, organization, instrument,
event}. The fixture is hand-built and committed to the repo;
right-answers are obvious by inspection (a single supervisor can audit
the entire entity registry in under 5 minutes).

---

## Open follow-ups (Phase 2b handoff and small future tasks)

- **Cross-doc support/attack edges (Phase 2b)** will key off
  `mappings/entities/`. The `Relation` schema gets a new `cross_doc:
  bool = False` flag and an optional `endpoints_via_entity_id: str |
  None` field, OR Phase 2b introduces a separate `CrossDocRelation`
  schema. Decision deferred to 2b's brainstorm.
- **Probandum hierarchies (Phase 2c)** sit on top of cross-doc edges.
  Hierarchy schema deferred to 2c's brainstorm.
- **INV-8 render-purity invariants-directory gate** (the one INV-8
  promised "when the prose-report surface lands") — explicitly defers
  to Phase 4 (or Phase 2c if a prose-report-of-mappings surface ships
  there).
- **Hand-edit verifier for source-mirror paragraphs vs manifest
  `content_sha256`** (INV-8 escape hatch) — defer to a future small
  task; not blocking 2a.
- **Substrate enumerator API extensions** (`list_distillations`,
  `list_relations`, `list_clarifications` as canonical enumerators
  per HISTORY 2026-05-30 follow-ups) — naturally land in this phase as
  `list_entities` / `list_resolutions` are introduced; added in the
  same M as the mappings API extensions.
- **Redaction-aware ingest** — explicitly NOT Phase 2a; remains a Phase
  3+ candidate.
- **Activating Constructive / Premortem stub roles** — NOT Phase 2a.
  Contrarian optionally activated for the brainstorm-review pass per
  `~/.agent/prompts/plan.md`; Constructive overlaps the Resolution-
  Auditor; Premortem stays a stub.

---

## Next step

After user review of this spec: invoke `superpowers:writing-plans` to
produce the Phase 2a implementation plan (milestone breakdown, task
list, risks table, hard rollback points). The plan goes through the
standard discipline: draft → self-contrarian pass → external dispatch
(contrarian + auditor + constructive) → fresh-eyes premortem →
synthesis → task breakdown.
