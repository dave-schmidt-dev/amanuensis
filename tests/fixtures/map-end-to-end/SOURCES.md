# Map End-to-End Fixtures — Sources

## Why a Python fixture-builder, not PDF files

T11.1 originally called for three synthetic PDFs (LaTeX/Typst/Pandoc) to seed the Phase 2a
map-pipeline end-to-end test. No PDF authoring tools (LaTeX, Typst, Pandoc, reportlab) are
installed in this environment, and adding a heavyweight optional dependency for a test fixture
would violate YAGNI.

The real purpose of T11.2 is to drive the **mapping pipeline** end-to-end — entity resolution,
surface-form deduplication across multiple sources, and idempotency replay — not to test PDF
ingestion. Phase 1's `test_distill_tiny_fixture.py` already covers PDF → substrate for that
pipeline. T6.8's `test_map_role_pair.py` demonstrates the same fixture-builder pattern on a
single distillation.

This fixture builder plants three distillations directly via project APIs (`Substrate`,
`add_atom`, `add_provenance`, `snapshot_vocabulary`), computing content-addressable ids via
`compute_id`, and writing atomic files via `add_provenance` / `add_atom` — the same discipline
the real ingest pipeline uses. The fix-on-disk format cannot drift from the production format
because it is written by the same code.

This approach mirrors `tests/e2e/_fixture_builder.py` and is documented in HISTORY.md (Phase 2a
M11, T11.1).

---

## The 3 distillations — mock contract / settlement scenario

Three documents represent a realistic legal corpus where multiple parties appear under slight
name variations across sources. The mapping pipeline must deduplicate them into canonical entities.

### 1. `contract-draft-1`
First draft of a commercial contract between ACME Corp and BetaCo Ltd, with a scheduled signing
event. Surface forms: **"ACME Corp"**, **"BetaCo Ltd"**, **"Contract Draft 1"**, **"Signing 1"**.

### 2. `contract-draft-2`
Revised draft of the same contract. Uses a slightly different spelling for ACME and BetaCo.
Surface forms: **"ACME Corporation"** (alias variation), **"BetaCo Ltd."** (period variant),
**"Contract Draft 2"**, **"Signing 2"**.

### 3. `settlement-instrument`
A settlement agreement that resolves a dispute arising from the contract. Uses the shortest-form
names. Surface forms: **"ACME Corp"**, **"BetaCo"** (no qualifier), **"Counsel for ACME"**,
**"Settlement Instrument"**, **"Settlement Event"**.

---

## Expected canonical entities after surface-form deduplication

Each distillation plants 3 atoms (one entity-kind obligor operand per atom), giving 9 atom
operand-refs across 3 sources. The map-resolve outputs are synthesized to deduplicate:

- "ACME Corp" and "ACME Corporation" collapse to **one canonical entity** (`canonical_name: "ACME Corp"`).
- "BetaCo Ltd", "BetaCo Ltd.", and "BetaCo" collapse to **one canonical entity** (`canonical_name: "BetaCo Ltd"`).
- Three document-specific names each become their own entity.

The 5 canonical entities are:

| # | `canonical_name`  | Surface forms merged                          | Spans sources        |
|---|-------------------|-----------------------------------------------|----------------------|
| 1 | ACME Corp         | "ACME Corp", "ACME Corporation"               | all 3 distillations  |
| 2 | BetaCo Ltd        | "BetaCo Ltd", "BetaCo Ltd.", "BetaCo"         | all 3 distillations  |
| 3 | Contract Draft 1  | "Contract Draft 1"                            | contract-draft-1     |
| 4 | Contract Draft 2  | "Contract Draft 2"                            | contract-draft-2     |
| 5 | Counsel for ACME  | "Counsel for ACME"                            | settlement-instrument|

The 9 atom operand-refs map to 5 canonical entities:
- contract-draft-1 atoms: ACME Corp (x1), BetaCo Ltd (x1), Contract Draft 1 (x1)
- contract-draft-2 atoms: ACME Corp (x1), BetaCo Ltd (x1), Contract Draft 2 (x1)
- settlement-instrument atoms: ACME Corp (x1), BetaCo Ltd (x1), Counsel for ACME (x1)

The ACME Corp entity has resolutions from atoms across **all 3 distillations**, exercising the
**cross-document resolution** property (T11.2 assertion 5). BetaCo Ltd likewise spans all 3.

---

## How to invoke the builder from a test

```python
from pathlib import Path
from tests.fixtures.map_end_to_end._fixture_builder import build_map_end_to_end_workspace

def test_something(tmp_path: Path) -> None:
    workspace = build_map_end_to_end_workspace(tmp_path)
    # workspace is an amanuensis workspace with 3 distillations planted
```

The builder also accepts an existing workspace path; it is effectively idempotent (the
content-addressable writes produce the same files on replay).

Command-line smoke test:

```
uv run python tests/fixtures/map-end-to-end/_fixture_builder.py /tmp/test-map-ws
```
