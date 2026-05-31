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

The map-resolve outputs are written so that:

- "ACME Corp" and "ACME Corporation" collapse to **one canonical entity** (`canonical_name: "ACME Corp"`).
- "BetaCo Ltd", "BetaCo Ltd.", and "BetaCo" collapse to **one canonical entity** (`canonical_name: "BetaCo Ltd"`).
- Each document-specific name becomes its own entity.

The 9 canonical entities are:

| # | `canonical_name`       | Surface forms merged                               |
|---|------------------------|----------------------------------------------------|
| 1 | ACME Corp              | "ACME Corp", "ACME Corporation"                    |
| 2 | BetaCo Ltd             | "BetaCo Ltd", "BetaCo Ltd.", "BetaCo"              |
| 3 | Contract Draft 1       | "Contract Draft 1"                                 |
| 4 | Signing 1              | "Signing 1"                                        |
| 5 | Contract Draft 2       | "Contract Draft 2"                                 |
| 6 | Signing 2              | "Signing 2"                                        |
| 7 | Counsel for ACME       | "Counsel for ACME"                                 |
| 8 | Settlement Instrument  | "Settlement Instrument"                            |
| 9 | Settlement Event       | "Settlement Event"                                 |

The ACME Corp entity appears in atoms from all three distillations, exercising the
**cross-document resolution** property (T11.2 assertion 5).

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
