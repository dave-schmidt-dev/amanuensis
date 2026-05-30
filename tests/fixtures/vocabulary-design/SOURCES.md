# Vocabulary-Design Fixtures — Sources

Three publicly-available PDFs acquired in M2.1 to drive M2.2 predicate-vocabulary
design. Each document was chosen so the three collectively exercise the full
predicate space (`asserts_*`, `alleges_*`, `cites_evidence`, `references_document`,
`denies_*`, `contests_*`) and qualifier space (`jurisdiction`, `date_range`,
`certainty_level`, methodology references).

Domains spanned: **(1) federal antitrust litigation, (2) asset-backed-securities
servicing / consumer-telecom finance, (3) aviation safety / transportation
accident investigation.**

---

## 1. Legal Pleading — `us-v-google-plaintiffs-post-trial-brief-2024.pdf`

- **Source name**: *Plaintiffs' Post-Trial Brief [Redacted]*, United States and
  Plaintiff States v. Google LLC, Case No. 1:20-cv-03010-APM, U.S. District
  Court for the District of Columbia. Brief dated February 9, 2024; filed on the
  PACER docket February 23, 2024. Document 837. Author: U.S. Department of
  Justice, Antitrust Division.
- **URL**: https://www.justice.gov/atr/media/1340241/dl?inline
  (linked from the DOJ case page:
  https://www.justice.gov/atr/case/us-and-plaintiff-states-v-google-llc).
- **License / public-domain basis**: Work of the United States Government,
  authored by DOJ Antitrust Division attorneys in the course of their official
  duties. Public domain under **17 U.S.C. § 105**. Additionally a public court
  filing on the PACER docket (Case 1:20-cv-03010-APM, Doc. 837).
- **Why this fixture**: A post-trial brief is the *richest* form of legal
  pleading for vocabulary design — it carries the full adversarial structure of
  a complaint (asserts, alleges, cites evidence) *plus* explicit denial and
  contest language rebutting the opposing party's defenses. Exercises
  `asserts_*` (market-definition findings), `alleges_*` (Google's exclusionary
  conduct), `cites_evidence` (PFOF paragraph cites, trial-transcript cites,
  exhibit cites), `references_document` (the Sherman Act, Microsoft 253 F.3d 34,
  contracts), `denies_*` and `contests_*` (sections rebutting Google's
  procompetitive-justification defenses), and qualifier types `jurisdiction`
  (D.D.C.), `date_range` (decade-long conduct claims), and `certainty_level`
  (e.g., "plainly", "clearly", "made-for-litigation excuses").
- **Annotation pages** (PDF page numbers):
  - **Page 8** — INTRODUCTION. Dense `asserts_*` + `alleges_*` against Google
    with embedded numeric qualifiers ($20B/year, decade-long monopoly) and
    high-certainty modal language. *Annotation note:* several confidential
    figures on this page are redacted in the source PDF; `pdftotext` renders
    the redaction boxes as stray short tokens (e.g., the word "on"). These are
    intentional redactions, not extraction errors — treat the surrounding
    sentence as the unit of annotation and skip the redacted numeric token.
  - **Page 60** — Section IV.B on privacy harms. Dense `cites_evidence` to
    PFOF paragraph numbers; factual claims qualified with comparative
    quantifiers ("nine times more", "19 times more").
  - **Page 75** — Section rebutting Google's smartphone-price pass-through
    defense. Pure `denies_*` / `contests_*` exemplar ("Google has not proven",
    "Nothing in Google's distribution contracts require", "Google's shot failed
    to bank", "made-for-litigation excuses with no basis").

---

## 2. Contract — `cuad-verizon-abs-service-agreement-2020.pdf`

- **Source name**: *Form of Transfer and Servicing Agreement* among Verizon
  Owner Trust 2020-A (as Issuer), Verizon ABS LLC (as Depositor), and Cellco
  Partnership d/b/a Verizon Wireless (as Servicer, Marketing Agent, and
  Custodian), dated as of January 29, 2020. Filed as Exhibit 10.4 to a Verizon
  ABS LLC Form 8-K on January 23, 2020 (SEC EDGAR). Distributed to this project
  as part of the Contract Understanding Atticus Dataset (CUAD) v1,
  `Part_I/Service/`.
- **URL**: Acquired from CUAD v1 via the Atticus Project's HuggingFace mirror —
  https://huggingface.co/datasets/theatticusproject/cuad/resolve/main/CUAD_v1/full_contract_pdf/Part_I/Service/VerizonAbsLlc_20200123_8-K_EX-10.4_11952335_EX-10.4_Service%20Agreement.pdf
  CUAD landing page: https://www.atticusprojectai.org/cuad
  Original SEC filing: Verizon ABS LLC 8-K, 1/23/2020 (the PDF footer cites the
  EDGAR source on every page).
- **License / public-domain basis**: **Dual basis.** (1) The underlying document
  is a publicly-filed SEC EDGAR exhibit (Verizon ABS LLC, 8-K, accession
  reference visible on page footers), available for broad research use as a
  public filing. (2) The CUAD dataset compilation, in which this PDF travels,
  is released by The Atticus Project under **CC-BY-4.0**
  (https://creativecommons.org/licenses/by/4.0/). Attribution: Hendrycks, Burns,
  Chen, Ball, *CUAD: An Expert-Annotated NLP Dataset for Legal Contract Review*
  (NeurIPS 2021).
- **Why this fixture**: A 106-page real-world commercial agreement with
  extraordinary clause density: representations & warranties, servicing
  obligations, jurisdiction/governing-law clauses, UCC perfection language,
  defined-term references, dated effectiveness conditions, and reacquisition /
  acquisition triggers. Exercises `asserts_*` (representations & warranties),
  `references_document` (cross-references to Receivables Transfer Agreements,
  Indenture, UCC, Hague Securities Convention), and qualifier types
  `jurisdiction` (New York governing law; SDNY venue submission), `date_range`
  (Closing Date, Acquisition Date, Collection Period, Final Maturity Date),
  and `certainty_level` (mandatory vs. permissive verb forms — "will",
  "shall", "may", "irrevocably waives").
- **Annotation pages** (PDF page numbers):
  - **Page 8** — Section 2.4 Representations & Warranties about Depositor
    Transferred Property + Section 2.5 Eligibility Representation triggers.
    Pure `asserts_*` density with UCC jurisdictional qualifiers.
  - **Page 12** — Section 3.2 Servicing of Receivables, subsections (c)-(h).
    Obligation language ("will maintain", "will not impair", "is authorized to
    execute") with embedded dated triggers (Cutoff Date) and cross-references.
  - **Page 49** — Section 10.4 Agent for Service + Section 10.5 GOVERNING LAW
    + Section 10.6 Submission to Jurisdiction. Canonical jurisdiction-qualifier
    text (New York internal law; SDNY non-exclusive jurisdiction; UCC Article
    2(1) Hague Securities Convention reference).

---

## 3. Expert Report — `ntsb-aar2101-calabasas-helicopter-crash-2021.pdf`

- **Source name**: *Aircraft Accident Report — Rapid Descent Into Terrain,
  Island Express Helicopters Inc., Sikorsky S-76B, N72EX, Calabasas, California,
  January 26, 2020*. NTSB/AAR-21/01, PB2021-100900. Adopted February 9, 2021,
  by the National Transportation Safety Board. (Investigation ID
  DCA20MA059 — commonly known as the Kobe Bryant helicopter crash
  investigation.)
- **URL**: https://www.ntsb.gov/investigations/AccidentReports/Reports/AAR2101.pdf
- **License / public-domain basis**: Work of the United States Government,
  prepared by NTSB staff and adopted by the five-member Board. Public domain
  under **17 U.S.C. § 105**. The NTSB is an independent federal agency
  established by the Independent Safety Board Act of 1974 (49 U.S.C. § 1101 et
  seq.); its reports are public documents (with the statutory caveat at 49
  U.S.C. § 1154(b) restricting their admissibility in civil damages actions —
  a restriction that does not affect their public-domain status for
  research use).
- **Why this fixture**: A formal expert technical report covering 86 pages of
  factual narrative, methodology, cited evidence, qualified findings, and a
  formal probable-cause determination. Exercises `asserts_*` (history-of-flight
  factual claims), `cites_evidence` (witness testimony, radar tracks,
  ForeFlight data, training records, regulatory filings, prior NTSB safety
  studies), `references_document` (14 C.F.R. Part 135, prior Safety
  Recommendations A-09-89 / A-16-36 / A-13-13 / A-20-29, the SMS Manual, FAA
  rules), and qualifier types `certainty_level` (an unusually rich vein:
  "likely", "possibly intermittent", "likely complete", "may have benefitted",
  "would have remained", "the NTSB concludes that…", "the National
  Transportation Safety Board determines that the probable cause of this
  accident was…") and `date_range` (precise UTC/Pacific times throughout the
  flight narrative). Methodology references appear via simulator-test and
  toxicology-protocol citations.
- **Annotation pages** (PDF page numbers):
  - **Page 15** — Section 1.1 History of the Flight + Section 1.1.1 Preflight
    Coordination. Dense factual `asserts_*` with multi-source `cites_evidence`
    (witness statements, ForeFlight server logs, Leidos records, company
    records).
  - **Page 55** — Section 2.4 analysis of Incomplete SMS Implementation.
    Expert reasoning with explicit "NTSB concludes" language and cited
    regulatory history.
  - **Page 66** — Section 3.1 Findings (list of 13 numbered findings) and
    Section 3.2 Probable Cause. The canonical certainty-qualified
    expert-conclusion exemplar — every finding carries an explicit modal
    qualifier and the probable-cause paragraph is the locus classicus of
    `certainty_level` expert language.

---

## Diversity Check

| Fixture | Domain | Posture |
| --- | --- | --- |
| US v. Google Post-Trial Brief | Federal antitrust litigation (Sherman Act §2) | Adversarial — plaintiff |
| Verizon ABS Transfer & Servicing Agreement | Asset-backed-securities servicing / consumer-telecom finance | Multi-party transactional |
| NTSB AAR-21/01 | Aviation safety / transportation accident investigation | Independent expert |

Three distinct domains; three distinct postures (adversarial advocacy,
transactional drafting, neutral expert determination). The set should support
M2.2's predicate-coverage target (≥75%) without leaving structural gaps.

---

## Known Limitations (for M2.2 annotators)

- **Rebuttal monoculture.** The `denies_*` / `contests_*` predicate family is
  exercised richly only by the US v. Google post-trial brief (fixture 1). The
  Verizon contract is transactional and supplies essentially no adversarial
  denial material; the NTSB report contains only sparse negated findings ("did
  not contribute to…") rather than counter-pleaded denials. M2.2 should design
  the rebuttal sub-vocabulary primarily off fixture 1 and explicitly mark that
  decision as a known under-fit risk. Phase 2 expansion fixtures (e.g., a
  litigation answer, a regulatory contest, an opposition brief) should
  stress-test the rebuttal vocabulary later. If M2.2 cannot reach ≥75%
  rebuttal-predicate coverage from fixture 1 alone, the right move is to add
  one short supplemental excerpt rather than re-pick the three primary
  fixtures.
- **PDF page indices vs. printed page numbers.** All annotation page numbers in
  this document are **PDF page indices** (1-based, as accepted by
  `pdftotext -f N -l N` and most PDF readers' page selectors), not the printed
  page numbers stamped on the documents. The two often differ by a small
  cover/ToC offset (≈ 7 pages for the Google brief, smaller offsets for the
  contract and NTSB report). Open the PDF directly to the listed index.
- **No content hashing.** Fixtures are pinned by filename + upstream URL, not
  by SHA. The three upstream sources are versioned-enough for M2.2 work; if
  reproducibility-by-hash is wanted later, a manifest can be added without
  re-downloading.
