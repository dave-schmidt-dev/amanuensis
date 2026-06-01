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

### `export`

```
amanuensis export <source-id> --output FILE.html [--no-include-mappings]
amanuensis export --workspace-appendix --out-dir DIR
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  byte-identical output ([INV-8](../INVARIANTS.md#inv-8--substrate-is-the-source-of-truth)
  render-purity).
- **Behavior:** Two operating modes:

  1. **Per-source single-file (Phase 1, M9.1):** writes one
     self-contained HTML file at `--output` containing the source-mirror
     summary, every paragraph body, every atom, every relation, and the
     Phase 2a entity sidebar / resolution annotations (toggleable). Fails
     with exit 1 if the source has not been ingested.
  2. **Workspace appendix bundle (Phase 2b, M9 + T10.0):** writes a
     directory at `--out-dir` containing `cross-doc-relations.html` (an
     appendix grouped by `kind`) plus `entities/<id>.html` per canonical
     entity, each page listing the cross-doc edges touching that entity.
     Useful for share-or-archive of the cross-doc reasoning. Mutually
     exclusive with the positional `<source-id>` argument and with
     `--output`.

  Both modes are read-only — no flock acquired.
- **Notable flags:**
  - `--output, -o PATH` (Phase 1 mode) — destination HTML file.
  - `--format, -f {static-html}` (default: `static-html`) — only value
    in Phase 1.
  - `--include-mappings / --no-include-mappings` (default: include) —
    Phase 1 mode only; toggles the Phase 2a entity sidebar.
  - `--workspace-appendix` (Phase 2b mode) — switches to the bundle
    exporter. Requires `--out-dir`.
  - `--out-dir PATH` (Phase 2b mode) — destination directory for the
    bundle. Created (with parents) if missing; existing files at the same
    paths are overwritten.
- **Example (Phase 1):**
  `amanuensis export case-2024-001 --output report.html`
- **Example (Phase 2b):**
  `amanuensis export --workspace-appendix --out-dir cross-doc-bundle/`

## amanuensis map

Phase 2 mapping commands. `amanuensis map` runs the full map
warp-plan cycle in three phases (Resolve / Audit, Connect, Hierarchize);
its sub-apps `entity`, `resolution`, `vocabulary`, `relation`,
`probandum`, `probandum-edge`, and `walton-scheme` provide read-only
inspection and supervisor-correction verbs. All commands require the
INV-1 marker. Mutating commands acquire the workspace flock
([INV-4](../INVARIANTS.md#inv-4--determinism-boundary-is-named-gated-and-audited)).
Entities, resolutions, cross-doc relations, probanda, and
probandum-edges all live under `mappings/`
([INV-12](../INVARIANTS.md#inv-12--mappings-is-the-home-for-all-cross-document-artifacts)).

### `map` (orchestrator)

```
amanuensis map [--role-set ROLES] [--non-interactive] [--connect-only] [--hierarchize-only]
```

- **Classification:** mutating.
- **Idempotency:** the enqueue step is append-only (each call creates a
  new dispatch queue entry with its own inputs hash). Running the command
  twice with the same substrate state writes two entries but downstream
  dispatch deduplicates on inputs hash.
- **Behavior:** Runs the full map cycle in three phases:
  1. **Resolve / Audit (Phase 2a).** Pins the entity-vocabulary snapshot
     at `mappings/entity-vocabulary-snapshot.yaml` if not present,
     enqueues `map-resolve` (and on a second invocation, after the
     supervisor runs `amanuensis dispatch --once`, the `map-audit`
     role), and appends a mappings replay-log entry. Requires
     `map_resolve.md` and `map_audit.md` to be installed in the active
     harness skills directory; fails with exit 2 if either is missing.
  2. **Connect (Phase 2b).** Enumerates canonical-entity clusters that
     span at least two distillations, enqueues one `connect` dispatch
     event per cluster, and reconciles any already-completed connect
     outputs through `_process_connect_output`. The connect-phase
     summary line names the per-cluster enqueue / reconciled counts.
  3. **Hierarchize (Phase 2c).** Enumerates clusters keyed by
     penultimate parent probanda, enqueues one `hierarchize` dispatch
     event per cluster, and reconciles any already-completed
     hierarchize outputs through `_process_hierarchize_output`. Skipped
     silently when the Walton-scheme snapshot is missing — pin it via
     `amanuensis map walton-scheme snapshot` first. The hierarchize
     phase summary line names the per-cluster enqueue / reconciled
     counts.

  Acquires the workspace flock for the duration of phases 1 + 2; phase
  3 re-acquires the flock independently. Fails with exit 1 if no
  distillations exist.
- **Notable flags:**
  - `--role-set ROLES` (default: `map-resolve,map-audit`) — comma-separated
    list of roles to enqueue. Changing this is an advanced operation.
  - `--non-interactive` — accepted for forward compatibility with a future
    interactive mode; currently a no-op.
  - `--connect-only` (Phase 2b) — skip the Resolve / Audit phase entirely
    and run the Connect + Hierarchize phases against an already-resolved
    substrate. Useful when the resolve+audit substrate is settled and
    the operator just wants to refresh cross-doc edges (and the
    downstream probandum tree). The orchestrator does NOT re-check
    `map_resolve.md` / `map_audit.md` presence in this mode (it
    assumes a prior `amanuensis map` run validated them).
  - `--hierarchize-only` (Phase 2c) — skip Resolve / Audit and Connect
    entirely; run only the Hierarchize phase. Useful when the
    resolve + connect substrate is settled and the operator just wants
    to refresh the probandum tree. Requires a pinned Walton-scheme
    snapshot (`amanuensis map walton-scheme snapshot`); fails with
    exit 2 if missing. Assumes a prior full `map` run validated skill
    presence.
- **Example:** `amanuensis map` then `amanuensis dispatch --once`
- **Example (Phase 2b):** `amanuensis map --connect-only` after the
  substrate is fully resolved.
- **Example (Phase 2c):** `amanuensis map --hierarchize-only` after the
  connect substrate is settled and the supervisor has authored an
  ultimate + penultimates.

### `map status`

```
amanuensis map status [--source-id ID] [--json]
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes. No flock acquired (INV-4).
- **Behavior:** Walks the workspace and prints per-distillation and
  aggregate counts: `entity_operand_count` (operands with `kind=entity`),
  `resolved_count` (those with an active resolution),
  `unresolved_count`, `open_clarification_count` (open clarifications
  whose kind is in `{resolution-disputed, resolution-ambiguous}`), and
  `last_map_run_at` (newest mappings replay-log entry, or `"never"`).
- **Notable flags:**
  - `--source-id ID` — restrict output to a single distillation.
  - `--json` — emit machine-parseable JSON (sorted keys, stable diffs).
- **Example:** `amanuensis map status --json`

### `map entity list`

```
amanuensis map entity list [--kind KIND]
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Lists every canonical entity in `mappings/entities/`,
  sorted by kind then canonical name. Prints
  `<id>  kind=<k>  canonical=<name>  aliases=<count>` per entity.
- **Notable flags:**
  - `--kind KIND` — filter to entities of the given kind; the kind must
    be in the active vocabulary snapshot or the command fails with exit 2.
- **Example:** `amanuensis map entity list --kind person`

### `map entity show`

```
amanuensis map entity show ENTITY_ID
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Prints one entity's on-disk content (YAML frontmatter +
  markdown body), then appends a "Resolutions pointing here" block and
  a "Supersede chain" block. The supersede chain shows the full forward
  chain from this entity id to the latest canonical entity.
- **Notable flags:** none.
- **Example:** `amanuensis map entity show e-3f1e9c2b...`

### `map entity merge`

```
amanuensis map entity merge A_ID B_ID --canonical ENTITY_ID \
                            --reason TEXT [--actor ID] [--dry-run] [--force]
```

- **Classification:** mutating.
- **Idempotency:** append-only. Each call writes a new `EntitySupersede`
  record and its paired provenance record. Running twice writes two
  records (duplicate-merge guard is not applied; use `--force` to merge
  an already-superseded entity).
- **Behavior:** Writes an `EntitySupersede` record (prefixed `t-`) in
  `mappings/supersedes/` pointing `A_ID` or `B_ID` (whichever is not
  `--canonical`) at the surviving entity, plus a paired
  `ProvenanceRecord` in `mappings/provenance/`. Acquires the workspace
  flock for the duration of the write.
- **Notable flags:**
  - `--canonical ENTITY_ID` (required) — the entity id that survives the
    merge; must already exist in `mappings/entities/`.
  - `--reason TEXT` (required) — reason text recorded in the
    `EntitySupersede` record.
  - `--actor ID` (default: `cli`) — identifier recorded in the PROV
    attribution.
  - `--dry-run` — print what would be written without making any changes.
  - `--force` — allow merging entities that are already superseded.
- **Example:** `amanuensis map entity merge e-aabb... e-ccdd... --canonical e-aabb... --reason "duplicate"`

### `map resolution show`

```
amanuensis map resolution show RESOLUTION_ID
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Prints one resolution record's raw YAML, then appends a
  "Supersede chain" block (all `ResolutionSupersede` records that
  reference this id) and a "Latest for triple" block showing whether
  this resolution is the currently active one for its
  `(source_id, atom_id, operand_index)` triple.
- **Notable flags:** none.
- **Example:** `amanuensis map resolution show j-9a2f...`

### `map resolution supersede`

```
amanuensis map resolution supersede OLD_ID --new-entity ENTITY_ID \
            --reason TEXT [--actor ID] [--confidence LEVEL] [--dry-run]
```

- **Classification:** mutating.
- **Idempotency:** one-shot on the active-triple constraint. The command
  validates that `OLD_ID` is the latest resolution for its triple; if it
  is already superseded the command fails cleanly. A successful run
  writes one new `Resolution` + one `ResolutionSupersede` + two
  `ProvenanceRecord` files.
- **Behavior:** Writes a new `Resolution` (`j-` prefix) inheriting the
  `(source_id, atom_id, operand_index)` triple from the old record but
  pointing at `--new-entity`, then writes a `ResolutionSupersede` (`s-`
  prefix) linking old → new. Acquires the workspace flock for the
  duration of the write.
- **Notable flags:**
  - `--new-entity ENTITY_ID` (required) — entity id the corrected
    resolution points at; must exist in `mappings/entities/`.
  - `--reason TEXT` (required) — reason text recorded in the
    `ResolutionSupersede`.
  - `--actor ID` (default: `cli`) — PROV attribution identifier.
  - `--confidence {high, medium, low}` (default: `high`) — confidence
    level for the new resolution.
  - `--dry-run` — print what would be written without making any changes.
- **Example:** `amanuensis map resolution supersede j-9a2f... --new-entity e-aabb... --reason "wrong entity"`

### `map vocabulary show`

```
amanuensis map vocabulary show [--archived ID]
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Prints the active entity-kind vocabulary snapshot at
  `mappings/entity-vocabulary-snapshot.yaml` to stdout. Fails with exit
  1 if no snapshot has been pinned yet (run `amanuensis map` first).
  With `--archived`, prints the archived snapshot identified by the
  16-hex-char id instead.
- **Notable flags:**
  - `--archived ID` — print an archived snapshot by its truncated
    SHA-256 id instead of the active one.
- **Example:** `amanuensis map vocabulary show`

### `map vocabulary snapshot`

```
amanuensis map vocabulary snapshot [--extend] [--template PATH] [--dry-run]
```

- **Classification:** mutating.
- **Idempotency:** without `--extend`, fails if a snapshot with
  different content already exists (protecting INV-12 pinning stability).
  With `--extend`, archives the current snapshot and writes a new one;
  each call advances the snapshot lineage.
- **Behavior:** Reads the entity-vocabulary YAML from `--template` (or
  the bundled generic template if not specified), validates it via
  `EntityVocabulary`, and writes it as the active snapshot at
  `mappings/entity-vocabulary-snapshot.yaml`. With `--extend`, archives
  the current snapshot first (under `mappings/archived-vocabulary/`).
  Acquires the workspace flock for the duration of the write.
- **Notable flags:**
  - `--extend` — archive the current snapshot and write the template as
    the new active snapshot (evolves the vocabulary lineage).
  - `--template PATH` — path to a custom entity-vocabulary YAML; defaults
    to the bundled `vocabularies/generic/entity-kinds.yaml`.
  - `--dry-run` — print what would happen without writing anything.
- **Example:** `amanuensis map vocabulary snapshot --extend --template my-entity-kinds.yaml`

### `map relation list`

```
amanuensis map relation list [--kind KIND] [--from-source ID] [--to-source ID] \
                             [--touching-source ID] [--shared-entity ID] [--limit N]
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Lists every Phase 2b `CrossDocRelation` in
  `mappings/relations/`, sorted lexicographically by id. Each line shows
  the relation id, kind, the directed endpoint pair (rendered in arrow
  form), the `from_source_id` / `to_source_id` pair, and the
  `shared_entities` count. Filters compose with AND semantics.
- **Notable flags:**
  - `--kind KIND` — filter to one of `supports` / `attacks` / `undercuts`;
    any other value is rejected with exit 2.
  - `--from-source ID` — filter to relations originating from this source.
  - `--to-source ID` — filter to relations terminating at this source.
  - `--touching-source ID` — filter to relations where the given source
    appears at either endpoint (union of `--from-source` and `--to-source`).
  - `--shared-entity ID` — filter to relations whose `shared_entities`
    list includes this entity id.
  - `--limit N` — render at most N relations (after filtering).
- **Example:** `amanuensis map relation list --kind supports --shared-entity e-1122...`

### `map relation show`

```
amanuensis map relation show RELATION_ID
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Prints one cross-doc relation's raw on-disk YAML (id,
  endpoints, kind, warrant, warrant_basis, warrant_defensibility,
  confidence, shared_entities, provenance_id), then appends a
  "Supersede chain" section walking the `CrossDocRelationSupersede`
  (`v-`) records both forward (`this -> X`) and backward (`Y -> this`),
  and a "Latest in chain" line. Fails with exit 1 if the id is not
  found in `mappings/relations/`.
- **Notable flags:** none.
- **Example:** `amanuensis map relation show x-3a9b12ff4c6d8e10`

### `map relation supersede`

```
amanuensis map relation supersede OLD_ID NEW_ID --reason TEXT [--actor ID] [--dry-run]
```

- **Classification:** mutating.
- **Idempotency:** one-shot on the active-relation constraint. Validates
  that `OLD_ID` is the latest in its chain; if it is already superseded
  the command fails cleanly. A successful run writes one new
  `CrossDocRelationSupersede` (`v-` prefix) plus its paired
  `ProvenanceRecord` to `mappings/supersedes/` and `mappings/provenance/`.
- **Behavior:** Writes a `CrossDocRelationSupersede` linking
  `OLD_ID -> NEW_ID`, plus a paired PROV record. Acquires the workspace
  flock for the duration of the write. Both `OLD_ID` and `NEW_ID` must
  already exist in `mappings/relations/`; the command never mutates the
  superseded record (INV-13).
- **Notable flags:**
  - `--reason TEXT` (required) — reason recorded in the supersede record.
  - `--actor ID` (default: `cli`) — identifier recorded in the PROV
    attribution.
  - `--dry-run` — print what would be written without making any changes.
- **Example:** `amanuensis map relation supersede x-3a9b... x-4b9d... --reason "warrant tightened"`

### `map probandum add`

```
amanuensis map probandum add STATEMENT --kind KIND --scheme SCHEME \
        [--alternative TEXT ...] [--confidence LEVEL] [--actor ID]
```

- **Classification:** mutating.
- **Idempotency:** content-addressable. Re-running with byte-identical
  arguments produces the same probandum id and is a no-op against the
  substrate. Different content produces a new id and a new on-disk
  record.
- **Behavior:** Writes a Phase 2c `Probandum` record (prefix `p-`) at
  `mappings/probanda/p-<hash>.md` plus a paired `ProvenanceRecord`
  under `mappings/provenance/`. Substrate's `add_probandum` enforces
  INV-18 (closed Walton-scheme vocabulary), the ACH-alternatives gate
  (non-empty `alternatives_considered` for `kind in {penultimate,
  interim}`), id discipline, and INV-13 immutability. Acquires the
  workspace flock for the duration of the write.
- **Notable flags:**
  - `--kind {ultimate, penultimate, interim}` (required) — tree
    position. `ultimate` is the root of the argument tree;
    `penultimate` anchors a sub-tree immediately above the evidence
    layer; `interim` is anywhere in between. `ultimate` and
    `penultimate` are supervisor-only — the Hierarchize role only
    proposes `interim`.
  - `--scheme SCHEME` (required) — Walton-scheme id. MUST appear in the
    pinned `mappings/walton-scheme-snapshot.yaml`; otherwise the
    command fails with exit 1 (INV-18 gate).
  - `--alternative TEXT` — competing hypothesis (repeatable). Required
    (at least once) for `--kind penultimate` and `--kind interim`
    (ACH-alternatives gate); rejected for `--kind ultimate` is
    acceptable (no gate triggers).
  - `--confidence {high, medium, low}` (default: `medium`).
  - `--actor ID` (default: `cli`) — identifier recorded in the PROV
    attribution.
- **Example (ultimate):**
  `amanuensis map probandum add "ACME prevails on its breach claim against Smith." --kind ultimate --scheme argument-from-evidence-to-hypothesis`
- **Example (penultimate):**
  `amanuensis map probandum add "Smith breached the 2018 contract." --kind penultimate --scheme argument-from-evidence-to-hypothesis --alternative "Smith and ACME mutually deferred the April 2024 delivery."`

### `map probandum list`

```
amanuensis map probandum list [--kind KIND] [--scheme SCHEME]
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Lists every probandum in `mappings/probanda/`, sorted
  lexicographically by id (the substrate's natural directory walk).
  Each line shows the probandum id, kind, scheme, and a truncated
  statement excerpt (first line of the statement, capped at 80 chars).
  Filters compose with AND semantics.
- **Notable flags:**
  - `--kind {ultimate, penultimate, interim}` — filter to probanda of
    the given kind. Other values rejected with exit 2.
  - `--scheme SCHEME` — filter to probanda using the given
    Walton-scheme id. No closed-vocab check on the filter itself —
    unknown scheme yields an empty list, not an error.
- **Example:** `amanuensis map probandum list --kind interim`

### `map probandum show`

```
amanuensis map probandum show PROBANDUM_ID
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Prints one probandum's on-disk content (YAML
  frontmatter + statement body), then appends sections for
  alternatives considered (one per line), confidence, lineage
  (incoming probandum-edges and outgoing edges), provenance id, and
  the supersede chain (forward + back). A "Latest in chain" line
  closes the output. Fails with exit 1 if the id is not found in
  `mappings/probanda/`.
- **Notable flags:** none.
- **Example:** `amanuensis map probandum show p-3a9b12ff4c6d8e10`

### `map probandum lineage`

```
amanuensis map probandum lineage PROBANDUM_ID
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Renders the lineage tree for a focal probandum. The
  output has two sections:

  1. **Lineage (upward to ultimate)** — walks INCOMING probandum-edges
     from the focal node up to the ultimate, root-first (root at the
     top, focal node at the bottom marked with `* `). Depth-capped at
     100 (defensive; matches the substrate's INV-17 walk cap).
  2. **Lineage (downward to leaves)** — DFS over outgoing edges from
     the focal node, indented to show parent / child relationships,
     terminating at atoms / cross-doc relations or at probanda with no
     outgoing edges. Cycles (which INV-16 should make impossible) are
     fenced by a visited-set guard that prints `(<id> already
     visited)`.

  Fails with exit 1 if the id is not found in `mappings/probanda/`.
- **Notable flags:** none.
- **Example:** `amanuensis map probandum lineage p-pen-smith-breach`

### `map probandum link`

```
amanuensis map probandum link PARENT_ID CHILD_ID --kind KIND \
        --warrant TEXT --warrant-basis TEXT \
        [--warrant-defensibility LEVEL] [--confidence LEVEL] \
        [--child-source-id ID] [--actor ID]
```

- **Classification:** mutating.
- **Idempotency:** content-addressable. Re-running with byte-identical
  arguments produces the same edge id and is a no-op against the
  substrate.
- **Behavior:** Writes a Phase 2c `ProbandumEdge` record (prefix `q-`)
  at `mappings/probandum-edges/q-<hash>.yaml` plus a paired
  `ProvenanceRecord`. The child kind is dispatched from the
  `CHILD_ID` prefix: `p-` → probandum child, `a-` → atom child
  (requires `--child-source-id`), `x-` → cross-doc-relation child.
  Substrate's `add_probandum_edge` enforces parent / child existence,
  INV-16 (tree-shape + acyclic), INV-17 (lineage reaches an
  ultimate), id discipline, and INV-13 immutability. Acquires the
  workspace flock for the duration of the write.
- **Notable flags:**
  - `--kind {supports, attacks, undercuts}` (required) — edge kind.
  - `--warrant TEXT` (required) — the warrant that licenses the
    inference (one paragraph conventional).
  - `--warrant-basis TEXT` (required) — basis grounding the warrant
    (citation, methodology, etc.).
  - `--warrant-defensibility {literature-backed, methodology-derived, conventional, contested}`
    (default: `conventional`).
  - `--confidence {high, medium, low}` (default: `medium`).
  - `--child-source-id ID` — required when `CHILD_ID` starts with `a-`
    (atom children carry a source id); rejected for `p-` or `x-`
    children. Mismatches fail at the schema layer with exit 1.
  - `--actor ID` (default: `cli`) — identifier recorded in the PROV
    attribution.
- **Example (probandum-to-atom):**
  `amanuensis map probandum link p-pen-smith-breach a-acme-001 --kind supports --warrant "..." --warrant-basis "Direct attestation" --child-source-id src-acme-brief`
- **Example (probandum-to-probandum):**
  `amanuensis map probandum link p-ult-acme-prevails p-pen-smith-breach --kind supports --warrant "..." --warrant-basis "Contract law mapping"`

### `map probandum supersede`

```
amanuensis map probandum supersede OLD_ID NEW_ID --reason TEXT [--actor ID]
```

- **Classification:** mutating.
- **Idempotency:** one-shot on the active-chain constraint. Validates
  that `OLD_ID` is the latest in its chain; if it is already
  superseded the command fails cleanly. A successful run writes one
  new `ProbandumSupersede` (`u-` prefix) plus its paired
  `ProvenanceRecord` to `mappings/supersedes/` and
  `mappings/provenance/`.
- **Behavior:** Writes a `ProbandumSupersede` linking
  `OLD_ID -> NEW_ID`, plus a paired PROV record. Acquires the
  workspace flock for the duration of the write. Both `OLD_ID` and
  `NEW_ID` must already exist in `mappings/probanda/`; the command
  never mutates the superseded record (INV-13).
- **Notable flags:**
  - `--reason TEXT` (required) — reason recorded in the supersede
    record.
  - `--actor ID` (default: `cli`) — identifier recorded in the PROV
    attribution.
- **Example:** `amanuensis map probandum supersede p-3a9b... p-4b9d... --reason "rescoped to fact-finding only"`

### `map probandum-edge supersede`

```
amanuensis map probandum-edge supersede OLD_ID NEW_ID --reason TEXT [--actor ID]
```

- **Classification:** mutating.
- **Idempotency:** one-shot on the active-chain constraint. Mirrors
  `map probandum supersede` for edge-level supersedes.
- **Behavior:** Writes a `ProbandumEdgeSupersede` (`o-` prefix)
  linking `OLD_ID -> NEW_ID` in `mappings/supersedes/`, plus a paired
  PROV record. Acquires the workspace flock for the duration of the
  write. Both `OLD_ID` and `NEW_ID` must already exist in
  `mappings/probandum-edges/`. Superseded edges are excluded from
  INV-16 (tree) and INV-17 (lineage) walks (they represent retracted
  state).
- **Notable flags:**
  - `--reason TEXT` (required) — reason recorded in the supersede.
  - `--actor ID` (default: `cli`) — identifier recorded in the PROV
    attribution.
- **Example:** `amanuensis map probandum-edge supersede q-aabb... q-ccdd... --reason "warrant tightened, defensibility upgraded"`

### `map walton-scheme show`

```
amanuensis map walton-scheme show
```

- **Classification:** read-only.
- **Idempotency:** re-running on the same substrate state produces
  identical output and no state changes.
- **Behavior:** Prints the active Walton-scheme snapshot at
  `mappings/walton-scheme-snapshot.yaml` to stdout. Fails with exit 1
  if no snapshot has been pinned yet (run
  `amanuensis map walton-scheme snapshot` first). No flock acquired.
- **Notable flags:** none.
- **Example:** `amanuensis map walton-scheme show`

### `map walton-scheme snapshot`

```
amanuensis map walton-scheme snapshot [--extend]
```

- **Classification:** mutating.
- **Idempotency:** without `--extend`, idempotent for byte-identical
  content. Fails with exit 1 if a snapshot with different content
  already exists (protecting INV-18 pinning stability). With
  `--extend`, archives the current snapshot under
  `mappings/walton-scheme-archive/<sha16>.yaml` and writes the bundled
  catalogue as the new active snapshot; each `--extend` call advances
  the snapshot lineage.
- **Behavior:** Pins the Walton-scheme registry into the workspace.
  Without `--extend`, copies the bundled generic catalogue at
  `vocabularies/generic/walton-schemes.yaml` to
  `mappings/walton-scheme-snapshot.yaml`. With `--extend`, archives
  the current snapshot first, then writes the bundled catalogue as
  the new active snapshot. Acquires the workspace flock for the
  duration of the write. The substrate caches the loaded registry
  per-instance; the cache is invalidated on every snapshot call.
- **Notable flags:**
  - `--extend` — archive the current snapshot and write the bundled
    catalogue as the new active snapshot (evolves the Walton-scheme
    lineage).
- **Example:** `amanuensis map walton-scheme snapshot`
- **Example (extend):** `amanuensis map walton-scheme snapshot --extend`

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Command body error (validator failure, missing atom, missing snapshot, ingest failure, etc.). |
| `2` | Preflight / usage failure — most often the INV-1 marker check (`amanuensis.yaml` missing) or an unknown enum value rejected by Typer before the command body runs. |

## Known Limitations

- **`install-skills` is a stub.** It detects installed harness CLIs and
  reports the install location but writes no skill files. A future
  milestone re-classifies the command as mutating once the production
  install path lands.
- **No interactive shell completion.** Typer would support shell
  completion installation; it is not wired in Phase 1.
- **No `--quiet` / `--verbose` flags.** Read-only commands emit a fixed
  amount of stdout; mutating commands print one summary line. Verbosity
  control is a Phase 2 candidate.
- **`atom validate` does not invoke the `lineage_closure` validator.**
  That validator operates over relations, not atoms; relation-level
  validation gets its own CLI surface once relation ingest is wired.
- **No `redact` command.** Redaction-aware ingest is out of scope for
  Phase 1 (acknowledged); see
  [`architecture.md`](./architecture.md#known-limitations).

## See also

- [`architecture.md`](./architecture.md) — system architecture, the
  three surfaces, the determinism boundary, module decomposition.
- [`schema-reference.md`](./schema-reference.md) — per-record schemas
  for every CLI input and output.
- [`supervision-protocol.md`](./supervision-protocol.md) — how the CLI
  commands compose into a supervised end-to-end run.
- [`../INVARIANTS.md`](../INVARIANTS.md) — the invariants charter
  (INV-1 marker, INV-4 determinism boundary, INV-10 vocabulary
  pinning, INV-16/17/18 Phase 2c probandum-tree gates).
