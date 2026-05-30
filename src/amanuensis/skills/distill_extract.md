---
name: distill_extract
description: Extractor role — extract atoms from a source-mirror's paragraphs.
role: extractor
version: 0.1.0
active: true
stub: false
expects_substrate: true
phase: distill
cli_commands_invoked:
  - amanuensis atom validate
---

## Purpose

Read a single source-mirror and emit atoms covering every claim,
entity reference, and relation worth distilling. One Extractor pass
runs per source per distillation; the dispatch driver writes the
output to `dispatch/outputs/extractor-<inputs_hash>/output.yaml` for
the Auditor and the reconciliation gate to consume.

## Inputs

- The `--source-id` being distilled.
- The source-mirror paragraph entries enumerated in
  `source-mirror/<source-id>/manifest.yaml` (each entry resolves to a
  paragraph `.md` file with a `content_sha256`).
- The pinned vocabulary snapshot at
  `distillations/<source-id>/vocabulary-snapshot.yaml` (per INV-10);
  never read the global `~/.amanuensis/vocabularies/` registry at
  extraction time.

## Output contract

Emit structured YAML on stdout matching the `Atom` schema. The top
level is a list; one atom per list item. The dispatch driver routes
the captured stdout to
`dispatch/outputs/extractor-<inputs_hash>/output.yaml` atomically.

Example shape (abbreviated):

```yaml
- id: atom-0001
  source_id: <source-id>
  section_path: "/§3.2"
  paragraph_index: 14
  char_span: [102, 247]
  scale_anchor: sentence
  predicate: <vocabulary predicate>
  subject: ...
  object: ...
  scale_anchor_rationale: ...
```

## Atom requirements

Every atom MUST satisfy these (validators reject otherwise):

- **INV-7 citation four-tuple.** `source_id`, `section_path`,
  `paragraph_index`, and `char_span` are mandatory and must resolve to
  a real span in the source-mirror.
- **INV-6 scale_anchor.** Must be exactly one of
  `{sentence, paragraph, section, document}`.
- **INV-5 closed vocabulary.** `predicate` MUST be a name (or alias)
  present in the pinned vocabulary snapshot for this distillation.
  Open-vocabulary or invented predicates are rejected by the Auditor.

PROV records are written by the dispatch driver from the dispatch
entry's metadata; the Extractor does not emit PROV records itself
(INV-3 provenance-by-construction is enforced at the boundary, not by
the agent).

## Validators run after extraction

After the dispatch driver lands `output.yaml`, the supervisor (or the
M7.4 gate) runs `amanuensis atom validate` which executes all seven
canonical validators against each emitted atom:

- `schema_check` — payload conforms to the `Atom` model.
- `citation_ledger` — four-tuple is well-formed (INV-7).
- `universe_check` — `source_id` refers to a known source-mirror.
- `scale_anchor` — value is in the INV-6 closed set.
- `closed_vocabulary` — `predicate` is in the pinned snapshot
  (INV-5/INV-10).
- `provenance_completeness` — provenance pointer resolves (INV-3).
- `lineage_closure` — for any emitted Relation, both endpoint atoms
  exist on the substrate.

Atoms that fail validation are not merged into the substrate; the
Auditor sees them and may rewrite, narrow, or reject.
