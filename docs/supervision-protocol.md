# Supervision Protocol

## Audience and scope

This guide is for a human supervisor running a real distillation
engagement on amanuensis. It assumes you have already read
[`cli-reference.md`](./cli-reference.md) (the full CLI surface,
including Phase 2a `amanuensis map` sub-app)
and [`skill-author-guide.md`](./skill-author-guide.md) (the role
contracts and dispatch queue protocol). In scope: the four supervision
surfaces the system exposes, how they wire to the local web app, and a
canonical end-to-end run for a single legal-pleading PDF. Out of scope:
the operational LLM mechanics — when an Extractor or Auditor body
needs revision, see `skill-author-guide.md`.

## The four supervision surfaces

Supervision in amanuensis is structured around four named surfaces.
Each surface has a CLI form and (with one Phase 1 exception) a web
form. Both forms acquire the same workspace flock, so concurrent
supervisor + dispatch operations serialize cleanly.

### 1. Checkpoints

A checkpoint is an opportunity to inspect substrate state before
continuing. The primary checkpoint is the **reconcile gate** (M7.4):
after a dispatch cycle deposits role outputs under
`dispatch/outputs/`, `amanuensis reconcile` walks each Auditor verdict
and commits or rejects per-atom against the substrate. Accepted atoms
merge; rejected atoms do not; contested-warrant rejections auto-raise
a clarification (CR-7).

The standard supervisor rhythm is:

```
amanuensis distill <source-id>
amanuensis dispatch --once
amanuensis reconcile
amanuensis status
```

`amanuensis status` (read-only) is the human-facing checkpoint readout
between cycles — per-distillation counts of paragraphs, atoms,
relations, and open/resolved clarifications. With `--json` the output
is stable-sorted for diff-friendly comparison between checkpoints.

### 2. Clarifications (interactive vs filesystem)

A clarification is raised when (a) an atom fails validation, (b) a
relation's warrant is flagged `warrant_defensibility: contested` by
the Auditor (CR-7), (c) the Map Auditor encounters an ambiguous or
disputed entity resolution, or (d) the Phase 2c reconciler hits a
lineage gap or an unknown Walton scheme. The clarification kinds in
use are:

| Kind | Raised by | Trigger |
| --- | --- | --- |
| `warrant-defensibility-contested` | Auditor (distill phase) | A rejection carries `warrant_defensibility: contested`. |
| `resolution-ambiguous` | Map Auditor (map phase) | Two equally-good entity matches, or an entity kind that is `supervisor-only` in the vocabulary snapshot. |
| `resolution-disputed` | Map Auditor (map phase) | A supersede proposal targets a resolution whose PROV `was_attributed_to.kind == "human"`. Never auto-accepted. |
| `lineage-incomplete` | Reconciler (hierarchize phase) | A proposed `ProbandumEdge` references a parent that has no path upward to an `ultimate` (INV-17 gate). Supervisor closes the gap by authoring the missing parent edges or restating the parent. |
| `scheme-missing` | Reconciler (hierarchize phase) | A proposed `Probandum` carries a `scheme` that is not in the active `mappings/walton-scheme-snapshot.yaml` (INV-18 gate). Supervisor extends the snapshot via `amanuensis map walton-scheme snapshot --extend` before retry. |

Each clarification lives at
`distillations/<source-id>/clarifications/open/<id>.md` until
resolved, then moves to `clarifications/resolved/`.

The supervisor resolves a clarification through one of two paths:

- **CLI**: `amanuensis clarification list` to enumerate, then
  `amanuensis clarification resolve <id> --resolution "<text>"` to
  resolve.
- **Web app**: the `/clarifications` route lists open items and posts
  the resolution via the same substrate path.

Both paths acquire the workspace flock for the duration of the write
and write a paired `clarification-resolved` PROV record (INV-3). The
open-bucket file is unlinked on resolve so the read paths see exactly
one canonical location for each clarification.

### 3. Iteration directives

When a distillation needs to be re-run with new guidance — a narrowed
vocabulary subset, a different focus, a request to re-extract a
specific section at sentence grain — the supervisor issues an
**iteration directive**:

- **CLI**: `amanuensis iteration add --directive "<text>"
  --target-source <id> [--rationale "<text>"]
  [--target-phase {distill,map,extend,synthesize}]`
- **Web app**: the `/iterations` route's add-form posts the same.

The directive lands at `iterations/<id>.md` with a paired
`iteration-issued` PROV record under the target source's
distillation. Directive writes are append-only by design — each call
records a separate event in the supervisor timeline, even if the
arguments are identical.

> **Known gap.** Directive *consumption* is not yet wired. M7.3 writes
> the directives with full PROV but the distill orchestrator does not
> yet read pending directives on the next run; for now, treat the
> directive as an audit-grade note to yourself and adjust the next
> `amanuensis distill` invocation manually. Open follow-up.

### 4. Delivery gate

The delivery gate is the final stage — the supervisor decides the
substrate is ready to render. Phase 1 ships the per-source static-HTML
stub (M9.1): `amanuensis export <source-id> --format static-html
--output <path>` emits a single self-contained HTML file suitable for
share-or-archive. Phase 2b adds a workspace-level bundle exporter:
`amanuensis export --workspace-appendix --out-dir DIR` emits a
directory containing `cross-doc-relations.html` plus per-entity pages
covering every canonical entity touched by a cross-doc relation —
useful when the supervisor wants the cross-doc reasoning rendered in
static form. The full delivery pipeline (audit-HTML bundle,
prose-report variant, render-time policy gates) is Phase 4.

## A canonical end-to-end run

For a single legal-pleading PDF, the canonical sequence is:

```bash
# 1. Bootstrap an engagement workspace.
amanuensis init my-engagement && cd my-engagement

# 2. Ingest the source PDF. Pins the vocabulary snapshot (INV-10)
#    and writes the source-mirror manifest.
amanuensis ingest path/to/brief.pdf --source-id case-2024-001

# 3. Orchestrate the distill phase — writes role queue entries.
amanuensis distill case-2024-001

# 4. Run the dispatch driver once: invokes harness CLIs for the
#    Extractor and Auditor, captures their stdout, writes outputs
#    under dispatch/outputs/<role>-<inputs_hash>/.
amanuensis dispatch --once

# 5. Reconcile: commit clean atoms; raise clarifications for
#    rejections and contested warrants.
amanuensis reconcile

# 6. Supervisor reviews. Either via the local web app:
uvicorn amanuensis.web.app:app
#    Or via CLI:
amanuensis clarification list

# 7. Resolve each open clarification.
amanuensis clarification resolve <id> --resolution "<text>"

# 8. If the distillation needs a re-run, issue a directive and
#    iterate from step 3.
amanuensis iteration add \
    --directive "re-extract §3.2 with sentence grain" \
    --target-source case-2024-001

# 9. Once the substrate is settled, export.
amanuensis export case-2024-001 --format static-html --output report.html

# 10. (Multi-source engagements only) Once 2+ sources are settled,
#     run the Resolve / Audit / Connect map cycle to produce cross-doc
#     relations. The supervisor runs `dispatch --once` between phases.
amanuensis map                                # Phase 2a Resolve + Audit
amanuensis dispatch --once
amanuensis map                                # second pass runs the Connect phase
amanuensis dispatch --once
amanuensis map --connect-only                 # re-run Connect after edits

# 11. (Macroscopic pass — Phase 2c Hierarchize.) Pin the Walton-scheme
#     snapshot, then author the ultimate + penultimates by hand so the
#     Hierarchize role has top-of-tree anchors to attach interim
#     probanda below. The reconciler enforces INV-17 (every non-ultimate
#     traces to an ultimate), so the supervisor MUST declare the
#     ultimate first.
amanuensis map walton-scheme snapshot         # pin the closed Walton vocabulary (INV-18)

amanuensis map probandum add \
    "ACME prevails on its breach claim against Smith." \
    --kind ultimate --scheme argument-from-evidence-to-hypothesis
# → prints p-ult-acme-prevails

amanuensis map probandum add \
    "Smith breached the 2018 contract." \
    --kind penultimate --scheme argument-from-evidence-to-hypothesis \
    --alternative "Smith and ACME mutually agreed to defer the April 2024 delivery." \
    --alternative "The shipment was tendered but rejected by ACME for unrelated quality reasons."
# → prints p-pen-smith-breach

amanuensis map probandum link \
    p-ult-acme-prevails p-pen-smith-breach \
    --kind supports \
    --warrant "If Smith breached, ACME prevails on the breach claim." \
    --warrant-basis "Contract law mapping from breach to remedies."

# 12. Run the Hierarchize phase (interim probanda + edges to evidence).
amanuensis map --hierarchize-only             # enqueue penultimate clusters
amanuensis dispatch --once                    # drive the hierarchize role
amanuensis map --hierarchize-only             # reconcile the outputs
# Optional: alternatively, plain `amanuensis map` runs all three phases.

# 13. Export the workspace-level cross-doc + probandum-tree bundle.
amanuensis export --workspace-appendix --out-dir cross-doc-bundle/
# Bundle includes cross-doc-relations.html, probandum-tree.html, plus
# per-entity (entities/<id>.html) and per-probandum (probanda/<id>.html)
# pages.
```

The integration test that exercises this happy path on a tiny fixture
is
[`tests/integration/test_distill_tiny_fixture.py`](../tests/integration/test_distill_tiny_fixture.py).
Reading the test alongside this guide is the fastest way to see the
sequence end-to-end without standing up a real PDF.

## Web app's role in supervision

The web app is a local-only FastAPI app (default bind:
`127.0.0.1:8723`) that mirrors the supervision surfaces above into a
browser-friendly form. Every route reads through the same Substrate
abstraction the CLI uses, and every mutating route POSTs through the
same workspace flock — so the web app and CLI can be used
interchangeably without race risk.

| Route | Purpose |
| --- | --- |
| `/` | Dashboard: lists distillations with per-source counts (atoms, relations, open clarifications). |
| `/distillations/<src>` | Source overview: manifest summary, role status, recent activity. |
| `/distillations/<src>/atoms` | Atom browser with scale / predicate filters. |
| `/distillations/<src>/atoms/<id>` | Single-atom detail; source-span highlight rendered from the four-tuple (INV-7). |
| `/distillations/<src>/relations` | Cytoscape relation graph. Uses the PM-6 HTMX swap pattern so graph state persists across HTMX swaps (filters, layout choice). |
| `/clarifications` | Lists open clarifications + per-row resolve form (surface #2). |
| `/iterations` | Lists existing directives + add form (surface #3). |
| `/entities` | Entity browser: lists canonical entities with kind, canonical name, and alias count. Phase 2a; Phase 2b extends the detail page with a "Cross-doc edges touching this entity" section. |
| `/resolutions` | Resolution browser: lists active resolutions with triple, entity, and confidence. Phase 2a. |
| `/cross-doc-relations` | Phase 2b cross-doc relation browser: lists every `CrossDocRelation`, filterable by kind / source / shared entity; the detail page renders the warrant, the supersede chain, and a Cytoscape overlay highlighting the relation in the relation graph. |
| `/probanda` | Phase 2c probandum browser: lists every `Probandum`, filterable by kind / scheme. The detail page (`/probanda/<id>`) renders the statement, the alternatives considered, lineage (incoming + outgoing edges), provenance, and the supersede chain. |
| `/probanda/<id>/tree` | Phase 2c probandum tree visualization: Cytoscape (dagre layout) tree rooted at the focal probandum, walking outgoing probandum-edges down to atoms / cross-doc relations. A JSON sibling at `/probanda/<id>/tree.json` returns the graph data. Phase 2a entity-detail pages additionally list probanda referencing the entity (Phase 2c extension). |
| `/probandum-edges/<id>` | Phase 2c probandum-edge detail: warrant, warrant-defensibility, parent / child linkage, supersede chain. |
| `/replay-log` | Recent activity feed for audit — useful for cross-checking what the dispatch driver and the supervisor actually did. |
| `/status` | Workspace health stats (a richer rendering of `amanuensis status`). |

### Binding

By default the app binds `127.0.0.1:8723` — loopback-only. To bind a
non-loopback interface (sharing the supervisor view on a trusted LAN,
running inside a container), set `AMANUENSIS_ALLOW_PUBLIC_BIND=1`
before launching uvicorn (M8.8). Without that opt-in, attempts to bind
a non-loopback host are refused with a clear error.

## Git as backup

amanuensis does NOT manage git for the supervisor (GAP-CV-1
acknowledged). The substrate is the source of truth (INV-8), so
standard git discipline is the supervisor's responsibility:

```bash
cd my-engagement
git init
git add -A && git commit -m "after-ingest"
# ... distill / dispatch / reconcile ...
git commit -am "after-reconcile"
```

The substrate's content-addressable design means a `git diff` between
two workspace states is meaningful: changed atom ids correspond to
changed atom content, and PROV records make the diff self-explaining.
A future milestone may add an `amanuensis snapshot` command that
wraps the convention; for Phase 1, a periodic `git commit -am
"checkpoint"` after each reconcile is the recommended discipline.

The `.gitignore` `amanuensis init` writes already excludes the
workspace flock file, the dispatch failure quarantine, and the
SQLite query cache — so a vanilla `git add -A` is safe out of the
box.

## Concurrency model

Only one mutating operation can run at a time per workspace. The
workspace flock (default 5-second acquisition timeout) sits in front
of every mutating CLI command and every web form POST. The flock is
the SR-4 mitigation: it makes the supervisor's mental model simple —
two operations can never partially interleave on the substrate.

Practical implication: if you POST a `/clarifications/<id>/resolve`
form in the browser while `amanuensis distill` is running in a
terminal, the POST blocks until the distill command releases the
flock (or until the 5s timeout elapses, at which point the POST gets a
clean error and the supervisor can retry). The reverse holds too —
launching `amanuensis dispatch --once` while a form POST is in-flight
blocks the dispatch command.

Read-only commands (`status`, `atom list`, `atom show`, `atom
validate`, `clarification list`, `iteration list`, `vocabulary list`,
`vocabulary show`, `vocabulary snapshot`, `export`, `map status`,
`map entity list`, `map entity show`, `map resolution show`,
`map vocabulary show`, `map relation list`, `map relation show`,
`map probandum list`, `map probandum show`, `map probandum lineage`,
`map walton-scheme show`) do NOT acquire the flock — they are safe to
run concurrently with any mutating operation, and their output is a
snapshot of substrate state at read time.

## Known Limitations

What this protocol does NOT yet provide, as of M8.10:

- **No multi-supervisor coordination.** A workspace assumes a single
  human supervisor at a time. Multiple supervisors editing the same
  workspace concurrently is not yet supported beyond what the
  workspace flock provides (which is mutual exclusion, not
  conflict-resolution). Phase 4 may introduce supervisor roles and
  identity-aware audit.
- **No redaction-aware ingest.** The source-mirror captures every
  paragraph including any sensitive text. Filing the source PDF
  safely — disk encryption, access controls, retention policy — is the
  supervisor's responsibility. Redaction support is a Phase 2
  candidate.
- **No automated iteration-directive consumption.** Directives are
  recorded with full PROV but the distill orchestrator does not yet
  read pending directives on subsequent runs. Open follow-up; until it
  lands, the supervisor must adjust the next `amanuensis distill`
  invocation manually based on the directive text.
- **Dispatch driver runs harness CLIs via subprocess.** In-process LLM
  SDK invocation (calling `anthropic` / `openai` client libraries
  directly) is out of scope for Phase 1; the subprocess boundary is
  what makes the write-isolation contract enforceable. See
  [`skill-author-guide.md`](./skill-author-guide.md#write-isolation-contract).
- **`amanuensis export` is still pre-Phase-4.** Phase 1's per-source
  single-file mode and the Phase 2b / 2c workspace-appendix bundle
  mode are the only delivery surfaces shipped today. The bundle now
  includes `cross-doc-relations.html`, `probandum-tree.html`,
  per-entity (`entities/<id>.html`) and per-probandum
  (`probanda/<id>.html`) pages. The full audit-HTML bundle,
  prose-report rendering, and render-time policy gates remain
  Phase 4. The bundle is workspace-level — to inspect a single source's
  cross-doc edges, use the web app's per-source graph with the
  cross-doc overlay enabled.
- **Tree-not-DAG enforced (Phase 2c).** Probandum hierarchies are
  enforced as trees by INV-16: each non-root probandum has exactly
  one active parent edge. When the same piece of evidence genuinely
  participates in multiple lineages, the Wigmore-sanctioned move is
  copy-by-reference at presentation time (the tree carries one
  canonical subtree and the renderer surfaces the cross-references at
  view time). DAG-shaped multi-lineage substrate is rejected at
  `Substrate.add_probandum_edge`.
- **No real-LLM Hierarchize dispatch verified end-to-end (Phase 2c).**
  Like the Resolver and Connector, the Hierarchize role's real-LLM
  smoke is deferred to the first engagement. The mock-harness smoke
  test and the multi-distillation fixture cover the code path; the
  real-LLM smoke runs against the first production engagement.
- **No full Walton critical-questions matrix (Phase 2c).** Phase 2c
  ships `Probandum.scheme` as a closed-vocabulary string keyed
  against `mappings/walton-scheme-snapshot.yaml`. The per-scheme
  critical-questions matrix is a Phase 2c.5 candidate; today the
  supervisor reads the scheme name and applies the audit discipline
  by hand.
- **No full ACH inconsistency matrix (Phase 2c).** The
  `Probandum.alternatives_considered` field is a free-text list of
  competing hypotheses; the structured ACH inconsistency matrix
  (each alternative scored against each piece of evidence) is
  deferred to Phase 2c.5. The write-time gate ensures non-empty
  alternatives for non-ultimate probanda but does not yet check
  inconsistency-matrix shape.
- **No Tetlock-style calibration (Phase 2c).** Confidence stays a
  closed-vocabulary literal (`high` / `medium` / `low`) on probanda
  and edges. Brier-score calibration, base-rate tracking, and the
  full Tetlock superforecaster toolkit are Phase 4 candidates.

## See also

- [`architecture.md`](./architecture.md) — system architecture and
  component map.
- [`cli-reference.md`](./cli-reference.md) — per-command reference for
  the CLI surface invoked throughout the canonical run.
- [`skill-author-guide.md`](./skill-author-guide.md) — role contracts,
  frontmatter, dispatch queue protocol, write-isolation.
- [`../INVARIANTS.md`](../INVARIANTS.md) — especially INV-1 (marker),
  INV-3 (provenance by construction), INV-4 (determinism boundary),
  INV-8 (substrate is the source of truth), and the Phase 2c
  probandum-tree gates INV-16 / INV-17 / INV-18.
- [`../tests/integration/test_distill_tiny_fixture.py`](../tests/integration/test_distill_tiny_fixture.py)
  — the end-to-end integration test for the happy path described
  above.
