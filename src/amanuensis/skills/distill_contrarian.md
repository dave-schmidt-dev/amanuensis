---
name: distill_contrarian
description: Contrarian role (STUB, Phase 2) — steelmans the opposing framing of the Extractor's atoms.
role: contrarian
version: 0.1.0
active: false
stub: true
stub_reason: "Phase 1 ships Extractor + Auditor only; Contrarian (challenges the Extractor's framing from a steelman-the-opposing-side angle) is Phase 2."
expects_substrate: true
phase: distill
cli_commands_invoked: []
---

The Contrarian's job in Phase 2 will be to challenge the Extractor's
framing: take the same source and the same atoms, and steelman the
opposing reading. Where the Extractor produces atom A asserting "X
caused Y," the Contrarian produces a counter-atom or counter-warrant
showing the strongest case for "X did not cause Y" (or "the source is
silent on causation"). The Contrarian is not an Auditor — it does not
reject; it adds dissenting analysis that the supervisor and downstream
mapping phases weigh against the Extractor's consensus.

The Contrarian would consume the Extractor's atoms output, the
source-mirror manifest, and the pinned vocabulary snapshot — the same
inputs as the Auditor. It would additionally need access to the
project's stance registry (Phase 2 addition) so it can identify which
framings already have advocates and which need a steelman supplied.

The planned output contract is a list of counter-atoms (same `Atom`
schema as Extractor output, distinguished by a `role: contrarian`
provenance tag) plus a list of `dissents: [{against_atom_id,
counter_warrant, source_spans}]`. Counter-atoms enter the substrate
the same way Extractor atoms do (through validators); dissents are
first-class substrate records and feed Phase 2's
support/attack-edge layer.

The Phase 2 implementation gate for activating Contrarian: the support/attack
edge schema and the cross-document entity-resolution layer (INV-9
extension) must be in place, because Contrarian output only becomes
useful once multiple sources can attack one another's claims through
a shared entity graph.
