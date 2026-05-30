---
name: distill_premortem
description: Premortem role (STUB, Phase 2) — catalogs failure modes for the extraction before they happen.
role: premortem
version: 0.1.0
active: false
stub: true
stub_reason: "Phase 1 ships Extractor + Auditor only; Premortem (catalogs failure modes for the extraction before they happen) is Phase 2."
expects_substrate: true
phase: distill
cli_commands_invoked: []
---

The Premortem's job in Phase 2 will be to enumerate the ways this
specific extraction is most likely to go wrong before the Extractor
runs. Given a source-mirror and the pinned vocabulary, the Premortem
predicts: which paragraphs are most likely to produce
warrant-contested atoms; which predicates in the snapshot are most
likely to be misapplied to this source's genre; where the source's
structure (footnotes, parentheticals, citations of other documents)
will tempt the Extractor into INV-7 four-tuple violations. The
Premortem is preventive — its output narrows the Extractor's risk
surface and primes the Auditor's attention.

The Premortem would consume the source-mirror manifest (paragraph
text included), the pinned vocabulary snapshot, and a corpus of past
distillations' rejected atoms and clarifications (Phase 2 addition;
serves as the failure-pattern training set the Premortem reasons
over).

The planned output contract is a list of
`risk_flags: [{paragraph_index, risk_category, narrative,
suggested_mitigation}]` where `risk_category` is drawn from a small
closed set (e.g., `ambiguous-causation`, `nested-citation`,
`scale-collision`, `vocabulary-mismatch`). The reconciliation gate
attaches matching risk_flags to atoms emitted from those paragraphs
so the supervisor sees the prediction alongside the realized output.

The Phase 2 implementation gate for activating Premortem: the
historical-failure corpus must exist (which requires at least one
prior completed distillation per project), and the risk-category
closed set must be governance-versioned the same way the predicate
vocabulary is — otherwise the Premortem's output drifts and stops
being useful as a Phase 2 substrate input.
