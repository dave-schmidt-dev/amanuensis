---
name: distill_constructive
description: Constructive role (STUB, Phase 2) — proposes alternative atomizations a senior reviewer might recommend.
role: constructive
version: 0.1.0
active: false
stub: true
stub_reason: "Phase 1 ships Extractor + Auditor only; Constructive (proposes alternative atomizations a senior reviewer might recommend) is Phase 2."
expects_substrate: true
phase: distill
cli_commands_invoked: []
---

The Constructive's job in Phase 2 will be to act as a senior reviewer
looking over the Extractor's shoulder: take the Extractor's output and
propose alternative atomizations the Extractor could have made but
didn't. Where the Extractor split a long sentence into three atoms,
the Constructive might propose one atom at paragraph scale that
captures the same content with less brittleness; where the Extractor
collapsed two distinct claims, the Constructive might propose
splitting them. The Constructive is generative, not adversarial — it
expands the option set the supervisor can choose from.

The Constructive would consume the Extractor's atoms output, the
source-mirror manifest, the pinned vocabulary snapshot, and the
project's atomization-style guide (Phase 2 addition; codifies house
preferences on scale, predicate granularity, and entity-vs-attribute
splits).

The planned output contract is a list of `proposals:
[{against_atom_ids, proposed_atoms, rationale}]`. Each proposal names
the Extractor atoms it would supersede and supplies replacement atoms
in the same `Atom` schema. The reconciliation gate surfaces proposals
to the supervisor as side-by-side diffs; nothing merges automatically.

The Phase 2 implementation gate for activating Constructive: the
atomization-style guide must exist as a substrate-loadable artifact,
and the reconciliation gate must support side-by-side diff
presentation — without those, Constructive output is just noise.
