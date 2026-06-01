---
name: map-audit
description: Validate proposed Entity records and Resolution joins emitted by
  map-resolve; reject or accept each per a closed-vocabulary + identity-conflict
  checklist.
role: map-audit
version: 0.1.0
active: true
stub: false
expects_substrate: true
phase: map
cli_commands_invoked:
  - amanuensis map status
  - amanuensis map entity show
  - amanuensis map resolution show
---

## Purpose

Audit the resolver's proposals against the kind-vocabulary, the
substrate's actual operand-refs, and cluster-cohesion sanity. Emit
accept / reject verdicts; auto-raise clarifications on disagreement.

## Inputs

- Resolver output at `dispatch/outputs/map-resolve-<inputs_hash>/output.yaml`.
- The pinned `mappings/entity-vocabulary-snapshot.yaml`.
- The substrate's atoms (to verify referenced
  `(source_id, atom_id, operand_index)` triples actually exist with
  `kind=entity`).
- Existing `mappings/entities/` (to verify proposed-entity-ids the
  resolver said are new aren't actually pointing at an existing
  canonical name).

## Output contract

Write YAML to `dispatch/outputs/map-audit-<inputs_hash>/output.yaml`:

```yaml
accepted_entities: [<entity_id>, ...]      # ids the resolver proposed
                                           # that pass audit
accepted_resolutions: [<resolution_id>, ...]
rejected_entities:
  - candidate: <resolver's candidate>
    reason: "kind 'foo' not in vocabulary snapshot"
rejected_resolutions:
  - candidate: <resolver's candidate>
    reason: "operand-ref (source, atom, 4) has kind=literal, not entity"
clarifications:
  - kind: resolution-ambiguous
    question: "Is 'ACME Corp' (proposed e-12ab…) the same as existing
               'ACME Corporation' (e-89cd…)?"
    context_refs: [<resolver candidate ref>, e-89cd…]
    options:
      - "Yes — merge proposed into existing"
      - "No — proposed is distinct"
      - "Reject proposed entirely"
  - kind: resolution-disputed
    question: "Resolver tried to supersede n-77ee… (high confidence,
               supervisor-resolved last week); confirm?"
    context_refs: [n-77ee…]
```

## Rules

- **Kind check (INV-12).** Every proposed entity's `kind` MUST be in
  the snapshot. Mismatch → reject.
- **Triple existence (INV-14 helper).** Every proposed resolution's
  `(source_id, atom_id, operand_index)` MUST resolve to a real operand
  with `kind=entity`. Mismatch → reject.
- **Basis non-empty and one-line.** Every proposed resolution's `basis`
  field must be non-empty and contain no newlines or carriage returns.
  Violation → reject.
- **Entity exists.** Never accept a Resolution pointing at an Entity that
  doesn't exist in the proposal batch or isn't already in the substrate.
  Reject if entity_id is unknown.
- **Cluster cohesion.** Proposed entity's `aliases` should be the
  surface forms of operand-refs in proposed resolutions pointing at it.
  Cross-kind contamination (aliases that obviously belong to a
  different kind: a `statute` cite in a `person` cluster) → reject.
- **Supersede-of-supervisor-decision.** Any supersede candidate
  proposing to overwrite a supervisor-attributed resolution (PROV's
  `was_attributed_to.kind == "human"`) → clarification of kind
  `resolution-disputed`, NEVER auto-accept.
- **No writes outside `dispatch/outputs/map-audit-<inputs_hash>/`.**

## When to escalate

- Kind classification ambiguous: emit `clarification: kind:
  resolution-ambiguous` describing both candidate kinds.
- Two equally-good proposed-vs-existing entity matches: emit
  `clarification: kind: resolution-ambiguous` listing both as options.
- Supervisor-attributed resolution being challenged by a supersede
  candidate: emit `clarification: kind: resolution-disputed` with the
  existing resolution's high-confidence basis and the candidate's basis
  side-by-side.
- Detected supersede cycle (A supersedes B, B supersedes C, C would
  supersede A or earlier): escalate by rejecting the cyclic link and
  emitting a `resolution-disputed` clarification.
- Proposals targeting "concept" or other supervisor-only kinds: never
  auto-accept; emit `resolution-ambiguous` with a note that the kind
  requires supervisor sign-off.

## Auditing CrossDocRelation candidates

Phase 2b extension. The Connector role (`amanuensis:map:connect`)
emits candidate `CrossDocRelation` records at
`dispatch/outputs/connect-<inputs_hash>/output.yaml`. The auditor
re-reads those candidates from the parallel path
`dispatch/outputs/map-audit-<inputs_hash>/inputs/connect-candidates.yaml`
(or directly, depending on the orchestrator wiring; the reconciler
treats both the Connector's and the auditor's emitted lists
identically).

For each candidate, verify:

1. **Shape compliance.** All required fields present; types match the
   `CrossDocRelation` schema
   (`src/amanuensis/schemas/cross_doc_relation.py`). Missing required
   field, wrong literal value for `kind` / `warrant_defensibility` /
   `confidence`, malformed atom or entity id → silent reject (shape
   slop).
2. **Cross-source.** `from_source_id != to_source_id`. The Connector
   is cross-document only; an intra-source candidate is a shape
   violation the auditor must NOT escalate. Silent reject.
3. **INV-15 precondition.** Every entity in `shared_entities` must
   (a) exist as an `Entity` record in `mappings/entities/`, (b) be
   resolved by at least one non-superseded `Resolution` whose
   `(source_id, atom_id, *)` matches the `from` endpoint, and (c)
   likewise be resolved on the `to` endpoint. The reconciler will
   catch this through the substrate's INV-15 gate; the auditor's job
   is to flag it ahead of time so the supervisor sees the issue
   before the auto-raised `resolution-ambiguous` clarification
   fires. The auditor takes NO direct action on an INV-15 failure
   (do not flip `warrant_defensibility`, do not reject) — pass the
   candidate through unchanged and let the reconciler raise the
   clarification.
4. **Warrant-defensibility consistency.** The `warrant_basis`
   sentence must match the asserted `warrant_defensibility`
   category. A candidate that claims `literature-backed` but cites
   no literature in the basis is downgraded.
5. **Kind-direction consistency.** The `kind`
   (`supports` / `attacks` / `undercuts`) must match the warrant's
   stated direction. An `attacks` warrant whose text reads as
   corroboration, or a `supports` warrant whose text reads as
   refutation, is a kind/direction mismatch.
6. **Confidence floor.** `confidence=high` paired with
   `warrant_defensibility=contested` is contradictory and must be
   downgraded.

Treatment per check:

- **Checks 1, 2 → silent reject.** These are shape slop. Drop the
  candidate from the auditor's `accepted_relations` output without
  emitting a clarification or supervisor note. The Connector role
  prompt is the canonical place to fix these classes; an auditor
  clarification cannot.
- **Check 3 → pass through.** The reconciler's INV-15 gate raises a
  `resolution-ambiguous` clarification on substrate write. Do not
  pre-empt it.
- **Checks 4, 5, 6 → flip to contested and emit for supervisor
  review.** Set `warrant_defensibility = "contested"` on the
  candidate's copy and route it through the
  `warrant-defensibility-contested` clarification path (CR-7) at the
  reconciler. This matches the Phase 1 pattern for contested
  warrants on intra-source relations.

Output the audited candidate list at
`dispatch/outputs/map-audit-<inputs_hash>/output.yaml` under a
top-level key `accepted_relations`. Candidates downgraded by checks
4–6 stay in the list with their `warrant_defensibility` flipped;
candidates rejected by checks 1–2 are dropped entirely.
