# Vocabulary TODO — Gaps and Phase 2 Candidates

This file records gaps observed during M2.2 coverage measurement. The
COVERAGE.md walkthrough hit 100 % on all three design fixtures, so this
list is forward-looking — it captures **borderline / charitable-fit
phrases** where a more specific predicate would have been a cleaner
match than the catch-all that ended up covering them, plus
**predicates known to be under-exercised** by the three design fixtures
that Phase 2 fixtures should stress-test.

All gaps are speculative — they should not be added to
`predicates.yaml` without grounding in newly-collected fixtures (per
the M2.2 brief's YAGNI rule: no predicates not grounded in the design
corpus).

---

## Fixture 1 — US v. Google post-trial brief

No uncovered phrases on pages 8 / 60 / 75. No borderline-fit calls.

The brief exercises the full asserts / alleges / data / rebuttal axes
of the vocabulary as designed. Future expansion candidate noted under
"Cross-cutting" below.

---

## Fixture 2 — Verizon ABS Service Agreement

### Borderline-fit — page 49

- **Page 49 — claim — "for Book-Entry Notes, when delivered under the
  procedures of the Clearing Agency, whether or not the Noteholder
  actually receives the notice"**
  - **Current fit:** `asserts_legal_effect` (covers the legal
    consequence of constructive delivery).
  - **Why imperfect:** the phrase is specifically a "deemed event"
    clause — a legal fiction that an event has occurred regardless of
    physical reality. The legal-effect predicate is broader.
  - **Speculative future predicate:** `asserts_deemed_event` —
    operands `(event, condition, fiction_scope)`. Grounded by exactly
    one fixture-page phrase; should wait for a second instance from
    Phase 2 contract fixtures before adding.

### Under-exercised predicate families (transactional)

- `applies_scope` was used as a catch-all on page 12. Phase 2 may need
  finer-grained:
  - `applies_payment_priority` (waterfall / payment-priority qualifier)
  - `applies_account_application` (cross-account application rules)
- `asserts_trigger_event` was used for three different operational
  triggers on page 12. Phase 2 contract fixtures (with default events,
  termination events, force-majeure clauses) will likely want:
  - `asserts_default_event`
  - `asserts_termination_event`
  - `asserts_force_majeure_event`

---

## Fixture 3 — NTSB AAR-21/01 Calabasas

### Borderline-fit — page 15

- **Page 15 footnote 2 — claim — "Flights operated under VFR are
  prohibited from penetrating clouds"**
  - **Current fit:** `asserts_regulatory_classification` (charitable
    fit — the predicate centers on classifying a subject, not stating
    a general rule).
  - **Why imperfect:** this is a *rule statement*, not a *classification*
    of a particular subject under a rule.
  - **Speculative future predicate:** `asserts_regulatory_rule` —
    operands `(rule, authority, scope)`. Sibling to
    `asserts_regulatory_classification`. Useful in any expert report
    that recites the rules under which it analyzes a subject.

### Borderline-fit — page 66

- **Page 66 Finding 9 — claim — "A fully implemented, mandatory safety
  management system could enhance Island Express Helicopters Inc.'s
  ability to manage risks"**
  - **Current fit:** `recommends_action` (NTSB findings often imply
    recommendations; the modal "could enhance" tracks recommendation
    strength).
  - **Why imperfect:** this is hybrid — a counterfactual *and* a
    recommendation. The current vocabulary forces a choice.
  - **Speculative future predicate:** allow `recommends_action` to
    take an optional `evidentiary_basis` operand pointing to a
    counterfactual atom; or introduce `recommends_remedial_change`
    that explicitly carries both. Not urgent — the current coding is
    defensible.

### Under-exercised predicate families (expert)

- `concludes_finding` is exercised once (page 55) and the page-66
  Findings list uses `asserts_finding` / `asserts_causal_finding`
  instead. The brief calls for `concludes_finding` to be reserved for
  *institutional* conclusions (NTSB-as-Board) versus narrative analysis
  findings — verify this distinction holds with additional NTSB or
  other expert reports.
- `asserts_counterfactual` saw heavy use on page 55 and Finding 3 of
  page 66. The modal-certainty handling via `qualifier_level` carried
  the load (likely / unlikely / may / might / could). Phase 2 should
  confirm `qualifier_level` is sufficient or whether a separate
  `applies_modal_certainty` qualifier is needed for expert reports.

---

## Cross-cutting / Phase 2 stress-test candidates

These are predicate families included in the vocabulary that the
three design fixtures did not richly exercise. They are not gaps in
the current file — but Phase 2 fixtures must stress-test them or the
under-fit risk grows.

- **Rebuttal monoculture** (per SOURCES.md known limitation):
  `denies_*` / `contests_*` / `disputes_interpretation` /
  `rejects_justification` were exercised only by fixture 1.
  Stress-test fixtures Phase 2 should add: a litigation answer
  (replying to allegations), a regulatory contest filing, an
  opposition brief, an expert rebuttal report.
- **`disputes_interpretation`** is included anticipating Phase 2 but
  saw zero use on the design pages. It is the natural predicate for
  contract-interpretation litigation, statutory-construction disputes,
  and "what does the rule require" arguments — none of which the
  design corpus exercises directly.
- **`applies_methodology` / methodology-citation** — exercised lightly
  by fixture 2 (Servicing Procedures) and not at all by fixture 3 on
  the chosen pages. Aviation reports typically cite simulator
  protocols, toxicology procedures, and inspection methodologies;
  expanding into the NTSB methodology sections (Section 2 outside
  page 55) would exercise this more.
- **`exhibits_data`** — exercised on Google brief page 8 (the $20B
  figure) and page 60 (the 9x / 19x ratios) but not by fixture 2 or 3.
  Phase 2 financial / scientific fixtures will lean on this more.
- **`quotes_internal_communication`** — exercised once (Google brief
  page 8). Phase 2 employment / commercial-tort fixtures will
  exercise this much more heavily.

---

## Items NOT added (YAGNI)

These would be reasonable but lacked grounding in the design fixtures
and were deliberately excluded:

- `asserts_estoppel`, `asserts_unconscionability`, `asserts_unjust_enrichment`
  (equity / equitable defenses — no design-corpus grounding).
- `cites_legislative_history`, `cites_treatise`
  (the Google brief cites cases and PFOF; no treatises or legislative
  history on the chosen pages).
- `applies_burden_of_proof`, `applies_standard_of_review`
  (no jury-charge / appellate-review pages in the design corpus).
- `asserts_damages_quantum`, `asserts_remedy_request`
  (no remedies pages chosen; the Google brief reaches them elsewhere).
- `recommends_safety_recommendation_by_id`
  (the NTSB page 66 chosen does not include a numbered safety
  recommendation in the modern A-YY-NN form; future NTSB pages will).

---

## Domain-coverage limits (known blank space)

The editorial reviewer of the M2.2 vocabulary identified predicate-space
gaps that the three design fixtures (antitrust brief, transactional
contract, accident-investigation report) do not exercise. These domains
are deliberately out of scope for v0.1. **Phase 2 expansion will require
domain-specific fixtures targeting each blank category before vocabulary
v0.2.**

### Tort liability

- `alleges_negligence`, `alleges_breach_of_duty`, `alleges_malpractice`
  — the tort claim space is empty; a medical-malpractice or premises-
  liability fixture would land predicates here.

### Criminal law

- `alleges_criminal_conduct`, `charges_offense` — criminal indictments
  and plea documents have no landing predicates in v0.1.

### Environmental

- `alleges_contamination`, `asserts_emission_violation` — environmental
  enforcement actions and consent decrees are blank.

### Damages / remedy

- `asserts_damages`, `asserts_quantum`, `claims_remedy` — explicitly
  deliberately excluded for v0.1 (M2.2 fixtures do not exercise damages
  claims); these belong in a domain-specific extension or v0.2.

### Fraud with scienter

- `alleges_fraud`, `alleges_scienter` — `alleges_misrepresentation`
  exists but does not capture the knowing-falsity element required for
  fraud claims.

### Discovery / metadata

- `cites_document_metadata` (bates numbers, custodian metadata),
  `cites_deposition_objection` — depositions and discovery filings are
  blank.

---

## Domain-specific aliases held out of core

These aliases are domain-specific rather than generic and would belong
in a future domain-pack overlay rather than the generic-core vocabulary.

- `contests_defense` alias `contests_procompetitive_justification`
  (antitrust-specific) — moved to a future domain-pack overlay.
