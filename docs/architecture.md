# Architecture

amanuensis is an agent-consumable workspace for document distillation,
mapping, and grounded extension toward legal-quality submissions. This
document is the architectural reference for the project at the level a
new contributor (human or agent) needs before reading code. The
authoritative plan lives at
`~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29.md`;
the on-disk schemas are documented in [`schema-reference.md`](./schema-reference.md);
the invariants this architecture rests on are in
[`../INVARIANTS.md`](../INVARIANTS.md).

---

## Purpose

amanuensis makes document distillation auditable. The product, in
operation, is a **filesystem tree** at a workspace root marked by
[`amanuensis.yaml`](../amanuensis.yaml). Every artifact in that tree —
every atom, relation, clarification, iteration directive, provenance
record — is a Pydantic-validated record persisted as YAML or markdown
with frontmatter, named by a content-addressable hash of its canonical
form. Every non-deterministic action (LLM call, human judgment) crosses
a single named boundary that records what happened, who did it, and what
its inputs and outputs were.

The system has three readers:

- **Agents** read and write the substrate directly. Skills loaded JIT by
  each harness (Claude Code, Codex, Gemini CLI, Cursor Agent) act on the
  tree. There is no API in front of them.
- **The supervisor** reads the substrate through a live web app (`amanuensis
  serve`) and writes back through forms whose handlers are the same
  Python functions the CLI exposes.
- **External consumers** receive a self-contained static HTML bundle
  (`amanuensis export`) built deterministically from the substrate.

Each is a pure function (or near-pure: the live app accepts supervisor
input) over substrate state. The substrate is the truth; everything
else is a view of it.

---

## Substrate-as-truth (INV-8)

The substrate is the **source of truth** ([INV-8](../INVARIANTS.md#inv-8--substrate-is-the-source-of-truth)).
All renderings are deterministic functions of substrate state. No web
session, no SQLite cache, no in-process registry holds state that the
substrate doesn't also hold. Caches exist only as content-addressable
acceleration; they are rebuildable from the substrate and never
authoritative.

Concretely, this means:

- **Git-friendly.** The tree is YAML and markdown. Diffs are reviewable;
  history is meaningful. Substrate hygiene is filesystem hygiene.
- **JIT-loadable by agents.** No schema server, no session, no daemon.
  An agent in a fresh harness session can `ls`, `cat`, and `find` its way
  through the tree without bootstrapping.
- **Survives the loss of any cache or DB.** Delete `cache/`, `dispatch/`,
  any rendered HTML — the substrate reconstitutes them. Lose the
  substrate and nothing else helps.
- **Writes are atomic.** Every write is `write-to-tmp-then-rename`
  (M1.6 `atomic_write_text`, POSIX `os.replace`). Readers see either the
  previous version of a file or the new one, never a torn write.
- **Reads are lock-free.** No reader takes the workspace flock; atomic
  writes are sufficient to make concurrent reads safe.

The mechanism that enforces all of this lives in `amanuensis.fs` (see
[Module decomposition](#module-decomposition) below). Every `add_*`
method on `Substrate` asserts `model.id == compute_id(model)` before
writing, so "the path you read from is the hash of what you read" is
trivially true.

---

## Three surfaces

amanuensis is a three-surface system. The substrate is the first
surface; the other two are views of it.

### Surface 1 — The substrate

The workspace itself. A directory marked by `amanuensis.yaml` containing:

- `distillations/<source-id>/` — one directory per distilled source
  (atoms, relations, source mirror, provenance, clarifications, replay
  log, vocabulary snapshot)
- `iterations/` — workspace-level supervisor-authored directives
- `delivery/` — Phase 4 sign-off gate (stub in Phase 1)
- `dispatch/{queue,outputs,failures}/` — multi-agent dispatch protocol
- `cache/` — content-addressable LLM-call cache

Layout details are in [Substrate layout](#substrate-layout) below;
file-by-file schema details are in [`schema-reference.md`](./schema-reference.md).

The substrate is the only surface that agents write to. Skills load JIT
inside each harness; they read paragraphs from `source-mirror/`, write
candidate atoms to `dispatch/outputs/`, and emit clarifications when
they hit ambiguity. Agents do not call a Python API — they read and
write files.

### Surface 2 — The live web app (`amanuensis serve` — M8.x)

A FastAPI + Jinja2 + HTMX application that boots against a workspace
and renders the substrate. The pages are listed in plan §8; the salient
properties:

- **Read-only by default.** All `GET` endpoints render directly from
  substrate state with no side effects. `Cache-Control: no-store` on
  substrate-derived responses.
- **Mutations go through the workspace flock.** `POST` endpoints
  (resolve clarification, add iteration directive) call the same Python
  function the CLI command calls; they acquire `acquire_workspace_lock`
  for the duration of the substrate write and release on completion. A
  5-second timeout produces a clear user-facing error if `distill` or
  `dispatch` is in flight.
- **HTML fragments, not JSON APIs.** HTMX swaps under `/fragments/`
  return HTML. The relation graph is Cytoscape.js with an Alpine.js
  binding that updates the graph data block without re-mounting the
  canvas.
- **Localhost-only by default.** Single supervisor in Phase 1; no
  multi-user concurrency.

The web app is the supervisor's instrument. It exposes the substrate
state and provides the affordances (resolve, iterate) that mutate it,
but it carries no state the substrate doesn't carry.

### Surface 3 — The static export (`amanuensis export` — M9.x)

A self-contained HTML bundle built from substrate state. Phase 1 ships a
smoke-test version (one HTML file with all atoms for a source); Phase 4
ships the full audit-HTML bundle that is the delivery gate.

The export is a pure function: same substrate → same bytes. INV-8's
render-purity test (M9.x) asserts this.

---

## Determinism boundary (INV-4)

The system's correctness rests on a small, named boundary between
deterministic and non-deterministic action.

**Deterministic side.** Path resolution, schema validation, content
addressing, file IO, vocabulary lookup, validator gates, replay-log
sequencing, render pipelines. Pure functions over substrate state. Same
substrate state, same code → same output, byte-identical.

**Non-deterministic side.** LLM calls and human judgments. These are
permitted **only at named events** ([INV-4](../INVARIANTS.md#inv-4--determinism-boundary-is-named-gated-and-audited)).
Each event has:

| Field | Source |
|---|---|
| input content hash | computed by the cached-call wrapper |
| output content hash | computed after the call returns |
| role attribution | `AgentAttribution` (kind, identifier, role) |
| model id (for LLM events) | `AgentAttribution.identifier` |
| timestamp | `AwareDatetime`, ISO-8601 UTC |
| deterministic validation gate | the Auditor + schema gates |

The LLM-call wrapper (`amanuensis.llm.cached_call`, M5.x) is the
mechanism:

1. Compute `inputs_hash` from `(role, prompt, normalized_inputs)`.
2. Look up `cache/<inputs_hash>.yaml`. On hit, replay byte-identically;
   write a `ReplayLogEntry` with `cache_hit=true`.
3. On miss, write a `dispatch/queue/<role>-<seq>.yaml` entry; the
   dispatch driver (M6.x) executes the harness CLI; capture the output;
   compute `outputs_hash`; persist to `cache/`.
4. Run the deterministic validation gate (Auditor, schema, citation
   ledger, scale anchor, closed vocabulary). Output that fails the gate
   is **rejected before it enters the substrate**.
5. Write a `ReplayLogEntry` with the four-tuple `(actor, activity,
   inputs_hash, outputs_hash)` plus duration and substrate changes.
6. Write a `ProvenanceRecord` (W3C PROV-O subset) tying the produced
   artifact to the activity, the actor, and the inputs.

The wrapper is a single function. Every LLM call goes through it; the
INV-4 gate test (M5.3 / M4.4) walks the substrate and verifies. Mutating
CLI commands are idempotent against a fixed substrate state; read-only
commands produce byte-identical substrate state when run twice on the
same input (no replay-log delta, no cache delta).

---

## Harness-aware module: dispatch

amanuensis is harness-agnostic at every layer except one: the **dispatch
driver** (`amanuensis.dispatch`, M6.x).

Every other module — schemas, fs, validators, ingest, llm, web, export,
cli — operates on substrate paths and Pydantic models. None of them
know whether the agent that produced an atom was Claude Code, Codex, or
Cursor Agent. The substrate carries the model id in `AgentAttribution`,
but no module branches on it.

The dispatch driver is where harness names appear. It:

- Detects installed harness CLIs (`claude`, `codex`, `gemini`,
  `cursor-agent`) via `which`.
- Reads `dispatch/queue/<role>-<seq>.yaml` files.
- Invokes the appropriate harness CLI per-role (the assignment table is
  configurable per project; defaults in plan §M6).
- Captures stdout/stderr/exit code and writes
  `dispatch/outputs/<role>-<seq>.yaml`.
- On retry exhaustion, writes `dispatch/failures/<role>-<seq>.yaml`.

The driver runs as its own process with its own context budget, by
design — a `claude -p` invocation cannot safely recursively spawn
`claude -p` sub-agents (fork-bomb risk), and the orchestrator skill
running inside an interactive session would otherwise need to take that
risk. The separation is in plan §9.

Role skills (`amanuensis:distill`, `amanuensis:distill:extract`,
`amanuensis:distill:audit`, plus the Phase 1.5 stubs `:contrarian`,
`:constructive`, `:premortem`) are markdown files bundled with the
package. `amanuensis install-skills` (M4.3) detects installed harnesses
and writes/symlinks skill files into the appropriate per-harness skill
directory (`~/.claude/skills/`, `~/.codex/skills/`, etc.). Stub skills
set `stub: true` in their frontmatter and refuse to dispatch; the
orchestrator skips them cleanly during reconciliation.

Phase 1 launches with **Extractor + Auditor active**; the other three
role bodies land in Phase 1.5.

---

## Substrate layout

This is a summary; the authoritative per-file schema is in
[`schema-reference.md`](./schema-reference.md#filesystem-layout) and the
plan source is §5.

```text
<workspace>/
  amanuensis.yaml                            (project marker — INV-1)
  HISTORY.md / TASKS.md / INVARIANTS.md      (project tracking, not substrate)
  pyproject.toml / .gitignore / ...          (project skeleton, not substrate)
  docs/                                      (human-facing documentation)

  distillations/<source-id>/                 (one directory per distilled source)
    README.md                                (auto-generated index)
    source-mirror/
      manifest.yaml                          (source file hash, ingest activity, paragraph count)
      paragraphs/p-<NNNN>.md                 (one file per paragraph)
      sections/                              (section hierarchy index)
    vocabulary-snapshot.yaml                 (per-distillation snapshot — INV-10)
    atoms/a-<hash>.md                        (frontmatter + narrative)
    relations/r-<hash>.yaml                  (pure YAML; no narrative body)
    provenance/<prov-id>.yaml                (one per provenance record)
    clarifications/
      open/c-<hash>.md                       (frontmatter + question body)
      resolved/c-<hash>.md                   (same id; resolution fields populated)
    replay-log/
      .next-seq                              (monotonic counter; flock-serialized)
      <yyyy-mm-dd>/<seq:012d>.yaml           (one entry per activity)

  iterations/i-<hash>.md                     (workspace-level, supervisor-authored)

  delivery/sign-off.yaml                     (Phase 4 gate; stub in Phase 1)

  dispatch/
    queue/<role>-<seq>.yaml                  (orchestrator writes; driver reads + deletes on success)
    outputs/<role>-<seq>.yaml                (driver writes after harness returns)
    failures/<role>-<seq>.yaml               (driver writes on retry exhaustion)

  cache/<input-hash>.yaml                    (LLM-call cache; content-addressable)

  mappings/                                  (Phase 2a cross-document artifacts — INV-12)
    entity-vocabulary-snapshot.yaml          (active entity-kind registry; pinned by `amanuensis map`)
    entity-vocabulary-archive/<hash>.yaml    (prior snapshots; written by `map vocabulary snapshot --extend`)
    entities/e-<hash>.md                     (canonical Entity records; frontmatter + notes body)
    resolutions/j-<hash>.yaml                (Resolution records; pure YAML)
    supersedes/t-<hash>.yaml                 (EntitySupersede records)
    supersedes/s-<hash>.yaml                 (ResolutionSupersede records)
    provenance/<prov-id>.yaml                (PROV-O records for mapping-phase artifacts)
    replay-log/                              (mappings-scoped replay log)
```

A few non-obvious points worth calling out here (full discussion in
`schema-reference.md`):

- **Provenance filenames key on `prov-id`, not `entity_id`.** A
  Clarification's raised + resolved provenance records share an
  `entity_id` (the clarification's id); using `entity_id` as filename
  would collide. Inverse lookup is the `entity_id` field on the record.
- **Replay-log day directories are for human navigation only.** `seq`
  is unique across the entire log, not per-day. Filenames are
  zero-padded width-12 so lexicographic sort within a day equals seq
  order.
- **Vocabulary snapshot at distillation root.**
  `distillations/<source-id>/vocabulary-snapshot.yaml` is the per-
  distillation closed-vocabulary registry. All validators read this
  snapshot, never the global `~/.amanuensis/vocabularies/` registry
  ([INV-10](../INVARIANTS.md#inv-10--vocabulary-is-pinned-per-distillation)).
- **`README.md` only inside `distillations/<source-id>/` subtrees.**
  The workspace root does NOT have a `README.md`; that would violate
  [INV-2](../INVARIANTS.md#inv-2--no-harness-specific-files-at-project-root).

---

## Concurrency model

The substrate is a shared mutable resource. The discipline:

| Operation | Lock acquired? | Mechanism |
|---|---|---|
| Mutating CLI command (`init`, `ingest`, `distill`, `dispatch`, `clarification resolve`, `iteration add`, `vocabulary snapshot`) | Yes | `acquire_workspace_lock(workspace_root, timeout=5.0)` (M1.8) |
| Mutating map CLI command (`map` orchestrator, `map entity merge`, `map resolution supersede`, `map vocabulary snapshot`) | Yes | Same flock, 5s timeout |
| Web POST endpoint (resolve clarification, add iteration) | Yes | Same flock, 5s timeout, per-request |
| Replay-log `seq` increment | Yes | Workspace flock held during atomic increment of `.next-seq` (M1.7) |
| Read-only CLI command (`status`, `atom list`, `atom validate`, `clarification show`, `vocabulary show`, `export`) | No | Atomic-write-then-rename makes reads snapshot-safe |
| Read-only map CLI command (`map status`, `map entity list`, `map entity show`, `map resolution show`, `map vocabulary show`) | No | Same |
| Web `GET` endpoints | No | Same |
| Cache write (`cache/<input-hash>.yaml`) | No | Idempotent by content addressing |

The lock is `fcntl.flock` on `<workspace>/.amanuensis-lock`. POSIX-only
(see [Known Limitations](#known-limitations)). The lock module
refuses to flock a directory that lacks the `amanuensis.yaml` marker —
defense-in-depth on INV-1 so a caller can't accidentally flock the
wrong tree.

Crash semantics:

- The flock is released by POSIX fd-table teardown on process exit
  (`SIGKILL`, `os._exit`, segfault). Verified by an explicit
  spawn-child SIGKILL test.
- Replay-log entries write the entry file via `atomic_write_text`
  BEFORE incrementing the counter. A crash between those two steps
  leaves the counter at N and the next writer overwrites the orphan
  entry at seq N — gap-free and duplicate-free on retry. A cross-day
  orphan scan inside the held flock handles the rare midnight-UTC
  edge case (see HISTORY.md for the bug entry).
- Atomic writes (`write-to-tmp-then-rename`) guarantee no partial
  reads. A crash between tmp write and rename leaves a `.tmp.*`
  sibling; `Substrate.list_*` skips them.

---

## Module decomposition

The Python package is `amanuensis`; each subpackage has one job and a
narrow public surface. Cross-module dependencies are a DAG; no cycles.

| Module | Purpose | Depends on | Public surface |
|---|---|---|---|
| `amanuensis.schemas` | Canonical Pydantic models + content-addressable hashing | (leaf) | Sixteen model classes; `compute_id` |
| `amanuensis.schemas.entity` | `Entity` — canonical cross-document entity | `schemas._shared` | `Entity` |
| `amanuensis.schemas.resolution` | `Resolution` — entity-id join for one operand-ref triple | `schemas._shared` | `Resolution` |
| `amanuensis.schemas.entity_supersede` | `EntitySupersede` — correction record for entity merges/renames | `schemas._shared` | `EntitySupersede` |
| `amanuensis.schemas.resolution_supersede` | `ResolutionSupersede` — correction record for resolution updates | `schemas._shared` | `ResolutionSupersede` |
| `amanuensis.fs` | Substrate filesystem (path conventions, atomic writes, workspace lock, replay log) | `schemas` | `Substrate`, `acquire_workspace_lock`, `ReplayLog`, typed errors |
| `amanuensis.ingest` (M3.x) | Document → paragraph-indexed source mirror | `schemas`, `fs` | `ingest(pdf_path, source_id) -> SourceMirror` |
| `amanuensis.vocabulary` (M2.x) | Closed predicate vocabulary registry + per-distillation snapshot loader | `schemas`, `fs` | `Vocabulary(snapshot_path).contains(predicate) -> bool` |
| `amanuensis.vocabulary.entity_registry` | `EntityVocabulary` loader + snapshot semantics for mapping-phase kind registry | `schemas`, `fs` | `load_entity_vocabulary(path) -> EntityVocabulary`; snapshot pinning helpers |
| `amanuensis.validators` (M2.x) | Pure-function validation gates | `schemas`, `fs`, `vocabulary` | `validate_atom(atom, substrate) -> ValidationResult`, one function per gate |
| `amanuensis.validators.entity_kind_in_vocabulary` | Closed-vocabulary gate: rejects entities whose `kind` is absent from the active entity snapshot | `schemas`, `vocabulary.entity_registry` | `entity_kind_in_vocabulary(entity, substrate) -> ValidationResult` |
| `amanuensis.llm` (M5.x) | LLM-call wrapper: cache + replay log + PROV-O record | `schemas`, `fs` | `cached_call(role, prompt, inputs) -> (output, provenance_record)` |
| `amanuensis.dispatch` (M6.x) | Multi-agent queue / driver. **The only harness-aware module.** | `schemas`, `fs`, `llm` | `Dispatch(workspace).enqueue(role, prompt, inputs)`; `driver.run()` |
| `amanuensis.dispatch.reconcile` | Reconciliation gate — merges role outputs into the substrate | `schemas`, `fs`, `validators` | `reconcile(workspace)`; Phase 2a: imports `_build_entity`, `_build_resolution` |
| `amanuensis.skills` (M4.x) | Skill content (markdown files; bundled with package) | (none) | Files installed to harness skill directories |
| `amanuensis.cli` (M4.x) | Typer command surface | All of the above | `amanuensis` console script |
| `amanuensis.cli.map` | `amanuensis map ...` sub-app (9 verbs; Phase 2a) | `schemas`, `fs`, `vocabulary.entity_registry` | `map`, `map status`, `map entity {list,show,merge}`, `map resolution {show,supersede}`, `map vocabulary {show,snapshot}` |
| `amanuensis.web` (M8.x) | FastAPI + HTMX + Cytoscape supervision UI | `schemas`, `fs`, `validators` | `amanuensis serve` |
| `amanuensis.web.routes.entities` | Read-only entity browser routes | `schemas`, `fs` | `GET /entities`, `GET /entities/<id>` |
| `amanuensis.web.routes.resolutions` | Read-only resolution browser routes | `schemas`, `fs` | `GET /resolutions`, `GET /resolutions/<id>` |
| `amanuensis.export` (M9.x) | Static HTML export (Phase 1 stub; Phase 4 production) | `schemas`, `fs`, `web` (renderer reuse) | `amanuensis export` |

Phase 1 status as of M1.9: `schemas` and `fs` are complete. The
remaining modules are scheduled in M2–M9. Phase 2a (Resolve) added
`schemas.entity`, `schemas.resolution`, `schemas.entity_supersede`,
`schemas.resolution_supersede`, `vocabulary.entity_registry`,
`validators.entity_kind_in_vocabulary`, `cli.map`, and
`web.routes.entities`/`web.routes.resolutions`.

---

## Known Limitations

Phase 1 deliberate scope cuts, not bugs. The list mirrors the
"acknowledged" items in the project's synthesis records
(`synthesis/distillation-pipeline-architecture-2026-05-28.md` and
`synthesis/verified-deliverable-workflow-architecture-2026-05-28.md`).

- **Single document per distillation.** Multi-document reasoning
  (entity resolution across sources, cross-document support/attack
  edges) is Phase 2 (Map). See
  [INV-9](../INVARIANTS.md#inv-9--cross-document-reasoning-is-phase-2s-job-not-phase-1s).
- **Single supervisor.** No multi-user concurrency; the live web app is
  localhost-only. Multi-supervisor coordination (identity-aware audit,
  conflict resolution beyond the workspace flock's mutual exclusion) is
  a Phase 4 candidate.
- **No redaction-aware ingestion.** The source-mirror captures every
  paragraph including sensitive text. Filing the source PDF safely is
  the supervisor's responsibility. Redaction support is a Phase 2
  candidate.
- **In-process LLM SDK invocation is out of scope.** The dispatch
  driver invokes harness CLIs (`claude`, `codex`, `cursor-agent`,
  `gemini`) as subprocesses; the subprocess boundary is what makes the
  write-isolation contract enforceable. Calling an `anthropic` /
  `openai` client library directly is not supported in Phase 1.
- **Iteration directive consumption is not yet automated.** Directives
  are written with full PROV but the distill orchestrator does not yet
  read pending directives on the next run. The supervisor must adjust
  the next `amanuensis distill` invocation manually until a later
  milestone wires consumption. See
  [`supervision-protocol.md`](./supervision-protocol.md#3-iteration-directives).
- **`amanuensis export` is a Phase-1 stub.** A single self-contained
  HTML file is the entire delivery surface in Phase 1 (M9.1); the full
  audit-HTML bundle, prose-report rendering, and render-time policy
  gates are Phase 4.
- **Cross-document reasoning is Phase 2's job.** Phase 1 emits
  intra-document relations only; cross-document support/attack edges,
  shared entity graphs, and probandum hierarchies spanning sources are
  Phase 2 (Map) outputs.
- **POSIX-only.** The workspace flock uses `fcntl.flock`. Windows
  support is out of scope for Phase 1.
- **Python 3.12+ but `<3.14`.** Python 3.14's `site.py` change skips
  `.pth` files whose stem starts with `_`, which breaks hatchling's
  editable install (`_editable_impl_amanuensis.pth`). Pinned in
  `pyproject.toml`'s `requires-python` until hatchling ships a
  non-underscore-prefixed editable shim. See HISTORY.md for the bug
  entry.
- **Replay-log read APIs have a microsecond-scale inconsistency
  window** during cross-day orphan recovery (documented in
  `src/amanuensis/fs/replay_log.py`). Negligible for Phase 1 substrate
  sizes.
- **`ReplayLog.get_entry(seq)` is O(num_days).** Scans each day
  directory in turn. Acceptable for Phase 1 corpora; an index file is
  a candidate optimization.
- **Generic vocabulary only.** Phase 1 ships a single generic
  vocabulary at `~/.amanuensis/vocabularies/generic/`. Domain-specific
  vocabularies (forensic-crypto, contract-review) are per-engagement
  bootstrap.
  [INV-10](../INVARIANTS.md#inv-10--vocabulary-is-pinned-per-distillation)
  ensures per-distillation pinning regardless of which vocabulary is
  active at ingest.
- **Three role stubs.** Contrarian / Constructive / Premortem skills
  exist as stubs (`stub: true` in frontmatter); the orchestrator skips
  them. Only Extractor + Auditor run in Phase 1. See
  [`skill-author-guide.md`](./skill-author-guide.md#the-stub-mechanism).
- **Cytoscape graph soft cap of ~750 atoms / 2000 edges.** Above the
  cap, the relation graph falls back to a "view by section" mode where
  the supervisor selects a section path and the graph renders scoped
  to that section (plan §8). Documented as a known limit; full-graph
  virtualization is a Phase 1.5 candidate.

---

## See also

- [`cli-reference.md`](./cli-reference.md) — per-command reference for
  the `amanuensis` console script (init / ingest / status / atom /
  clarification / iteration / vocabulary / install-skills / map).
- [`schema-reference.md`](./schema-reference.md) — per-model field
  documentation, canonical-form rules, content-addressable id
  algorithm, INVARIANTS enforcement points.
- [`skill-author-guide.md`](./skill-author-guide.md) — skill file
  format, dispatch queue protocol, write-isolation contract.
- [`supervision-protocol.md`](./supervision-protocol.md) — the four
  supervision surfaces (checkpoints, clarifications, iteration
  directives, delivery gate) and the canonical end-to-end run.
- [`../INVARIANTS.md`](../INVARIANTS.md) — the invariants charter
  (INV-1 through INV-14).
- [`../amanuensis.yaml`](../amanuensis.yaml) — the project marker and
  posture configuration.
- `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29.md` —
  the authoritative Phase 1 plan; sections §1 (goal/scope), §3
  (architecture), §4 (schema), §5 (filesystem layout), §11
  (invariant gate tests) are the source material for this document.
- `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29-tasks.md` —
  the 56-task implementation breakdown.
