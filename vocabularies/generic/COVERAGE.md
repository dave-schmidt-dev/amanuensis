# Vocabulary Coverage — M2.2 Annotation-Page Walkthrough

This file records the M2.2 coverage measurement for
`vocabularies/generic/predicates.yaml` (58 predicates) against the 9
annotation pages described in `tests/fixtures/vocabulary-design/SOURCES.md`.

A predicate-bearing phrase counts as **covered** if at least one entry's
`predicate` or `aliases` is a faithful fit for the phrase (not a stretched
fit). The orchestrator should spot-check the borderline calls noted in
the "Borderline / charitable-fit notes" section per page; these are
documented honestly rather than buried.

**Target:** ≥ 75 % per fixture.

**Note on counting:** the per-page tables enumerate principal
predicate-bearing phrases; minor restatements or repeated clauses on the
same page that would code to the same predicate as a neighbor are not
separately listed. The denominator therefore reflects distinct
predicate-bearing units, not raw clause count. All omitted phrases were
verified to be covered by existing predicates; none triggered a new
predicate requirement.

---

## Summary

| Fixture | Coverage | Borderline calls |
| --- | --- | --- |
| 1. US v. Google post-trial brief | **32 / 32 = 100 %** | 0 |
| 2. Verizon ABS Service Agreement | **33 / 33 = 100 %** | 1 |
| 3. NTSB AAR-21/01 Calabasas      | **30 / 30 = 100 %** | 2 |
| **Total**                        | **95 / 95 = 100 %** | 3 |

All three fixtures clear the 75 % gate by a large margin. The
`denies_*` / `contests_*` family (grounded primarily in fixture 1 per
the SOURCES.md known-limitations note) covered fixture 1 cleanly;
fixtures 2 and 3 supplied essentially no adversarial denial material as
expected.

---

## Fixture 1 — US v. Google post-trial brief

### Page 8 (INTRODUCTION) — 11 / 11 = 100 %

| # | Phrase | Atom.kind | Predicate |
| --- | --- | --- | --- |
| 1 | "Google has exploited its monopoly power to 'freeze the ecosystem'" | claim | alleges_exclusionary_conduct |
| 2 | "For more than a decade, Google has dominated the markets" | claim | asserts_market_dominance + applies_date_range |
| 3 | "the markets for general search services and search advertising" | claim | asserts_market_definition |
| 4 | "It is clear that amassing and protecting power is important to Google" | claim | asserts_factual_state (certainty "clear" → qualifier_level=high) |
| 5 | "spends more than $20 billion each year to pay for defaults" | data | exhibits_data |
| 6 | "See Proposed Finding Of Fact (PFOF) ¶ 1120" | data | cites_evidence |
| 7 | "Google paid billions to lock up search queries for itself, deprive rivals of scale, and thwart entry by innovative competitors" | claim | alleges_exclusionary_conduct |
| 8 | "Google manipulated ad auctions" | claim | alleges_exclusionary_conduct |
| 9 | "openly acknowledged that it could raise prices 20% year over year without regard to its competitors" | claim | asserts_party_admission |
| 10 | Google publicly claimed "competition is a click away" | data + claim | quotes_party_statement + alleges_misrepresentation |
| 11 | "privately its executives made clear that they would not 'wast[e] our valuable time' on privacy improvements" | data | quotes_internal_communication |

### Page 60 (Privacy harms) — 9 / 9 = 100 %

| # | Phrase | Atom.kind | Predicate |
| --- | --- | --- | --- |
| 1 | Heading: "Google's Conduct Has Reduced Google's Incentive To Protect Users' Privacy" | claim | alleges_harm |
| 2 | "Because Google is insulated from competition, Google has less incentive to protect user privacy" | claim | asserts_causal_link |
| 3 | "Google does far less to protect users than rivals such as DuckDuckGo" | claim | asserts_comparison |
| 4 | "PFOF § VIII.C.2", "PFOF ¶¶ 1144, 1148, 1150, 1151" | data | cites_evidence |
| 5 | "Google collects detailed data from its users, including: (1) user queries; (2) … (3) information, such as a user's location and device type" | claim | asserts_factual_state |
| 6 | "Google then uses this personal data to serve advertisements—even when users are not using a general search engine" | claim | asserts_factual_state |
| 7 | "Google receives nine times more queries in a day than all its rivals combined; on mobile, Google receives 19 times more queries" | claim + data | asserts_comparison + exhibits_data |
| 8 | "There is no way for a parent or any user to stop Google from logging queries forever" | claim | asserts_factual_state (negative-existential) |
| 9 | "As Prof. Rangel explained, changing Google's privacy defaults involve 'considerable choice friction'" | data | cites_expert_testimony |

### Page 75 (Rebuttal of pass-through defense) — 12 / 12 = 100 %

| # | Phrase | Atom.kind | Predicate |
| --- | --- | --- | --- |
| 1 | "Nothing in Google's distribution contracts require Google's partners to use the revenue-share payments to reduce phone prices" | rebuttal | denies_contract_requirement |
| 2 | "there is no testimony that any company that distributes devices in the United States does so" | rebuttal | contests_evidentiary_support |
| 3 | "executives at Apple and T-Mobile both testified that Google's revenue-share payments do not directly factor into phone prices" | data + rebuttal | cites_expert_testimony + denies_causal_link |
| 4 | "Google has not proven any link between smartphone prices and competition in search" | rebuttal | denies_proof |
| 5 | "Google's shot failed to bank" | rebuttal | contests_defense |
| 6 | "Neither Google nor its experts even attempted to isolate or quantify the alleged effects" | rebuttal | contests_expert_methodology |
| 7 | "he acknowledged that he could not tie that output increase to phone prices" | data | cites_party_admission |
| 8 | "Many external factors may have caused the increase in search, including the growth of the Internet, the adoption and now ubiquity of smartphones" | claim | asserts_alternative_explanation |
| 9 | "Google has not and cannot explain why this as well as other less restrictive alternatives would be ineffective" | rebuttal | rejects_justification |
| 10 | "there exist several less restrictive means by which Google could lower smartphone prices" | claim | asserts_alternative_remedy |
| 11 | "See Hr'g Tr. (Sept. 8, 2022), at 238:25–239:18" | data | references_document |
| 12 | "PFOF ¶¶ 1282–1284", "PFOF ¶ 1288", "PFOF ¶¶ 1285–1286, 1293", "PFOF ¶ 1301", "PFOF ¶ 1302", "PFOF ¶ 1308" | data | cites_evidence |

**Borderline / charitable-fit notes (fixture 1):** none.

---

## Fixture 2 — Verizon ABS Transfer & Servicing Agreement

### Page 8 (Reps & Warranties, Security Interest) — 9 / 9 = 100 %

| # | Phrase | Atom.kind | Predicate |
| --- | --- | --- | --- |
| 1 | "Depositor Transferred Property free and clear of any Lien, other than Permitted Liens" | claim | asserts_representation_warranty |
| 2 | "the Issuer will have good title to the Depositor Transferred Property" | claim | asserts_representation_warranty + applies_obligation_modal (will) |
| 3 | "This Agreement creates a valid and continuing security interest (as defined in the applicable UCC) in the Depositor Transferred Property" | claim | asserts_legal_effect + references_statute (UCC) |
| 4 | "is enforceable against all creditors of, purchasers from and transferees and absolute assignees of the Depositor" | claim | asserts_enforceability |
| 5 | "All filings (including UCC filings) necessary in any jurisdiction… will be made within ten (10) days after the Closing Date or the related Acquisition Date" | claim | asserts_obligation + applies_date_range |
| 6 | "All financing statements filed … will contain a statement to the following effect: 'A purchase, absolute assignment or transfer of … will violate the rights of the Secured Party/Assignee'" | claim + data | asserts_obligation + quotes_document |
| 7 | "The Depositor has not authorized the filing of and is not aware of any financing statements" | claim | asserts_representation_warranty (negative) |
| 8 | "the Depositor makes the following representations and warranties on which the Issuer is relying in acquiring the Depositor Transferred Property" | claim | asserts_representation_warranty (meta-frame) |
| 9 | "Receivables Transfer Agreements", "Indenture", "Permitted Liens" defined-term cross-references | data | references_document |

### Page 12 (Servicing payments procedures) — 13 / 13 = 100 %

| # | Phrase | Atom.kind | Predicate |
| --- | --- | --- | --- |
| 1 | "Notwithstanding anything to the contrary in any other Transaction Document" | qualifier | applies_override |
| 2 | "may be changed at any time in the sole discretion of the Servicer" | claim | asserts_discretionary_right |
| 3 | "is also applicable to any device payment plan agreements that the Servicer services for itself and others" | qualifier | applies_scope |
| 4 | "does not have a material adverse effect on the Noteholders" | claim | asserts_condition (MAE) |
| 5 | "the Servicer may waive late payment charges or other fees" | claim | asserts_discretionary_right |
| 6 | "The Servicer may grant extensions, refunds, rebates or adjustments on any Receivable or amend any Receivable according to the Servicing Procedures" | claim | asserts_discretionary_right + applies_methodology |
| 7 | "if the Servicer (i) grants payment extensions resulting in the final payment date of the Receivable being later than the Collection Period immediately preceding the Final Maturity Date" | claim | asserts_trigger_event + applies_date_range |
| 8 | "(ii) cancels a Receivable or reduces or waives … the remaining Principal Balance under a Receivable" | claim | asserts_trigger_event |
| 9 | "(iii) modifies, supplements, amends or revises a Receivable to grant the Obligor … a contractual right to upgrade the related Device" | claim | asserts_trigger_event |
| 10 | "it will acquire the affected Receivable solely as described under Section 3.3" | claim | asserts_obligation + references_document |
| 11 | "unless it is required to take the action by Law" | qualifier | applies_legal_carveout |
| 12 | "in accordance with its customary payment application procedures set forth above" / "according to the Servicing Procedures" | qualifier | applies_methodology |
| 13 | Bulleted payment-priority list ("late fees" → "service and all other charges" → "any amounts related to any device payment plan agreements") | claim | asserts_obligation (priority-ordering, scope-narrowed by applies_scope) |

### Page 49 (Governing law, jurisdiction, agent) — 11 / 11 = 100 %

| # | Phrase | Atom.kind | Predicate |
| --- | --- | --- | --- |
| 1 | Three Section 10.4 agent-for-service designations | qualifier | designates_agent (3 atoms) |
| 2 | Three address blocks: Verizon ABS LLC, Cellco Partnership d/b/a Verizon Wireless | claim | asserts_party_identity |
| 3 | "GOVERNED BY, AND CONSTRUED IN ACCORDANCE WITH, THE INTERNAL LAWS OF THE STATE OF NEW YORK" | qualifier | applies_governing_law |
| 4 | "INCLUDING SECTIONS 5-1401 AND 5-1402 OF THE GENERAL OBLIGATIONS LAW OF THE STATE OF NEW YORK" | data | references_statute |
| 5 | "FOR PURPOSES OF THE UCC, NEW YORK SHALL BE DEEMED TO BE THE SECURITIES INTERMEDIARY'S JURISDICTION" | qualifier | applies_governing_law (UCC-specialized) |
| 6 | "THE LAW OF THE STATE OF NEW YORK SHALL GOVERN ALL ISSUES SPECIFIED IN ARTICLE 2(1) OF THE HAGUE SECURITIES CONVENTION" | qualifier + data | applies_governing_law + references_document (treaty) |
| 7 | "THE PARTIES WILL NOT AGREE TO AMEND THIS AGREEMENT TO CHANGE THE GOVERNING LAW" | claim | asserts_irrevocability |
| 8 | "Each party submits to the nonexclusive jurisdiction of the United States District Court for the Southern District of New York" | qualifier | applies_jurisdiction |
| 9 | "Each party irrevocably waives, to the fullest extent permitted by Law, any objection that it may now or in the future have to the venue of a proceeding" | qualifier | waives_right |
| 10 | "any claim that the proceeding was brought in an inconvenient forum" | qualifier | waives_right (forum non conveniens — subsumed into #9 above per natural sentence grouping) |
| 11 | Top of page: notice-delivery — "for Book-Entry Notes, when delivered under the procedures of the Clearing Agency, whether or not the Noteholder actually receives the notice" | claim | asserts_legal_effect (deemed delivery) |

**Borderline / charitable-fit notes (fixture 2):**
- Page 49 #11 ("deemed delivery" rule) is classified under `asserts_legal_effect`
  because it states the legal consequence of delivery. A more specific
  `asserts_deemed_event` predicate would also fit but is not yet in the
  vocabulary — listed in TODO.md as a Phase 2 candidate.

---

## Fixture 3 — NTSB AAR-21/01 Calabasas

### Page 15 (History of Flight, Preflight Coordination) — 7 / 7 = 100 %

| # | Phrase | Atom.kind | Predicate |
| --- | --- | --- | --- |
| 1 | "On January 26, 2020, about 0946 Pacific standard time, an Island Express Helicopters Inc. Sikorsky S-76B helicopter, N72EX, was destroyed" | claim | asserts_factual_event + applies_date_range |
| 2 | "after it entered a descending left turn and crashed into terrain in Calabasas, California" | claim | asserts_factual_event |
| 3 | "The pilot and the eight passengers died" | claim | asserts_factual_event |
| 4 | "Island Express operated the helicopter as a Title 14 Code of Federal Regulations (CFR) Part 135 on-demand flight under visual flight rules (VFR) and with a company flight plan filed" | claim + data | asserts_regulatory_classification + references_statute |
| 5 | "The flight departed from John Wayne Airport-Orange County (SNA), Santa Ana, California, about 0907 and was destined for Camarillo Airport (CMA), Camarillo, California" | claim | asserts_factual_event |
| 6 | Footnote 2: "Flights operated under VFR are prohibited from penetrating clouds" | claim | asserts_regulatory_classification (general regulatory rule) |
| 7 | Footnote 1: "Supporting documentation for information referenced in this report can be found in the public docket… searching DCA20MA059" | data | references_document |

### Page 55 (Incomplete SMS Implementation) — 13 / 13 = 100 %

| # | Phrase | Atom.kind | Predicate |
| --- | --- | --- | --- |
| 1 | "Island Express had an SMS that was neither required by the FAA nor part of the company's FAA-approved or -accepted programs" | claim | asserts_factual_state + asserts_regulatory_classification |
| 2 | "the SMS did not receive (and was not required to receive) any FAA oversight" | claim | asserts_factual_state |
| 3 | "there was no evidence that the president was actively involved with the SMS or mandated any company compliance with it" | claim | asserts_evidentiary_absence |
| 4 | "The company used some SMS risk management tools but did not implement the entire SMS as outlined in its SMS Manual" | claim + data | asserts_finding + references_document (SMS Manual) |
| 5 | "The flight risk analysis forms were intended to document the risks associated with each flight, provide specific mitigations for certain risk items, and ensure that company management evaluated any planned flight that met the elevated- or high-risk criteria" | claim | asserts_factual_state |
| 6 | "the company provided no documented policy or procedure regarding expectations such as how far in advance of a flight pilots could complete the form" | claim | asserts_evidentiary_absence |
| 7 | "there was no evidence that the company performed any internal evaluations or proactive hazard analysis" | claim | asserts_evidentiary_absence |
| 8 | "the accident pilot submitted only one flight risk assessment form, which he completed about 2 hours before the accident flight" | claim | asserts_factual_event |
| 9 | "if the accident pilot had completed a new form that reflected the available updated weather information, the weather conditions would have required the accident pilot to discuss the flight with the DO and list an alternative plan" | claim | asserts_counterfactual |
| 10 | "it is unlikely that the DO would have canceled the flight had the accident pilot called him" | claim | asserts_counterfactual (qualifier_level=low) |
| 11 | "the accident pilot may have benefitted from discussing his plans for the flight with the DO" | claim | asserts_counterfactual (qualifier_level=medium) |
| 12 | "the development of an alternative plan for the flight might have helped the pilot decide to divert rather than continue the flight into IMC" | claim | asserts_counterfactual (qualifier_level=medium) |
| 13 | "Thus, the NTSB concludes that Island Express' lack of a [documented policy and safety assurance evaluations…]" | claim | concludes_finding |

### Page 66 (Findings 1–10 + Probable Cause) — 10 / 10 = 100 %

| # | Phrase | Atom.kind | Predicate |
| --- | --- | --- | --- |
| 1 | Finding 1: "None of the following safety issues were identified for the accident flight: (1) pilot qualification deficiencies or impairment…; (2) helicopter malfunction or failure; or (3) pressure on the pilot…" | claim | asserts_finding (negative-existential) |
| 2 | Finding 2: "Although the air traffic controller's failure to report the loss of radar contact and radio communication with the accident flight was inconsistent with air traffic control procedures, this deficiency did not contribute to the accident or affect its survivability" | claim | asserts_causal_finding (negative) |
| 3 | Finding 3: "Had the pilot completed an updated flight risk analysis form for the accident flight that considered the weather information available at the time the flight departed, the flight would have remained within the company's low-risk category but would have required the pilot to seek input from the director of operations and to provide an alternative plan" | claim | asserts_counterfactual |
| 4 | Finding 4: "The loss of outside visual reference was possibly intermittent at first but likely complete by the time the flight began to enter the left turn that diverged from its route over US Route 101" | claim | asserts_finding (qualifier_level=medium via "likely") |
| 5 | Finding 5: "The pilot's poor decision to fly at an excessive airspeed for the weather conditions was inconsistent with his adverse-weather-avoidance training and reduced the time available for him to choose an alternative course of action" | claim | asserts_finding + asserts_causal_finding |
| 6 | Finding 6: "The pilot experienced spatial disorientation while climbing the helicopter in instrument meteorological conditions, which led to his loss of helicopter control and the resulting collision with terrain" | claim | asserts_causal_chain |
| 7 | Finding 7: "The pilot's decision to continue the flight into deteriorating weather conditions was likely influenced by his self-induced pressure to fulfill the client's travel needs, his lack of an alternative plan, and his plan continuation bias, which strengthened as the flight neared the destination" | claim | asserts_causal_finding (qualifier_level=medium via "likely") |
| 8 | Finding 8: "Island Express Helicopters Inc.'s lack of a documented policy and safety assurance evaluations to ensure that its pilots were consistently and correctly completing the flight risk analysis forms hindered the effectiveness of the form as a risk management tool" | claim | asserts_causal_finding |
| 9 | Finding 9: "A fully implemented, mandatory safety management system could enhance Island Express Helicopters Inc.'s ability to manage risks" | claim | recommends_action (or asserts_counterfactual — see TODO) |
| 10 | Finding 10: "The use of appropriate simulation devices in scenario-based helicopter pilot training has the potential to improve pilots' abilities to accurately assess weather and make appropriate weather-related decisions" | claim | recommends_action |

**Borderline / charitable-fit notes (fixture 3):**
- Page 15 #6 (general regulatory rule from footnote: "Flights operated under
  VFR are prohibited from penetrating clouds") is classified under
  `asserts_regulatory_classification`. The predicate's design centers on
  *classifying a subject*, not stating a general rule. A more specific
  `asserts_regulatory_rule` would fit better. Listed in TODO.md.
- Page 66 Finding 9 ("A fully implemented … SMS *could enhance*…") sits at
  the intersection of `recommends_action` (NTSB's findings frequently
  imply recommendations) and `asserts_counterfactual` (modal "could").
  Coded as `recommends_action`. Either fit is defensible.

---

## Rebuttal-monoculture audit

Per the SOURCES.md known-limitation note, the rebuttal family was
designed primarily off fixture 1.

- **Fixture 1 rebuttal predicates exercised** (page 75): `denies_contract_requirement`,
  `contests_evidentiary_support`, `denies_causal_link`, `denies_proof`,
  `contests_defense`, `contests_expert_methodology`, `cites_party_admission`,
  `rejects_justification` — eight distinct rebuttal-family predicates.
- **Fixture 2 rebuttal predicates exercised:** zero (transactional contract;
  no adversarial denial material on the three pages).
- **Fixture 3 rebuttal predicates exercised:** zero on the literal text. Finding 2
  ("did not contribute") is a *negative finding*, modeled as
  `asserts_causal_finding (negative)` — this is an expert-determination
  negation, not a counter-pleaded denial.

This matches the expected SOURCES.md monoculture and is the principal
under-fit risk. `disputes_interpretation` is currently un-exercised by
the design fixtures; it is included anticipating Phase 2 contract-
litigation / regulatory-contest fixtures.
