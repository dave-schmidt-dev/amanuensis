# Legal-Pleading Fixtures — Sources

A single representative legal pleading used by M3.4's ingest-fidelity test
(`tests/ingest/test_legal_pdf_fidelity.py`) to verify that the source-mirror
ingest pipeline preserves the structural and citation density of a real-world
court filing.

The same file appears under `tests/fixtures/vocabulary-design/` for M2.x
predicate-design work — **git deduplicates the blob** (content-addressable
storage means an identical file costs effectively one blob in the object
database regardless of how many paths reference it). The duplicate path is
intentional: each fixture directory documents its own purpose and provenance
so a reader landing in either directory has the full context without
cross-references.

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
- **Why this fixture (M3.4)**: A post-trial brief is exactly the representative
  legal pleading the Phase 1 plan calls for. It carries the three structural
  features the fidelity test exercises:
  1. **Dense citation references** — PFOF paragraph cites (`Pls. PFOF ¶ NNN`),
     trial-transcript cites (`Tr. NNN:NN-NN`), exhibit cites, statutory cites
     (Sherman Act §2), and case cites (notably Microsoft, `253 F.3d 34`).
  2. **Explicit numbered footnotes** throughout the brief — Docling marks these
     with `DocItemLabel.FOOTNOTE`, so the ingest pipeline's preservation of
     footnote linkage can be verified directly from the manifest.
  3. **Clear logical-paragraph structure with section headers** — introduction,
     argument I.A, argument I.B, etc. — so the paragraph segmentation can be
     spot-checked against a defensive lower bound on paragraph count and a
     non-trivial median `char_count`.
- **Used by**: `tests/ingest/test_legal_pdf_fidelity.py` (M3.4 fidelity test)
  and `tests/ingest/test_ingest_determinism.py` (M3.3 determinism test,
  parametrized over both engines × both fixtures from M3.4 onward).

### Notes on redactions

The PDF carries multiple redaction boxes (confidential commercial figures); see
the parallel `vocabulary-design/SOURCES.md` entry for the per-page annotation
detail. The fidelity test does not depend on the redacted content — its checks
target citation density and structural-paragraph count, both of which are
unaffected by the redactions.
