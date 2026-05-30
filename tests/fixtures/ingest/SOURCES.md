# Ingest Fixtures — Sources

PDFs used by `tests/ingest/` to drive the Docling source-mirror pipeline.
Kept deliberately small so the ingest test runs in seconds, not minutes.

---

## 1. `simple-contract.pdf` — first 3 pages of the CUAD Verizon contract

- **Source name**: Pages 1–3 (PDF page indices, 1-based) of
  *Form of Transfer and Servicing Agreement* among Verizon Owner Trust
  2020-A, Verizon ABS LLC, and Cellco Partnership (d/b/a Verizon Wireless),
  dated January 29, 2020. The full 106-page document lives at
  `tests/fixtures/vocabulary-design/cuad-verizon-abs-service-agreement-2020.pdf`;
  see that directory's `SOURCES.md` for the upstream URL and licensing
  basis.
- **Page selection**: Title page, ARTICLE I/II markers, and the start of
  the Table of Contents. Dense enough that Docling extracts ≥5 paragraphs
  and at least one SECTION_HEADER, which the simple-PDF ingest test
  asserts on.
- **License / public-domain basis**: Inherited from the upstream CUAD
  dataset compilation, released by The Atticus Project under
  **CC-BY-4.0** (https://creativecommons.org/licenses/by/4.0/);
  underlying document is a publicly-filed SEC EDGAR exhibit (Verizon ABS
  LLC, 8-K, January 23, 2020, Exhibit 10.4). See the
  `tests/fixtures/vocabulary-design/SOURCES.md` for full attribution.
- **Extraction recipe** (one-shot during fixture creation; NOT re-run by
  the test suite):

      uv run python <<'EOF'
      import pypdfium2 as pdfium
      src = 'tests/fixtures/vocabulary-design/cuad-verizon-abs-service-agreement-2020.pdf'
      dst = 'tests/fixtures/ingest/simple-contract.pdf'
      src_doc = pdfium.PdfDocument(src)
      new_doc = pdfium.PdfDocument.new()
      new_doc.import_pages(src_doc, [0, 1, 2])
      new_doc.save(dst)
      EOF

  `pypdfium2` is already pulled in transitively by the Docling install;
  no extra dependency was added for fixture creation.
- **Why pages 1–3**: The first three pages exercise paragraph extraction
  (title/parties block), section-header detection (ARTICLE I, ARTICLE II,
  TABLE OF CONTENTS), and page-number tracking across multiple pages,
  while keeping the test runtime to ~30 seconds on CPU. M3.4 will add a
  legal-pleading fixture separately.
