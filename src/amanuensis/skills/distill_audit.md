---
name: distill_audit
description: Auditor role — audit Extractor atoms against the source-mirror and raise contested-warrant clarifications.
role: auditor
version: 0.1.0
active: true
stub: false
expects_substrate: true
phase: distill
cli_commands_invoked:
  - amanuensis atom validate
---

## Purpose

Audit the Extractor's atoms against the source-mirror: verify each
atom's span actually supports the predicate-subject-object claim,
verify the four-tuple resolves, verify the predicate is in the pinned
vocabulary, and surface any atom whose warrant from source span to
claim is contested. The Auditor's output drives the M7.4
reconciliation gate — accepted atoms merge to the substrate, rejected
atoms do not, and clarifications block merge until a supervisor
resolves them.

## Inputs

- The Extractor's output at
  `dispatch/outputs/extractor-<inputs_hash>/output.yaml`.
- The source-mirror manifest at
  `source-mirror/<source-id>/manifest.yaml` (and the paragraph `.md`
  files it references).
- The pinned vocabulary snapshot at
  `distillations/<source-id>/vocabulary-snapshot.yaml` (INV-10).

## Output contract

Emit structured YAML on stdout. The dispatch driver routes it to
`dispatch/outputs/auditor-<inputs_hash>/output.yaml`. Required shape:

```yaml
accepted_atom_ids:
  - atom-0001
  - atom-0003
rejected_atoms:
  - atom_id: atom-0002
    reason: "char_span 102-247 does not contain a sentence supporting predicate `caused`"
    warrant_defensibility: contested   # optional; set when the warrant is ambiguous
clarifications:
  - question: "Should atom-0004 be narrowed to §3.2 only, or also cover §3.3?"
    raised_against_atom_id: atom-0004
    options:
      - "Narrow to §3.2 only"
      - "Keep both sections"
      - "Reject atom-0004"
```

For any rejection whose `warrant_defensibility` is `contested`, the
M7.4 reconciliation gate auto-raises a
`warrant-defensibility-contested` clarification (per CR-7) so the
supervisor sees the conflict explicitly even when the Auditor itself
didn't enumerate options.

## What "contested warrant" means

The warrant is the inferential step from a source span to the atom's
claim. A warrant is "contested" when a reasonable reader could draw a
materially different inference from the same span — e.g., the source
says "X correlated with Y" and the atom asserts predicate `caused`.
That's not a span error (the citation four-tuple may be perfect); it's
an inference error. The reconciliation gate raises a supervisor-facing
clarification asking them to either reaffirm the warrant (with
rationale recorded in PROV), narrow the atom (replace `caused` with
`correlated_with`, for instance), or reject the atom outright.
