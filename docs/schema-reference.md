# Schema Reference

The amanuensis substrate is filesystem-as-truth ([INV-8](../INVARIANTS.md#inv-8--substrate-is-the-source-of-truth)):
every artifact is a YAML or markdown file on disk, every artifact is a
Pydantic-validated record, every identity-carrying artifact is named by
a deterministic hash of its content. This document is the reference for
the Phase 1 schemas defined in `src/amanuensis/schemas/`, for the
content-addressable id scheme implemented in
`src/amanuensis/schemas/_hashing.py`, and for the on-disk layout the
filesystem layer (`src/amanuensis/fs/`) writes them to.

The companion document [`architecture.md`](./architecture.md) describes
the system as a whole; this document is the per-record reference.

The five Phase 1 **content-addressable** types are:

| Type | Module | Prefix | Volatile fields |
| --- | --- | --- | --- |
| `Atom` | `schemas/atom.py` | `a-` | `{provenance_id}` |
| `Relation` | `schemas/relation.py` | `r-` | `{provenance_id}` |
| `ProvenanceRecord` | `schemas/provenance.py` | `p-` | `set()` |
| `Clarification` | `schemas/clarification.py` | `c-` | `{status, resolved_at, resolved_by, resolution, raised_provenance_id, resolved_provenance_id}` |
| `IterationDirective` | `schemas/iteration.py` | `i-` | `{applied_at, applied_by, applied_outcome, issued_provenance_id, applied_provenance_id}` |

Phase 2a (Resolve) adds four more **content-addressable** types:

| Type | Module | Prefix | Volatile fields |
| --- | --- | --- | --- |
| `Entity` | `schemas/entity.py` | `e-` | `{provenance_id}` |
| `Resolution` | `schemas/resolution.py` | `j-` | `{provenance_id}` |
| `EntitySupersede` | `schemas/entity_supersede.py` | `t-` | `{provenance_id}` |
| `ResolutionSupersede` | `schemas/resolution_supersede.py` | `s-` | `{provenance_id}` |

Phase 2b (Connect) adds two more **content-addressable** types:

| Type | Module | Prefix | Volatile fields |
| --- | --- | --- | --- |
| `CrossDocRelation` | `schemas/cross_doc_relation.py` | `x-` | `{provenance_id}` |
| `CrossDocRelationSupersede` | `schemas/cross_doc_relation_supersede.py` | `v-` | `{provenance_id, at}` |

The remaining Phase 1 schemas — `ReplayLogEntry`, `Vocabulary`,
`VocabularyEntry`, `OperandTypeSchema` — are NOT content-addressable.
See [Non-content-addressable types](#non-content-addressable-types).

All Pydantic models in this package set
`model_config = ConfigDict(strict=True, extra="forbid")`. Strict mode
rejects implicit coercion (`"1"` is not an `int`); `extra="forbid"`
rejects unknown fields. Every tz-bearing datetime is `AwareDatetime`,
which rejects naive timestamps with error type `timezone_aware`.

---

## Schema reference (per-model)

The twelve Phase 1 model classes plus four Phase 2a (Resolve) model
classes, in dependency order. Each entry lists the model's purpose,
its fields (required and optional), and validation rules beyond plain
Pydantic typing.

### `AgentAttribution` (`schemas/_shared.py`)

Identifies who or what acted in a particular role.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `kind` | `Literal["human", "llm"]` | yes | |
| `identifier` | `str` | yes | For humans, a user id / handle. For LLMs, the model id at call time (e.g. `claude-opus-4-7`). Pinned per call, recorded in PROV-O. |
| `role` | `Literal["extractor", "auditor", "contrarian", "constructive", "premortem", "human_supervisor"]` | yes | |

Used by: `RoleAttribution.agent`, `ProvenanceRecord.was_attributed_to`,
`Clarification.raised_by`, `Clarification.resolved_by`,
`IterationDirective.issued_by`, `IterationDirective.applied_by`,
`ReplayLogEntry.actor`.

### `RoleAttribution` (`schemas/_shared.py`)

Records a single audit event on a substrate artifact. Distinct from
`AgentAttribution`: a `RoleAttribution` is the **event**
(e.g. "extractor proposed at T"), `AgentAttribution` is the **actor**.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `agent` | `AgentAttribution` | yes | |
| `activity` | `str` | yes | A verb describing what the agent did (e.g. `"proposed"`, `"approved"`). |
| `at` | `AwareDatetime` | yes | Convention is ISO-8601 UTC. Naive datetimes rejected. |

Used by: `Atom.role_attributions`, `Relation.role_attributions`.

### `OperandRef` (`schemas/_shared.py`)

Typed reference to an operand participating in an `Atom`'s predicate.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `role` | `str` | yes | e.g. `"subject"`, `"object"`, `"amount"`, `"cited"`. |
| `kind` | `Literal["entity", "literal", "doc_span"]` | yes | |
| `value` | `str` | yes | Free-form in Phase 1. Phase 2 (Map) normalizes entity references for cross-document join. |
| `type_hint` | `str \| None` | no (default `None`) | Advisory only; no validation in Phase 1. |

### `Atom` (`schemas/atom.py`)

The leaf unit of distillation. A reduced-Toulmin assertion (claim,
data, qualifier, or rebuttal) anchored to a specific span of a source
mirror. Content-addressable.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | Content-addressable hash. `a-<16 hex chars>`. Universally volatile under canonical-form hashing. |
| `source_id` | `str` | yes | INV-7 four-tuple member. |
| `section_path` | `list[str]` | yes | INV-7. e.g. `["Part II", "§3.2", "(a)"]`. |
| `paragraph_index` | `int` | yes | INV-7. 0-indexed within source mirror. |
| `sentence_index` | `int \| None` | no (default `None`) | Optional finer grain. |
| `char_span` | `tuple[int, int]` | yes | INV-7. `(start, end)` within the paragraph. **Validator:** `start < end` (`_char_span_ordered`); raises `ValueError` otherwise. |
| `scale_anchor` | `Literal["sentence", "paragraph", "section", "document"]` | yes | INV-6. No default; missing or `None` is rejected. |
| `kind` | `Literal["claim", "data", "qualifier", "rebuttal"]` | yes | Reduced-Toulmin role. |
| `predicate` | `str` | yes | INV-5. Closed-vocabulary check is M2.4 against the per-distillation vocabulary snapshot, NOT enforced at this layer. |
| `operands` | `list[OperandRef]` | yes | Typed operand references. |
| `narrative` | `str` | yes | Human-readable form of the assertion. Persisted as markdown body; frontmatter carries the structured fields. |
| `qualifier_level` | `Literal["high", "medium", "low", "contested"] \| None` | no (default `None`) | When `kind` allows. |
| `qualifier_basis` | `str \| None` | no (default `None`) | One-line rationale. |
| `provenance_id` | `str` | yes | Volatile under canonical-form hashing; points to `provenance/<prov-id>.yaml`. PROV-O direction is Activity → Entity; the atom's outbound provenance pointer is metadata, not identity content. |
| `role_attributions` | `list[RoleAttribution]` | yes | Audit trail: who proposed, who audited. |
| `schema_version` | `int` | no (default `1`) | |

On-disk: `distillations/<source-id>/atoms/a-<hash>.md` — YAML
frontmatter for structured fields, markdown body for `narrative`.

### `Relation` (`schemas/relation.py`)

Directed warrant-bearing edge between two atoms in the same source.
Intra-document only in Phase 1 ([INV-9](../INVARIANTS.md#inv-9--cross-document-reasoning-is-phase-2s-job-not-phase-1s)).
Content-addressable.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | `r-<16 hex chars>`. |
| `source_id` | `str` | yes | MUST match both atoms' `source_id` (INV-9). The cross-reference check requires a `Substrate` handle and lives in M2.x, NOT at this schema layer. |
| `from_atom_id` | `str` | yes | |
| `to_atom_id` | `str` | yes | |
| `kind` | `Literal["supports", "attacks", "undercuts"]` | yes | |
| `warrant` | `str` | yes | The generalization licensing the edge. |
| `warrant_defensibility` | `Literal["literature-backed", "methodology-derived", "conventional", "contested"]` | yes | When `"contested"`, the Auditor (M7.4) auto-raises a clarification. Not wired at this layer. |
| `warrant_basis` | `str` | yes | One-line rationale or citation. |
| `confidence` | `Literal["high", "medium", "low"]` | yes | |
| `provenance_id` | `str` | yes | Volatile under canonical-form hashing; same rationale as `Atom.provenance_id`. |
| `role_attributions` | `list[RoleAttribution]` | yes | |
| `schema_version` | `int` | no (default `1`) | |

On-disk: `distillations/<source-id>/relations/r-<hash>.yaml` — pure
YAML (no narrative body).

### `ProvenanceRecord` (`schemas/provenance.py`)

W3C PROV-O subset for substrate-artifact lineage. The unit of evidence
that satisfies [INV-3](../INVARIANTS.md#inv-3--provenance-by-construction).
Content-addressable; NO volatile fields beyond the universal `id` drop.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | `p-<16 hex chars>`. |
| `entity_type` | `Literal[...]` | yes | One of nine values: `"atom"`, `"relation"`, `"clarification-raised"`, `"clarification-resolved"`, `"iteration-issued"`, `"iteration-applied"`, `"source-mirror-document"`, `"source-mirror-section"`, `"source-mirror-paragraph"`. The lifecycle pairs (raised/resolved, issued/applied) are first-class so the INV-3 walk can verify both endpoints. |
| `entity_id` | `str` | yes | Points to the subject artifact (e.g. an atom id). NOT used as filename — see [Filesystem layout](#filesystem-layout). |
| `activity` | `str` | yes | e.g. `"extract_v1"`, `"audit_v1"`, `"human_clarify_v1"`. |
| `activity_started_at` | `AwareDatetime` | yes | |
| `activity_ended_at` | `AwareDatetime` | yes | |
| `used_entity_ids` | `list[str]` | yes | What this creation drew on. |
| `was_attributed_to` | `AgentAttribution` | yes | Human or LLM (with model id). |
| `was_influenced_by` | `list[str]` | no (default `[]`) | Higher-order influences (clarification ids, iteration ids). |
| `schema_version` | `int` | no (default `1`) | |

Rationale for empty `_VOLATILE_FIELDS`: a provenance record **is** the
lifecycle event. Every field other than `id` is identity content.

On-disk: `distillations/<source-id>/provenance/<prov-id>.yaml` — keyed
by the provenance record's own id, NOT `entity_id`. See
[Filesystem layout](#filesystem-layout) for the rationale.

### `Clarification` (`schemas/clarification.py`)

An open question raised by a role on substrate artifacts. Lifecycle is
two-phase: `open` → `resolved`. Content-addressable; the lifecycle
transition does NOT change identity (the open and resolved records refer
to the same substrate artifact at two points in its lifecycle).

| Field | Type | Required | Volatile? | Notes |
| --- | --- | --- | --- | --- |
| `id` | `str` | yes | universal | `c-<16 hex chars>`. |
| `status` | `Literal["open", "resolved"]` | yes | yes | |
| `raised_at` | `AwareDatetime` | yes | no | |
| `raised_by` | `AgentAttribution` | yes | no | |
| `raised_by_activity` | `str` | yes | no | |
| `context_refs` | `list[str]` | yes | no | Atom / relation / source-span ids that motivated the question. Existence is NOT validated at this layer. |
| `question` | `str` | yes | no | Markdown body in the on-disk form. |
| `options` | `list[str] \| None` | no (default `None`) | no | Multiple-choice if applicable. |
| `resolved_at` | `AwareDatetime \| None` | no (default `None`) | yes | Populated on transition to `resolved`. |
| `resolved_by` | `AgentAttribution \| None` | no (default `None`) | yes | |
| `resolution` | `str \| None` | no (default `None`) | yes | |
| `raised_provenance_id` | `str` | yes | yes | Points to a `clarification-raised` `ProvenanceRecord`. |
| `resolved_provenance_id` | `str \| None` | no (default `None`) | yes | Points to a `clarification-resolved` `ProvenanceRecord` once resolved. |
| `schema_version` | `int` | no (default `1`) | no | |

The "lifecycle-completion" volatility is the spec's intent: resolving a
clarification MUST NOT change its id, because every existing reference
to the open clarification would break otherwise. The
raised/resolved provenance pair records the transition; the artifact is
the same artifact across the transition.

On-disk: `distillations/<source-id>/clarifications/open/c-<hash>.md` →
`distillations/<source-id>/clarifications/resolved/c-<hash>.md` on
transition (frontmatter + markdown body for `question`).

### `IterationDirective` (`schemas/iteration.py`)

A human instruction to revise a phase's outputs (e.g. "re-extract §3
with stricter qualifier discipline"). Lifecycle is two-phase: `issued`
→ `applied`. Same identity-stability argument as `Clarification`.
Content-addressable.

| Field | Type | Required | Volatile? | Notes |
| --- | --- | --- | --- | --- |
| `id` | `str` | yes | universal | `i-<16 hex chars>`. |
| `issued_at` | `AwareDatetime` | yes | no | |
| `issued_by` | `AgentAttribution` | yes | no | Conventionally human in Phase 1, but not enforced. |
| `target_phase` | `Literal["distill", "map", "extend", "synthesize"]` | yes | no | |
| `target_artifacts` | `list[str]` | yes | no | Atom / relation / finding ids OR path globs (plan §4); plain strings at this layer. |
| `directive` | `str` | yes | no | Markdown body in the on-disk form. |
| `rationale` | `str` | yes | no | |
| `applied_at` | `AwareDatetime \| None` | no (default `None`) | yes | |
| `applied_by` | `AgentAttribution \| None` | no (default `None`) | yes | |
| `applied_outcome` | `str \| None` | no (default `None`) | yes | |
| `issued_provenance_id` | `str` | yes | yes | Points to an `iteration-issued` `ProvenanceRecord`. |
| `applied_provenance_id` | `str \| None` | no (default `None`) | yes | Points to an `iteration-applied` `ProvenanceRecord` once applied. |
| `schema_version` | `int` | no (default `1`) | no | |

On-disk: `iterations/i-<hash>.md` (workspace-level, not under
`distillations/`). Frontmatter + markdown body for `directive`.

### `Entity` (`schemas/entity.py`)

The canonical cross-document entity. Every `OperandRef` of `kind=entity`
across the workspace resolves (via a `Resolution` record) to one `Entity`.
Entities are immutable once written ([INV-13](../INVARIANTS.md#inv-13--entity-and-resolution-records-are-immutable-once-written));
corrections go through `EntitySupersede`. Content-addressable.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | `e-<16 hex chars>`. Content-addressable. |
| `kind` | `str` | yes | MUST be the `id` of an entry in `mappings/entity-vocabulary-snapshot.yaml`. Closed-vocab gate is `entity_kind_in_vocabulary` validator ([INV-12](../INVARIANTS.md#inv-12--mappings-is-the-home-for-all-cross-document-artifacts)). Validator `_non_empty_kind` rejects blank strings. |
| `canonical_name` | `str` | yes | Canonical surface form. Validator `_non_empty_canonical` rejects blank strings. |
| `aliases` | `list[str]` | no (default `[]`) | Surface forms seen across the corpus. |
| `notes` | `str \| None` | no (default `None`) | Supervisor-authored disambiguation text (markdown). |
| `provenance_id` | `str` | yes | Volatile under canonical-form hashing; same rationale as `Atom.provenance_id`. |
| `role_attributions` | `list[RoleAttribution]` | yes | |
| `schema_version` | `int` | no (default `1`) | |

**Volatile fields:** `{"provenance_id"}`.

**Validators:** `_non_empty_canonical` (rejects blank `canonical_name`);
`_non_empty_kind` (rejects blank `kind`).

On-disk: `mappings/entities/e-<hash>.md` — YAML frontmatter for
structured fields; markdown body for `notes` (if any).

Example YAML frontmatter:

```yaml
id: e-3a9b12ff4c6d8e10
kind: organization
canonical_name: Acme Corp
aliases:
  - ACME Corporation
  - Acme Inc
notes: null
provenance_id: p-7f2a9b...
schema_version: 1
```

---

### `Resolution` (`schemas/resolution.py`)

One immutable join: `(source_id, atom_id, operand_index)` → `entity_id`.
The unit of cross-document joinable evidence. Two non-superseded
resolutions for the same triple cannot coexist
([INV-14](../INVARIANTS.md#inv-14--resolution-records-key-off-the-normalized-triple)).
Corrections go through `ResolutionSupersede`. Content-addressable.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | `j-<16 hex chars>`. Prefix `j` = "join". |
| `source_id` | `str` | yes | Identifies the distillation. Must name an existing distillation (INV-12). |
| `atom_id` | `str` | yes | The atom that owns the operand. |
| `operand_index` | `int` | yes | Zero-indexed into the atom's `operands` list. `ge=0`. Validator `resolution_triple_exists` (M2) certifies the index is in range. |
| `entity_id` | `str` | yes | The canonical entity (`e-<hash>`) this operand resolves to. |
| `confidence` | `Literal["high", "medium", "low"]` | yes | |
| `basis` | `str` | yes | One-line rationale (no embedded newlines). Validator `_basis_one_line` rejects multi-line or blank strings. |
| `provenance_id` | `str` | yes | Volatile under canonical-form hashing. |
| `role_attributions` | `list[RoleAttribution]` | yes | |
| `schema_version` | `int` | no (default `1`) | |

**Volatile fields:** `{"provenance_id"}`.

**Validators:** `_basis_one_line` (rejects `\n`/`\r` or blank `basis`).

On-disk: `mappings/resolutions/j-<hash>.yaml` — pure YAML.

---

### `EntitySupersede` (`schemas/entity_supersede.py`)

Records a supervisor correction at the entity level — a merge, split, or
rename of canonical entities. The superseded entity record remains on
disk (immutability); this record is the correction pointer. Content-addressable.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | `t-<16 hex chars>`. Prefix `t` = "tracking". |
| `kind` | `Literal["entity"]` | yes (default `"entity"`) | Discriminator distinguishing entity-level from resolution-level corrections. |
| `superseded_entity_id` | `str` | yes | The entity id (`e-`) being replaced. |
| `replacement_entity_id` | `str` | yes | The surviving canonical entity (`e-`). |
| `reason` | `str` | yes | Non-empty reason for the correction. Validator `_reason_non_empty` rejects blank strings. |
| `provenance_id` | `str` | yes | Volatile under canonical-form hashing. |
| `role_attributions` | `list[RoleAttribution]` | yes | |
| `schema_version` | `int` | no (default `1`) | |

**Volatile fields:** `{"provenance_id"}`.

**Validators:** `_reason_non_empty` (rejects blank `reason`).

On-disk: `mappings/supersedes/t-<hash>.yaml` — pure YAML.

---

### `ResolutionSupersede` (`schemas/resolution_supersede.py`)

Records a supervisor correction at the resolution level. Carries no
semantic content beyond the old → new pointer; the corrected resolution
is a separate new `Resolution` record. Walking the supersede chain yields
the current resolution for a given triple. Content-addressable.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | `s-<16 hex chars>`. Prefix `s` = "supersede". |
| `kind` | `Literal["resolution"]` | yes (default `"resolution"`) | Discriminator; distinguishes from `EntitySupersede`. |
| `superseded_resolution_id` | `str` | yes | The resolution id (`j-`) being replaced. |
| `replacement_resolution_id` | `str` | yes | The new resolution id (`j-`) that takes its place. |
| `reason` | `str` | yes | Non-empty reason. Validator `_reason_non_empty` rejects blank strings. |
| `provenance_id` | `str` | yes | Volatile under canonical-form hashing. |
| `role_attributions` | `list[RoleAttribution]` | yes | |
| `schema_version` | `int` | no (default `1`) | |

**Volatile fields:** `{"provenance_id"}`.

**Validators:** `_reason_non_empty` (rejects blank `reason`).

On-disk: `mappings/supersedes/s-<hash>.yaml` — pure YAML.

---

### `CrossDocRelation` (`schemas/cross_doc_relation.py`)

Directed warrant-bearing edge between two atoms in **different**
distillations, grounded by at least one shared canonical entity. The
cross-document analogue of Phase 1's `Relation`. Phase 2b (Connect)
schema. Content-addressable.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | `x-<16 hex chars>`. Prefix `x` = "cross-doc". |
| `from_atom_id` | `str` | yes | Source endpoint atom. |
| `from_source_id` | `str` | yes | MUST differ from `to_source_id`. Cross-doc-only is a M2 substrate-write gate, not a schema validator. |
| `to_atom_id` | `str` | yes | Sink endpoint atom. |
| `to_source_id` | `str` | yes | MUST differ from `from_source_id`. |
| `kind` | `Literal["supports", "attacks", "undercuts"]` | yes | Same closed set as Phase 1 `Relation`. Wigmore-flavored extensions (`corroborates`, `contradicts`, ...) deferred to Phase 2c. |
| `warrant` | `str` | yes | The generalization licensing the edge — one paragraph. |
| `warrant_defensibility` | `Literal["literature-backed", "methodology-derived", "conventional", "contested"]` | yes | When `"contested"`, the Map-Auditor auto-raises a clarification via the M4 reconciler (`_auto_raise_resolution_clarification`). |
| `warrant_basis` | `str` | yes | One-line rationale / citation. |
| `confidence` | `Literal["high", "medium", "low"]` | yes | |
| `shared_entities` | `list[str]` | yes | One or more canonical-entity ids (`e-`). INV-15: list MUST be non-empty AND every listed entity MUST be resolved by BOTH endpoints. Enforced by `Substrate.add_cross_doc_relation` at write-time and re-checked by the INV-15 invariant gate test at audit-time. The schema layer accepts an empty list; M2 rejects it (raises `SharedEntityGateViolation`). |
| `provenance_id` | `str` | yes | Volatile under canonical-form hashing; same rationale as `Relation.provenance_id`. |
| `role_attributions` | `list[RoleAttribution]` | yes | |
| `schema_version` | `int` | no (default `1`) | |

**Volatile fields:** `{"provenance_id"}`.

**Invariants enforced:**

- **[INV-9](../INVARIANTS.md#inv-9--cross-document-reasoning-is-phase-2s-job-not-phase-1s)**:
  Substrate writes for cross-doc relations are confined to
  `mappings/relations/`; any attempt to write `x-<hash>.yaml` under
  `distillations/<src>/` is rejected by the path resolver.
- **[INV-13](../INVARIANTS.md#inv-13--substrate-records-are-immutable-once-written)**:
  Cross-doc relations are immutable once written; corrections flow through
  `CrossDocRelationSupersede`. The same atomic-write-then-add path that
  protects Phase 2a entities and resolutions protects cross-doc relations.
- **[INV-15](../INVARIANTS.md#inv-15--cross-doc-edges-are-grounded-in-shared-resolved-entities)**:
  `shared_entities` is non-empty AND every listed entity id (a) exists in
  `mappings/entities/` (chain-walked via `latest_entity_for`) and (b) is
  resolved by BOTH endpoint atoms. Enforced at write-time
  (`Substrate.add_cross_doc_relation`) and at audit-time
  (`tests/invariants/test_cross_doc_shared_entity.py`).

On-disk: `mappings/relations/x-<hash>.yaml` — pure YAML.

Example YAML:

```yaml
id: x-3a9b12ff4c6d8e10
from_atom_id: a-aabb112233445566
from_source_id: case-2024-001
to_atom_id: a-ccdd778899aabbcc
to_source_id: case-2024-002
kind: supports
warrant: |
  Both endpoints attest Smith's role as the signing officer of the
  shared parent corporation, evidence from independent filings.
warrant_defensibility: methodology-derived
warrant_basis: "two independent filings + shared canonical entity"
confidence: medium
shared_entities:
  - e-1122334455667788
provenance_id: p-cd1234...
schema_version: 1
```

---

### `CrossDocRelationSupersede` (`schemas/cross_doc_relation_supersede.py`)

Records a supervisor correction at the cross-doc relation level. Carries
no semantic content beyond the old → new pointer; the corrected
`CrossDocRelation` is a separate new record. Walking the supersede chain
yields the current cross-doc relation for the (from, to, shared entity)
context. Content-addressable.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | `v-<16 hex chars>`. Prefix `v` = "vacated" (entity-and-resolution supersedes already claim `t-` and `s-`). |
| `supersedes_id` | `str` | yes | The cross-doc relation id (`x-`) being replaced. |
| `superseded_by_id` | `str` | yes | The new cross-doc relation id (`x-`) that takes its place. |
| `kind` | `Literal["cross-doc-relation"]` | yes (default `"cross-doc-relation"`) | Discriminator; distinguishes from entity / resolution supersedes. |
| `reason` | `str` | yes | Non-empty reason. Validator `_reason_non_empty` rejects blank strings. |
| `provenance_id` | `str` | yes | Volatile under canonical-form hashing. |
| `role_attributions` | `list[RoleAttribution]` | yes | |
| `at` | `AwareDatetime` | yes | Volatile under canonical-form hashing (observational metadata, not identity content). |
| `schema_version` | `int` | no (default `1`) | |

**Volatile fields:** `{"provenance_id", "at"}`. The `at` timestamp is
observational — different supersede events for the same logical
correction (replays, re-runs) carry different wall-clock timestamps and
must therefore not perturb identity.

**Validators:** `_reason_non_empty` (rejects blank `reason`).

**Invariants enforced:**

- **[INV-13](../INVARIANTS.md#inv-13--substrate-records-are-immutable-once-written)**:
  Cross-doc relation corrections do NOT rewrite the superseded record;
  they append a supersede record alongside it. The supersede chain is
  walked at read-time to surface the current relation.

On-disk: `mappings/supersedes/v-<hash>.yaml` — pure YAML.

---

### `ReplayLogEntry` (`schemas/replay_log.py`)

One append-only entry in a workspace's replay log. **NOT
content-addressable**: keyed by `seq` (monotonically increasing per
workspace), cache-identity is `inputs_hash`. The replay log is an append
stream, not a content-addressable store.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `seq` | `int` | yes | Monotonic, gap-free per workspace; assigned by `ReplayLog.append` under the workspace flock (M1.7). |
| `timestamp` | `AwareDatetime` | yes | ISO-8601 UTC convention. |
| `actor` | `AgentAttribution` | yes | |
| `activity` | `str` | yes | e.g. `"extract_v1"`, `"audit_v1"`. |
| `inputs_hash` | `str` | yes | Cache key: hash of `(role, prompt, normalized inputs)`. Computed by the LLM-call wrapper (M5.x). |
| `outputs_hash` | `str` | yes | Hash of the produced output. |
| `cache_hit` | `bool` | yes | `True` iff the activity was satisfied from the prior run's outputs. |
| `substrate_changes` | `list[str]` | yes | Paths written or deleted. |
| `duration_seconds` | `float` | yes | |
| `tokens_input` | `int \| None` | no (default `None`) | Cost telemetry; populated when the harness CLI surfaces it. Carrying these now avoids a schema-version bump when cost analysis lands. |
| `tokens_output` | `int \| None` | no (default `None`) | |
| `cost_estimate_cents` | `float \| None` | no (default `None`) | |
| `schema_version` | `int` | no (default `1`) | |

On-disk:
`distillations/<source-id>/replay-log/<yyyy-mm-dd>/<seq:012d>.yaml`
plus `distillations/<source-id>/replay-log/.next-seq` (monotonic
counter). Day subdirectory is derived from the entry's UTC date.

### `OperandTypeSchema` (`schemas/vocabulary.py`)

Schema describing one operand position a predicate expects. Mirrors the
value-side shape of `OperandRef`; kept in `vocabulary.py` because it is
vocabulary-domain configuration. **NOT content-addressable.**

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Operand position name (e.g. `"payer"`, `"amount"`). |
| `kind` | `Literal["entity", "literal", "doc_span"]` | yes | |
| `required` | `bool` | no (default `True`) | |
| `type_hint` | `str \| None` | no (default `None`) | Advisory. |

### `VocabularyEntry` (`schemas/vocabulary.py`)

One predicate registered in a `Vocabulary`. **NOT
content-addressable.**

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `predicate` | `str` | yes | Canonical predicate identifier (e.g. `"asserts_payment"`). |
| `aliases` | `list[str]` | no (default `[]`) | |
| `operand_types` | `list[OperandTypeSchema]` | yes | |
| `qualifier_required` | `bool` | yes | |
| `notes` | `str` | yes | |

### `Vocabulary` (`schemas/vocabulary.py`)

A named, versioned closed predicate registry. **NOT
content-addressable.** Versioned by `(name, version)`; snapshotted
per-distillation per [INV-10](../INVARIANTS.md#inv-10--vocabulary-is-pinned-per-distillation).

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | e.g. `"generic"`, `"forensic-crypto-v1"`. |
| `version` | `str` | yes | Semver. |
| `entries` | `list[VocabularyEntry]` | yes | |

On-disk (per distillation):
`distillations/<source-id>/vocabulary-snapshot.yaml`. Validators read
this file, never the global `~/.amanuensis/vocabularies/` registry.

---

## Filesystem layout

Authoritative layout for the Phase 1 substrate. The path resolvers in
`amanuensis.fs.Substrate` are the single source of truth in code; this
section mirrors them. (Plan source: §5.)

```text
<workspace>/
  amanuensis.yaml                            project marker (INV-1)

  distillations/<source-id>/
    README.md                                auto-generated index
    source-mirror/
      manifest.yaml                          source file hash + ingest activity
      paragraphs/p-<NNNN>.md                 one per paragraph (frontmatter + body)
      sections/                              section hierarchy index
    vocabulary-snapshot.yaml                 per-distillation snapshot (INV-10)
    atoms/a-<hash>.md                        frontmatter + narrative body
    relations/r-<hash>.yaml                  pure YAML
    provenance/<prov-id>.yaml                pure YAML; keyed by prov-id (see below)
    clarifications/
      open/c-<hash>.md                       frontmatter + question
      resolved/c-<hash>.md                   same id; resolution fields populated
    replay-log/
      .next-seq                              monotonic counter (flock-serialized)
      <yyyy-mm-dd>/<seq:012d>.yaml           one per activity

  iterations/i-<hash>.md                     workspace-level supervisor directives

  delivery/sign-off.yaml                     Phase 4 gate (stub in Phase 1)

  dispatch/
    queue/<role>-<seq>.yaml                  orchestrator → driver
    outputs/<role>-<seq>.yaml                driver → orchestrator
    failures/<role>-<seq>.yaml               retry exhaustion

  cache/<input-hash>.yaml                    content-addressable LLM-call cache

  mappings/                                  Phase 2a + 2b cross-document layer (INV-12)
    entity-vocabulary-snapshot.yaml          active entity-kind registry (INV-12)
    entities/e-<hash>.md                     canonical Entity records (frontmatter + notes)
    resolutions/j-<hash>.yaml                Resolution records (pure YAML)
    relations/x-<hash>.yaml                  Phase 2b CrossDocRelation records (pure YAML; INV-15)
    supersedes/t-<hash>.yaml                 EntitySupersede records
    supersedes/s-<hash>.yaml                 ResolutionSupersede records
    supersedes/v-<hash>.yaml                 Phase 2b CrossDocRelationSupersede records
    provenance/<prov-id>.yaml                PROV-O records for mapping-phase artifacts
    replay-log/                              mappings-scoped replay log
```

### Path conventions

- **All identity-bearing ids are content-addressable** (per the
  [Content-addressable IDs](#content-addressable-ids) section). Same
  content → same path.
- **`.md` for files with human-readable bodies**, `.yaml` for pure-record
  files. Frontmatter uses standard `---` delimiters; the body is
  free-form but conventionally structured.
- **Every subdirectory under `distillations/<source-id>/`** has a
  `README.md`. **The workspace root does NOT have a `README.md`** —
  that would violate [INV-2](../INVARIANTS.md#inv-2--no-harness-specific-files-at-project-root).
- **Append-only.** `atoms/`, `relations/`, `provenance/`, and the
  replay log are append-only. Clarifications "move" from `open/` to
  `resolved/` by writing a new file at the resolved path; the id is
  preserved (volatility rules ensure this).
- **Id-component validation.** Source ids and other path components must
  match `^[A-Za-z0-9_.-]+$`. This rejects path separators, parent
  traversal (`.`, `..`), embedded NUL, whitespace, and anything else
  that could compromise path discipline.

### Provenance filename: `prov-id`, not `entity-id`

Plan §5 named provenance files by `entity-id`. M1.6 changed the naming
to the provenance record's own id, `prov-id`, because a
`Clarification`'s raised + resolved provenance pair share an
`entity_id` (the clarification's id) and would collide on the same
filename. Inverse lookup ("what provenance records point at this
entity?") is via the `entity_id` field on each record. The decision is
recorded in `substrate.py`'s module docstring and in HISTORY.md
(M1.6 entry).

### Replay-log layout

- `.next-seq` is the monotonic counter. Its increment is serialized by
  the workspace flock (M1.7 + M1.8).
- `<yyyy-mm-dd>/` is for human navigation only. `seq` is unique across
  the entire log, not per-day.
- Filenames are zero-padded width-12 (`000000000042.yaml`), so
  lexicographic file sort within a day directory equals numeric seq
  order.
- Crash discipline: the entry file is written via `atomic_write_text`
  BEFORE the counter is bumped. A crash leaves the counter at N and the
  next writer overwrites the orphan at seq N — gap-free and
  duplicate-free on retry. Cross-day orphan scan inside the held flock
  handles the rare midnight-UTC edge case.

---

## Invariants enforcement

Per-invariant enforcement points at or near the schema layer. The
canonical charter is in [`../INVARIANTS.md`](../INVARIANTS.md). The
schema layer enforces structural shape; full semantic enforcement (the
content of `Substrate` cross-reference checks, the Auditor, the
vocabulary closure check) lands in later milestones (M2–M5). The
"Enforced at" column names the precise mechanism per invariant; the
"Gate test (planned)" column gives the eventual integration test.

| Invariant | Schema-layer enforcement | Gate test (planned) |
| --- | --- | --- |
| [INV-3](../INVARIANTS.md#inv-3--provenance-by-construction) (provenance by construction) | Every content-addressable type carries a `provenance_id` (Atom, Relation) or a paired `*_provenance_id` field (Clarification raised/resolved, IterationDirective issued/applied). The pointers are required-on-create (raised/issued) and required-on-completion (resolved/applied) for the lifecycle types. `ProvenanceRecord` itself is the entity; its `entity_type` covers all nine substrate-entity classes including the four lifecycle pairs and the three `source-mirror-*` variants. | M2.5 `test_provenance_completeness.py` walks the substrate; fails if any artifact lacks a PROV-O record. |
| [INV-4](../INVARIANTS.md#inv-4--determinism-boundary-is-named-gated-and-audited) (determinism boundary) | `compute_id` is deterministic (no salt, no randomness; SHA-256 over canonical form). Pydantic `strict=True` + `extra="forbid"` rejects unstructured input. `AwareDatetime` rejects naive datetimes (removes a non-determinism source). The LLM-call wrapper (M5.x) writes a `ReplayLogEntry` + `ProvenanceRecord` per call; cached calls replay byte-identically. | M5.3 + M4.4 `test_determinism_boundary.py` verifies the mutating boundary vs read-only purity; verifies every LLM call goes through cache+log. |
| [INV-5](../INVARIANTS.md#inv-5--closed-predicate-vocabulary-at-extraction) (closed predicate vocabulary) | `Atom.predicate` is `str` at the schema layer. The closure check is M2.4 against the per-distillation `Vocabulary` snapshot (the `OperandTypeSchema`+`VocabularyEntry`+`Vocabulary` types are the registry shape). | M2.5 `test_closed_vocabulary.py` rejects atoms whose predicate is not in the per-distillation snapshot. |
| [INV-6](../INVARIANTS.md#inv-6--scale_anchor-is-mandatory-on-every-atom) (`scale_anchor` mandatory) | `Atom.scale_anchor` is required, typed `Literal["sentence", "paragraph", "section", "document"]`. No default; Pydantic rejects missing or `None`. | M2.4 `test_scale_anchor_required.py`. (Schema layer already enforces; the gate test is end-to-end.) |
| [INV-7](../INVARIANTS.md#inv-7--source_id-section_path-paragraph_index-char_span-mandatory) (citation 4-tuple mandatory) | `Atom.source_id`, `Atom.section_path`, `Atom.paragraph_index`, `Atom.char_span` are all REQUIRED with no defaults. `char_span` ordering is validated by `_char_span_ordered` (`start < end`, raises `ValueError`). | M2.4 `test_citation_ledger.py`. |
| [INV-10](../INVARIANTS.md#inv-10--vocabulary-is-pinned-per-distillation) (vocabulary pinned per distillation) | `Vocabulary` is config-shaped, not coupled to a global registry. The per-distillation snapshot file (`distillations/<source-id>/vocabulary-snapshot.yaml`) is written on ingest (M2.3) and content-addressed; the snapshot hash is recorded in `source-mirror/manifest.yaml`. Validators read the snapshot, never `~/.amanuensis/vocabularies/`. | M2.5 `test_vocabulary_pinned.py` verifies every distillation has a snapshot; verifies the snapshot hash matches the manifest; verifies validator code paths reach the snapshot, not the global registry. |

INV-1, INV-2, INV-8 are filesystem / harness invariants, not schema
invariants, and are enforced elsewhere:

- **INV-1** (marker required) — `amanuensis.fs.Substrate.__init__`
  rejects construction if `<workspace>/amanuensis.yaml` is missing.
  `acquire_workspace_lock` enforces the same as defense-in-depth.
- **INV-2** (no harness-specific files at project root) — pre-commit
  shape-check hook plus the planned `test_no_harness_files.py`.
- **INV-8** (substrate is the source of truth) — atomic writes in
  `_atomic.py`, content-addressable-path checks in `Substrate.add_*`,
  the M9.x render-purity test.

INV-9 (Phase 1 emits intra-document relations only) is a per-pipeline
property enforced by the validators (M2.x) and the M2.5 gate test, not
the schema layer.

---

## Content-addressable IDs

Every content-addressable artifact has

    id = "<kind-letter>-<16 hex chars>"

where the 16 hex chars are the first 8 bytes of the SHA-256 of the
artifact's **canonical form**. The hasher is the public function
`amanuensis.schemas.compute_id`.

### Canonical-form algorithm (plan §4)

Given a Pydantic model instance:

1. **Dump the model** via `model_dump(mode="python")`. This produces a
   `dict[str, Any]` with native Python `datetime`, `tuple`, `float`,
   etc. preserved.
2. **Drop volatile fields** at the top level:
   - `id` (universally; chicken-and-egg).
   - Every name in the model class's
     `_VOLATILE_FIELDS: ClassVar[frozenset[str]]`.
3. **Recursively sort all mapping keys** lexicographically. Lists keep
   their order (lists are semantically ordered in JSON).
4. **Encode datetimes** as ISO-8601 UTC with microsecond precision and
   a `Z` suffix (e.g. `2026-05-29T12:00:00.000000Z`). Naive (tz-less)
   datetimes are rejected; the schema layer's `AwareDatetime` already
   prevents them but the hasher's check is explicit.
5. **Encode floats** with Python's `repr()` (shortest round-trip
   decimal). The float becomes a JSON string, not a JSON number, in
   the canonical encoding — this is deliberate: hashing is a
   closed-loop (we hash; we never round-trip back to a model from
   canonical form), and `repr()` is the only stdlib float formatter
   that guarantees a lossless decimal representation. `NaN` and `Inf`
   are rejected; canonical JSON does not represent them.
6. **Encode tuples as lists** (JSON has no tuple type).
7. **Serialize as canonical JSON**: `sort_keys=True`,
   `ensure_ascii=True` (so non-ASCII characters become `\uXXXX`
   escapes), `separators=(",", ":")` (no whitespace),
   `allow_nan=False`. UTF-8 bytes.
8. **Hash** with SHA-256; take the first 16 hex chars (8 bytes);
   prefix with the kind letter.

### Per-type volatile fields

| Type | `_VOLATILE_FIELDS` (in addition to `id`) | Rationale |
| --- | --- | --- |
| `Atom` | `{"provenance_id"}` | PROV-O direction is Activity → Entity; the atom's outbound provenance pointer is observational metadata, not identity content. |
| `Relation` | `{"provenance_id"}` | Same rationale as Atom. |
| `ProvenanceRecord` | `set()` | A provenance record **is** the lifecycle event. Every field other than `id` is identity content. |
| `Clarification` | `{"status", "resolved_at", "resolved_by", "resolution", "raised_provenance_id", "resolved_provenance_id"}` | The clarification's identity is its question and raise context. The `open` → `resolved` transition is recorded via the paired provenance pair (raised + resolved); the artifact itself is the same artifact across the transition. The provenance pointers are PROV-O Entity → Activity, same volatility argument as Atom. |
| `IterationDirective` | `{"applied_at", "applied_by", "applied_outcome", "issued_provenance_id", "applied_provenance_id"}` | The directive's identity is its instruction and issue context. The `issued` → `applied` transition is recorded via the paired provenance pair (issued + applied); same argument as Clarification. |
| `Entity` | `{"provenance_id"}` | Same rationale as Atom. Entity identity is its kind + canonical_name + aliases; the provenance pointer is observational. |
| `Resolution` | `{"provenance_id"}` | Resolution identity is the triple + entity target + confidence + basis. Same PROV-O direction argument as Atom. |
| `EntitySupersede` | `{"provenance_id"}` | Supersede identity is the old → new pointer + reason. Same argument as Atom. |
| `ResolutionSupersede` | `{"provenance_id"}` | Same rationale. |
| `CrossDocRelation` | `{"provenance_id"}` | Cross-doc relation identity is the (from, to, kind, warrant) tuple plus `shared_entities`. Provenance pointer is observational. |
| `CrossDocRelationSupersede` | `{"provenance_id", "at"}` | Supersede identity is the old → new pointer + reason. The wall-clock `at` is volatile because replays of the same logical correction carry different timestamps. |

The "lifecycle-completion" volatility on `Clarification` and
`IterationDirective` is the spec's intent: resolving a clarification
or applying an iteration MUST NOT change the artifact's id, because
the open-state record and the resolved-state record refer to the same
substrate artifact (just at two points in its lifecycle). Without
volatility, resolving the clarification would mint a new id, breaking
every existing reference to the open clarification.

### Worked example

Given the fixture-style `Atom`:

```python
Atom(
    id="a-stub",                       # universal volatile; ignored
    source_id="src-fixture-001",
    section_path=["Part II", "§3.2", "(a)"],
    paragraph_index=0,
    sentence_index=None,
    char_span=(0, 42),
    scale_anchor="paragraph",
    kind="claim",
    predicate="asserts_obligation",
    operands=[
        OperandRef(role="subject", kind="entity",
                   value="ent-acme-corp", type_hint=None),
    ],
    narrative="ACME shall pay the invoiced amount within 30 days.",
    qualifier_level=None,
    qualifier_basis=None,
    provenance_id="prov-fixture-0001", # per-class volatile; ignored
    role_attributions=[RoleAttribution(...)],
    schema_version=1,
)
```

the canonical JSON (after dropping `id` and `provenance_id`, sorting,
encoding the datetime, escaping the `§`) is:

```json
{"char_span":[0,42],"kind":"claim","narrative":"ACME shall pay the invoiced amount within 30 days.","operands":[{"kind":"entity","role":"subject","type_hint":null,"value":"ent-acme-corp"}],"paragraph_index":0,"predicate":"asserts_obligation","qualifier_basis":null,"qualifier_level":null,"role_attributions":[{"activity":"proposed","agent":{"identifier":"claude-opus-4-7","kind":"llm","role":"extractor"},"at":"2026-05-29T12:00:00.000000Z"}],"scale_anchor":"paragraph","schema_version":1,"section_path":["Part II","\u00a73.2","(a)"],"sentence_index":null,"source_id":"src-fixture-001"}
```

`SHA-256` of those bytes is

    64794b73bc8a6bff7f032665cdfb5b55e28bca3ddc180a52af253f8f60d0bc97

The truncated, prefixed id is

    a-64794b73bc8a6bff

### Collision discipline

8-byte truncation gives roughly `2^32` records before the
birthday-collision probability approaches 50%. This is comfortably
above any realistic single-engagement corpus (a heavy matter is
tens of thousands of atoms, not billions). Tests sweep fixture
corpora and assert zero collisions. Production discovery of a
collision is a governance event: lengthen the truncation,
re-canonicalize, version the id scheme.

### Determinism guarantees

- `compute_id(model) == compute_id(model)` on every call. No salt, no
  randomness. (INV-4: determinism boundary; the hasher is on the
  deterministic side.)
- Equivalent content (the same payload modulo dict key ordering)
  produces the same id. Property-tested over 500 generated Atoms
  with `hypothesis`.
- Changing any non-volatile field changes the id. Spot-checked across
  all five content-addressable types.
- Changing a volatile field does NOT change the id. Spot-checked
  across all five types.

---

## Non-content-addressable types

`ReplayLogEntry` does not have an `id` field. It is keyed by `seq`
(monotonically increasing per workspace) and its cache identity is
the `inputs_hash` field, computed by the LLM-call wrapper (M5.x).
The replay log is an append stream, not a content-addressable store.

`Vocabulary`, `VocabularyEntry`, `OperandTypeSchema` are configuration
artifacts (the closed predicate registry). They are versioned by name
+ semver, snapshotted per-distillation (INV-10), and have no
content-addressable id. `compute_id()` rejects all four with a
`ValueError`.

---

## Where this lives in code

- `src/amanuensis/schemas/_hashing.py` — `compute_id`, `_to_canonical`,
  `_canonical_json`. Authoritative spec is the module docstring.
- `src/amanuensis/schemas/__init__.py` — public re-exports
  (`compute_id` plus the twelve model types).
- `src/amanuensis/fs/substrate.py` — path resolvers, `add_*` and
  `get_*` methods, INV-1 + content-addressable-path enforcement.
- `src/amanuensis/fs/replay_log.py` — `ReplayLog` append-only writer,
  seq counter, crash discipline.
- `src/amanuensis/fs/lock.py` — `acquire_workspace_lock` context
  manager.
- `tests/schemas/test_content_addressing.py` — determinism /
  equivalence / volatility / collision-sweep / rejection tests, plus
  the 500-example `hypothesis` property test.
- `tests/schemas/test_atom.py`, `test_relation.py`,
  `test_provenance.py`, `test_clarification.py`,
  `test_iteration.py`, `test_replay_log.py`, `test_vocabulary.py` —
  per-model validation tests.
- `tests/fs/` — substrate path / atomic-write / replay-log / lock
  tests.

---

## Known Limitations

- **No automated schema-version migration.** Every Pydantic model
  carries a `schema_version: int` field (default `1`); changing the
  on-disk shape of a record bumps that integer, but there is no
  registered migration runner that walks a workspace and rewrites
  records. A migration tool is a Phase 2 candidate.
- **`Atom.section_path` and `Atom.operands[].value` are free-form
  strings.** Phase 1 does not normalize entity references across
  documents; Phase 2 (Map) introduces the entity-resolution layer that
  populates a canonical entity registry from these strings. See
  [INV-9](../INVARIANTS.md#inv-9--cross-document-reasoning-is-phase-2s-job-not-phase-1s).
- **8-byte truncation of SHA-256 content-addressable ids.** Roughly
  `2^32` records before the birthday-collision probability approaches
  50% — comfortably above realistic single-engagement corpora. Sweeping
  fixture corpora certifies zero collisions; a production collision is
  a governance event (lengthen truncation, re-canonicalize, version the
  id scheme).
- **No retrofit path for legacy / partial provenance.** INV-3
  (provenance by construction) makes retrofitted PROV records
  un-mintable: every substrate-creating event must produce the PROV
  record at the moment of creation. Importing pre-existing artifacts
  with synthetic provenance is intentionally out of scope.
- **Vocabulary registry edits between distillations do not retroactively
  propagate.** INV-10 pins the per-distillation snapshot; this is the
  intent. Migrating an existing distillation to a newer vocabulary
  requires re-ingest (Phase 2 may add a re-snapshot tool).

---

## See also

- [`architecture.md`](./architecture.md) — system-level architecture
  (substrate-as-truth, three surfaces, determinism boundary,
  harness-aware module, module decomposition).
- [`../INVARIANTS.md`](../INVARIANTS.md) — invariants charter (INV-1
  through INV-10).
- `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29.md` —
  authoritative Phase 1 plan; §4 is the schema spec, §5 is the layout,
  §11 is the invariant gate-test catalogue.
