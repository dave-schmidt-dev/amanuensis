# Ingest fallbacks — fixtures requiring the pdfplumber engine

This file lists fixtures for which the Docling ingester (M3.1, default)
produces **non-deterministic paragraph output** across re-runs of the
same PDF bytes + vocabulary snapshot + Docling version. The project's
mitigation is recorded here so future contributors do not have to
re-discover the failure mode: such fixtures are routed through the
pdfplumber fallback engine (M3.2,
`amanuensis.ingest.ingest_pdf_pdfplumber`), which is structurally
identical at the manifest level but trades section-path fidelity for
lighter, deterministic extraction.

The M3.3 determinism gate
(`tests/ingest/test_ingest_determinism.py`) is what surfaces these
cases: if it fails for the docling engine on a fixture, log the fixture
below with the symptom, then add the fixture to the pdfplumber path in
whatever calling code routes ingest engine choice.

> Auto-fallback wiring is intentionally NOT part of M3.3 — the manifest
> field `ingest_engine` is set by whichever entrypoint the caller picks.
> This file is the human-in-the-loop record so the call-site decision
> has a documented rationale.

## Known fallbacks

(none yet)

## Format

When adding an entry, use one row per fixture with these columns:

`fixture_path | first_observed | symptom | mitigation`

- **fixture_path**: relative path under `tests/fixtures/`
- **first_observed**: ISO date (YYYY-MM-DD) when non-determinism was
  first reproduced
- **symptom**: short description of what drifted (paragraph count,
  section_path on paragraph N, content_sha256 on paragraph N, etc.)
- **mitigation**: `pdfplumber` (the default for now) or a fuller note
  if a smarter routing decision is warranted
