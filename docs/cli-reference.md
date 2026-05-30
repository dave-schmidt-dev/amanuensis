# CLI Reference

`amanuensis` is the command-line surface for the agent-consumable workspace
described in [`architecture.md`](./architecture.md). It is a thin Typer app
over the same Python functions the (future) web supervisor and dispatch
loop call; every command operates on a workspace rooted at a directory
that contains an `amanuensis.yaml` marker file
([INV-1](../INVARIANTS.md#inv-1--amanuensisyaml-marker-is-required-at-the-project-root)).

This document is the per-command reference. The companion documents are
[`architecture.md`](./architecture.md) (system-level) and
[`schema-reference.md`](./schema-reference.md) (per-record schemas).

## Marker requirement (INV-1)

Every command except [`init`](#init) refuses to run outside a workspace.
The check is a single decorator (`@require_marker` in
`src/amanuensis/cli/_marker.py`); on failure it prints a clear stderr
error and exits with code 2. Pass `--workspace PATH` (or `-w PATH`) to
operate on a workspace other than the current working directory.

## Read-only vs mutating

Each command below is classified as **read-only** or **mutating**. This
classification is the user-facing reflection of
[INV-4](../INVARIANTS.md#inv-4--determinism-boundary-is-named-gated-and-audited):
read-only commands are pure functions over substrate state — running them
twice on the same workspace yields identical output and no state changes.
Mutating commands cross the determinism boundary by writing new substrate
records, but they still have an idempotency contract (documented inline
below). The
[INV-4 gate test](../tests/invariants/test_determinism_boundary.py)
parametrically certifies the read-only side of this classification;
M5.3 will add the mutating-side counterpart.

## Global flags

| Flag | Description |
| --- | --- |
| `--version` | Print the installed `amanuensis` version and exit. |
| `--help` | Print top-level or per-command help and exit. |
| `--workspace PATH` / `-w PATH` | Workspace root containing `amanuensis.yaml`. Defaults to the current working directory. Accepted by every command except `--version`. |

## Commands

### `init`

```
amanuensis init [PATH]
```

- **Classification:** mutating.
- **Idempotency:** idempotent. Re-running on an existing workspace is a
  no-op for the marker; missing `docs/` and `.gitignore` are still
  created if absent.
- **Behavior:** Bootstraps a workspace at `PATH` (default: current
  directory). Writes `amanuensis.yaml` (the INV-1 marker, with
  `schema_version: 1` and `project_name: <basename>`), creates a `docs/`
  directory, and writes a default `.gitignore`. Does NOT acquire the
  workspace flock (the flock lives under the workspace root that this
  command is creating).
- **Notable flags:** none. The single positional `PATH` defaults to the
  current directory.
- **Example:** `amanuensis init ~/work/matter-2026-05`

### `ingest`

```
amanuensis ingest [--engine ENGINE] [--source-id ID] PDF_PATH
```

- **Classification:** mutating.
- **Idempotency:** refuses to re-ingest an existing `source_id`. The
  substrate raises `SourceMirrorExists` and the CLI surfaces it as a
  clean non-zero exit. To re-run, delete the distillation's
  `source-mirror/` directory.
- **Behavior:** Runs the chosen ingest engine over the PDF and writes
  `distillations/<source-id>/{source-mirror/, provenance/, vocabulary-snapshot.yaml}`.
  Acquires the workspace flock for the duration of the call. The source
  id defaults to `Path(pdf).stem`.
- **Notable flags:**
  - `--engine, -e {docling, pdfplumber}` (default: `docling`). `docling`
    is section-aware; `pdfplumber` is a lighter fallback with no
    `section_path`.
  - `--source-id, -s ID` — override the auto-derived source id.
- **Example:** `amanuensis ingest --engine docling docs/contract.pdf`

### `status`

```
amanuensis status [--json]
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Walks every distillation under `distillations/` and
  prints per-distillation counts (paragraphs, atoms, relations,
  open/resolved clarifications). With `--json`, emits a single
  machine-parseable JSON document instead of human-readable text.
- **Notable flags:**
  - `--json` — JSON output; sorted keys for stable diffs.
- **Example:** `amanuensis status --json`

### `atom list`

```
amanuensis atom list [--scale SCALE] SOURCE_ID
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Lists every atom id under the named distillation. Prints
  `id  scale=<x>  predicate=<y>` per atom, followed by a count line.
- **Notable flags:**
  - `--scale {sentence, paragraph, section, document}` — filter to atoms
    whose `scale_anchor` matches the given value
    ([INV-6](../INVARIANTS.md#inv-6--scale_anchor-is-mandatory-on-every-atom)).
- **Example:** `amanuensis atom list contract --scale paragraph`

### `atom show`

```
amanuensis atom show SOURCE_ID ATOM_ID
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Prints one atom's full on-disk form (YAML frontmatter +
  narrative body) by reading the substrate file directly.
- **Notable flags:** none.
- **Example:** `amanuensis atom show contract a-3f1e9c2b...`

### `atom validate`

```
amanuensis atom validate [--validator NAME] SOURCE_ID
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Runs the canonical M2 validators against every atom in
  the named distillation: `schema_check`, `citation_ledger`,
  `universe_check`, `scale_anchor`, `closed_vocabulary`,
  `provenance_completeness`. Prints per-validator pass/fail/skip counts
  and a list of failures. Exits 1 if any check fails, 0 otherwise.
  Note: `lineage_closure` runs over relations, not atoms, and is not
  invoked here.
- **Notable flags:**
  - `--validator NAME` — restrict to one validator by name; unknown
    names are rejected.
- **Example:** `amanuensis atom validate contract --validator closed_vocabulary`

### `clarification list`

```
amanuensis clarification list [--status STATUS]
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Walks every distillation's `clarifications/{open,resolved}/`
  and prints one line per clarification with its status, location,
  raiser, and a question excerpt. Optionally filtered by status.
- **Notable flags:**
  - `--status {open, resolved}` — filter to a single bucket.
- **Example:** `amanuensis clarification list --status open`

### `clarification resolve`

```
amanuensis clarification resolve --resolution TEXT [--resolver ID] CLARIFICATION_ID
```

- **Classification:** mutating.
- **Idempotency:** one-shot. The command searches every distillation's
  `clarifications/open/` for the id; if not found (already resolved or
  never existed), it fails clearly. A second `resolve` on the same id
  fails with the "no open clarification" error rather than silently
  re-writing.
- **Behavior:** Writes a paired `clarification-resolved` provenance
  record, flips the clarification's `status` to `resolved`, and removes
  the open-bucket file so the read paths see exactly one canonical
  location. Acquires the workspace flock for the duration of the write.
- **Notable flags:**
  - `--resolution TEXT` (required) — the resolution text to record.
  - `--resolver ID` (default: `cli`) — identifier recorded on the
    resolved-by agent (a `human` / `human_supervisor` attribution).
- **Example:** `amanuensis clarification resolve c-9a2f... --resolution "parent" --resolver dschmidt`

### `iteration list`

```
amanuensis iteration list
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Walks the workspace-level `iterations/` directory and
  prints one line per directive (status, id, target phase, target
  artifacts, directive excerpt).
- **Notable flags:** none.
- **Example:** `amanuensis iteration list`

### `iteration add`

```
amanuensis iteration add --directive TEXT --target-source ID \
                        [--rationale TEXT] [--target-phase PHASE] [--issuer ID]
```

- **Classification:** mutating.
- **Idempotency:** append-only. Each call always writes a NEW directive
  (and its paired `iteration-issued` provenance record). Running the
  command twice with identical arguments yields two distinct directive
  files — by design — because each directive is a separate event in the
  human-supervisor timeline.
- **Behavior:** Writes `iterations/<id>.md` and a paired PROV record
  filed under the target source's distillation. Acquires the workspace
  flock for the duration of the write.
- **Notable flags:**
  - `--directive TEXT` (required) — the directive text.
  - `--target-source ID` (required) — source id this directive applies
    to (recorded in `target_artifacts`).
  - `--rationale TEXT` (default: `(no rationale recorded)`).
  - `--target-phase {distill, map, extend, synthesize}` (default:
    `distill`).
  - `--issuer ID` (default: `cli`) — identifier of the human issuing
    the directive.
- **Example:** `amanuensis iteration add --directive "re-extract §3.2 with sentence grain" --target-source contract`

### `vocabulary list`

```
amanuensis vocabulary list
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Prints every canonical predicate in the active
  vocabulary, one per line with aliases summarised. The active
  vocabulary is resolved via the workspace's `domain.vocabulary_registry`
  if set, else the bundled generic registry, else an in-memory
  placeholder.
- **Notable flags:** none.
- **Example:** `amanuensis vocabulary list`

### `vocabulary show`

```
amanuensis vocabulary show PREDICATE
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Prints one vocabulary entry's full YAML representation
  (canonical predicate, aliases, operand types, qualifier requirement,
  notes). Accepts either the canonical name or an alias; an unknown
  predicate fails with a clear error.
- **Notable flags:** none.
- **Example:** `amanuensis vocabulary show asserts_obligation`

### `vocabulary snapshot`

```
amanuensis vocabulary snapshot SOURCE_ID
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Prints the per-distillation vocabulary snapshot file
  ([INV-10](../INVARIANTS.md#inv-10--vocabulary-is-pinned-per-distillation))
  to stdout. Fails with a clear error if the snapshot is missing.
- **Notable flags:** none.
- **Example:** `amanuensis vocabulary snapshot contract`

### `install-skills`

```
amanuensis install-skills [--harness HARNESS]
```

- **Classification:** read-only (M4.3 stub).
- **Idempotency:** re-running yields identical output. The stub detects
  installed harness CLIs via `shutil.which` and prints where skills
  WOULD install, but writes no files. M7.6 will re-classify this command
  as mutating and move its gating to the M5.3 mutating-side test.
- **Behavior:** Iterates the supported harnesses, probes for each
  binary on `PATH`, and reports detection + intended install directory.
- **Notable flags:**
  - `--harness {claude, codex, cursor, gemini, all}` (default: `all`).
- **Example:** `amanuensis install-skills --harness claude`

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Command body error (validator failure, missing atom, missing snapshot, ingest failure, etc.). |
| `2` | Preflight / usage failure — most often the INV-1 marker check (`amanuensis.yaml` missing) or an unknown enum value rejected by Typer before the command body runs. |

## Known limitations

The CLI surface is still landing milestone by milestone. As of M4.5:

- `install-skills` is an M4.3 stub: it detects harnesses but does not
  yet install skill files. M7.6 will finalise this command once M7.1
  ships the six skill files.
- No `distill`, `dispatch`, or `export` commands yet. They land in M7.3,
  M6.5, and M9.1 respectively.
- No web UI for supervision yet. The browser-based supervisor app is
  M8.
- The INV-4 read-only side is gated by
  `tests/invariants/test_determinism_boundary.py`; the mutating-side
  gate (cache + replay-log discipline for `init`, `ingest`,
  `clarification resolve`, `iteration add`) arrives in M5.3.

This list grows as more milestones land.
