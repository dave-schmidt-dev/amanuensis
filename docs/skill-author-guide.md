# Skill Author Guide

## Audience and scope

This guide is for someone authoring a new amanuensis skill (a new role for
the distill phase, or a new orchestrator for a future phase) or extending
an existing one. In scope: the skill file format, the frontmatter
contract, body conventions, the dispatch queue protocol as seen from the
skill's perspective, and the write-isolation contract a role must
respect. Out of scope: the per-harness install paths
(`~/.claude/skills/amanuensis/`, `~/.codex/skills/`, etc.) and the
detection logic that maps a harness CLI to its skill directory — those
live in [`cli-reference.md`](./cli-reference.md) under the
`install-skills` command.

## Skill file format

A skill is a single Markdown file under `src/amanuensis/skills/` with
YAML frontmatter on top and a Markdown body below. The frontmatter is
the machine-readable contract that the dispatch driver and the
`install-skills` command consume; the body is the prompt text that the
dispatch driver hands to the role's harness CLI.

Skeleton (lifted from `src/amanuensis/skills/distill.md`):

```markdown
---
name: distill
description: Orchestrator skill for distilling a single source into atoms, relations, and PROV records.
role: orchestrator
version: 0.1.0
active: true
stub: false
expects_substrate: true
phase: distill
cli_commands_invoked:
  - amanuensis ingest
  - amanuensis status
  - amanuensis dispatch --once
  - amanuensis distill
---

## Purpose

<role body — prompt text the dispatch driver feeds to the harness CLI>
```

### Required frontmatter fields

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | str | File-stem-style identifier (no spaces). Must be unique across the skill set. |
| `description` | str | One-sentence summary; surfaced by `amanuensis install-skills` and by harness skill listings. |
| `role` | str | Substrate role this skill plays — `orchestrator`, `extractor`, `auditor`, `contrarian`, `constructive`, `premortem`. Drives dispatch-queue routing. |
| `version` | str | Semver string. Bumped when the body or frontmatter contract changes. |
| `active` | bool | Whether the orchestrator should enqueue work items for this role. Must be `true` for non-stub skills, `false` for stubs. |
| `stub` | bool | Whether this skill is a Phase 2 placeholder. Must be `false` for shipped roles, `true` for placeholders. |
| `expects_substrate` | bool | Whether the role reads or writes the workspace substrate. Almost always `true` in Phase 1. |
| `phase` | str | Pipeline phase — `distill`, `map`, `extend`, `synthesize`. Phase 1 only ships `distill`. |
| `cli_commands_invoked` | list[str] | Every `amanuensis ...` invocation the body asks the harness to run. Lets supervisors pre-flight permissions without parsing the body. |

### Conditional fields

- When `stub: true`, the frontmatter MUST also carry `stub_reason: "<why
  this is deferred>"`, and `active` MUST be `false`.
- When `stub: false`, `active` MUST be `true`.

These rules are enforced by
[`tests/skills/test_skill_frontmatter.py`](../tests/skills/test_skill_frontmatter.py);
a violation fails on the next pytest run.

## The stub mechanism

Phase 1 ships two active roles — Extractor and Auditor — and three stub
roles that the orchestrator's role-set logic knows about but does not
yet run: Contrarian, Constructive, Premortem. The stubs exist on disk
so:

- The orchestrator can list every Phase 2 role in its frontmatter and
  body without the test suite tripping on a missing skill file.
- The frontmatter test parametrically covers every shipped role,
  including the placeholders, so the role-set inventory stays honest.
- Activating a Phase 2 role is a small diff: flip `active: true`,
  remove `stub_reason`, fill in the body's currently-prose contract with
  the agreed-upon Phase 2 contract.

When the distill orchestrator (M7.3) sees a role whose `active: false`
or `stub: true`, it skips enqueueing work for that role and writes a
replay-log entry recording the skip
(`entity_type: "role-skipped"`). The skip is observable in
`amanuensis status` output and in any post-hoc replay-log audit; it is
never silent.

## Dispatch queue protocol — from the skill's perspective

When the orchestrator decides to run your role, it writes a
`DispatchQueueEntry` to
`<workspace>/dispatch/queue/<role>-<inputs_hash>.yaml`. The entry's
schema lives at
[`src/amanuensis/llm/queue.py`](../src/amanuensis/llm/queue.py); the
fields a skill author needs to know:

- `role` — your skill's `role` frontmatter value, used by the dispatch
  driver to route the queue entry to the right harness CLI and output
  directory.
- `prompt` — the full Markdown body of your skill file (frontmatter
  stripped). The dispatch driver feeds this verbatim to the harness CLI
  on stdin. The body IS the prompt.
- `inputs` — a structured dict (`source_id`, `manifest_path`,
  `workspace_root`, role-specific references). Role-specific keys are
  documented in each role's body under the "Inputs" section.
- `model_id` — the model the driver targets, recorded in the eventual
  PROV-O record's `was_attributed_to.identifier`.
- `inputs_hash` — SHA-256 of canonical `{role, prompt, inputs,
  model_id}`. The cache key, the cross-reference between queue entry /
  PROV-O record / replay-log entry / output directory, and the
  determinism boundary's identity for this invocation.

### What the driver does with your queue entry

1. Reads the entry from disk
   ([`src/amanuensis/dispatch/queue.py`](../src/amanuensis/dispatch/queue.py)
   `dequeue` / `_load_queue_entry`).
2. Looks up `role` in the hardcoded role-to-harness mapping (Phase 1:
   `{extractor: claude, auditor: claude, ...}`) and resolves the CLI
   path (`claude`, `codex`, `cursor-agent`, `gemini`).
3. Snapshots the workspace mtime tree, excluding the role's allowed
   output directory and standard cache/VCS noise
   ([`src/amanuensis/dispatch/isolation.py`](../src/amanuensis/dispatch/isolation.py)
   `snapshot_workspace_tree`).
4. Invokes the harness CLI as a subprocess with the entry's `prompt` on
   stdin; captures stdout.
5. Parses stdout as YAML (preferred) or JSON; rejects parse failures by
   moving the queue entry to `dispatch/failures/` with `reason="output-parse-error"`.
6. Re-walks the tree
   (`assert_no_unauthorized_mutation`); any out-of-bounds mutation
   moves the queue entry to `dispatch/failures/` with
   `reason="write-isolation-violation"`.
7. On success, calls
   `move_to_outputs(workspace, queue_path, role=..., inputs_hash=...,
   output_payload=...)`, which writes
   `dispatch/outputs/<role>-<inputs_hash>/output.yaml` (mode `0600`)
   and unlinks the queue entry.
8. Writes a PROV-O record and a replay-log entry for the dispatch
   (M5.2 mechanics). On a cache hit, the original PROV-O record is the
   one referenced — the subprocess is not re-run.

### Cache semantics (INV-4)

Identical inputs produce an identical `inputs_hash`. An identical
`inputs_hash` is a cache hit: the dispatch driver returns the
byte-identical output of the original call without invoking the
subprocess. This is the determinism-boundary contract from
[INV-4](../INVARIANTS.md): every LLM call crosses a single named gate,
and that gate is content-addressable so replays are deterministic.

The implication for skill authors: any non-determinism the body
introduces (a wall-clock reference, a "pick randomly between" prompt
fragment) breaks replay. Keep the prompt body deterministic; let the
harness CLI introduce randomness if it must.

## Write-isolation contract

The dispatched role's harness CLI subprocess MUST NOT modify any file
outside its assigned output directory
`dispatch/outputs/<role>-<inputs_hash>/`. The dispatch driver enforces
this structurally:

1. Snapshots the workspace mtime tree before invoking the subprocess.
2. Re-walks the tree after the subprocess exits.
3. Any path that was added or whose mtime changed (outside the allowed
   subtree, outside the standard skip list of `.venv`, `__pycache__`,
   `.git`, etc.) is a violation. The queue entry is routed to
   `dispatch/failures/` with `reason="write-isolation-violation"` and a
   detail listing every offending path.

Skill authors should phrase the role's contract explicitly. The body
should say, in so many words: "writes structured YAML/JSON to stdout;
performs no filesystem mutations." If a role genuinely needs to record
intermediate state (a debug log, a scratch file), it must write it
inside its assigned output directory — the dispatch driver creates that
directory before invocation and excludes it from the snapshot.

The mtime check is cheap, not adversarial. The threat model is "buggy
role agent that accidentally writes outside its sandbox", not "actively
malicious role agent" — see the isolation module's docstring for the
trade-off rationale.

## Examples — Extractor and Auditor

### Extractor (`distill_extract.md`)

Output contract, quoted from the skill:

```markdown
Emit structured YAML on stdout matching the `Atom` schema. The top
level is a list; one atom per list item. The dispatch driver routes
the captured stdout to
`dispatch/outputs/extractor-<inputs_hash>/output.yaml` atomically.
```

Notable points:

- The Extractor does NOT emit PROV records itself. PROV records are
  written by the dispatch driver from the queue entry's metadata
  (INV-3 provenance by construction is enforced at the boundary, not by
  the agent). A skill author writing a new substrate-emitting role
  should follow the same pattern: emit the substrate payload, let the
  driver attach provenance.
- Every emitted atom must satisfy INV-5 (closed vocabulary), INV-6
  (`scale_anchor`), and INV-7 (citation four-tuple). The body lists the
  seven canonical validators that run after extraction — the Extractor
  is expected to read those constraints and produce conformant output;
  the validators are the structural backstop, not the first line of
  defense.
- The pinned vocabulary lives at
  `distillations/<source-id>/vocabulary-snapshot.yaml` per
  [INV-10](../INVARIANTS.md#inv-10--vocabulary-is-pinned-per-distillation).
  The body explicitly forbids reading the global registry at extraction
  time.

### Auditor (`distill_audit.md`)

Output contract, quoted from the skill:

```markdown
Emit structured YAML on stdout. The dispatch driver routes it to
`dispatch/outputs/auditor-<inputs_hash>/output.yaml`. Required shape:

accepted_atom_ids:
  - atom-0001
  - atom-0003
rejected_atoms:
  - atom_id: atom-0002
    reason: "char_span 102-247 does not contain a sentence supporting predicate `caused`"
    warrant_defensibility: contested
clarifications:
  - question: "Should atom-0004 be narrowed to §3.2 only, or also cover §3.3?"
    raised_against_atom_id: atom-0004
    options:
      - "Narrow to §3.2 only"
      - "Keep both sections"
      - "Reject atom-0004"
```

Notable points:

- The Auditor's output is the input to the M7.4 reconciliation gate.
  Accepted atoms merge to the substrate, rejected atoms do not,
  clarifications block merge until a human supervisor resolves them.
- **Contested-warrant auto-clarification (CR-7).** When a rejection
  carries `warrant_defensibility: contested`, the M7.4 reconciliation
  gate auto-raises a `warrant-defensibility-contested` clarification
  even if the Auditor itself did not enumerate options. This is the
  mechanism that satisfies
  [INV-3](../INVARIANTS.md#inv-3--provenance-by-construction): the
  inference step from source span to atom claim is itself an event the
  supervisor sees and resolves on the record. Skill authors adding new
  audit-style roles should respect this convention — surface contested
  warrants explicitly; do not silently absorb them into a pass/fail
  signal.

## Example — a stub (`distill_contrarian.md`)

A stub skill's frontmatter and body together describe both what the
Phase 2 role WILL do and what activation requires. Use this template
when adding a new stub:

```yaml
---
name: distill_contrarian
description: Contrarian role (STUB, Phase 2) — steelmans the opposing framing of the Extractor's atoms.
role: contrarian
version: 0.1.0
active: false
stub: true
stub_reason: "Phase 1 ships Extractor + Auditor only; Contrarian (challenges the Extractor's framing from a steelman-the-opposing-side angle) is Phase 2."
expects_substrate: true
phase: distill
cli_commands_invoked: []
---
```

The body should cover:

- What the role will do once activated (one or two paragraphs).
- What inputs it will consume (overlap with active roles is fine and
  expected).
- The planned output contract (schema sketch, even if not yet pinned).
- The Phase 2 gate for activation — what other milestones must land
  first. For Contrarian: the support/attack edge schema and the
  cross-document entity-resolution layer (INV-9 extension), because
  Contrarian output only becomes useful once multiple sources can attack
  one another's claims through a shared entity graph.

## Validation

Every shipped skill is validated by
[`tests/skills/test_skill_frontmatter.py`](../tests/skills/test_skill_frontmatter.py).
The test is parametric over `src/amanuensis/skills/*.md`, so adding a
new skill file auto-extends coverage on the next pytest collection. The
test enforces:

- Frontmatter fences (`---` open on line 1, `---` close before body).
- Every required field is present and well-typed.
- Stub-vs-active rules (`stub: true` ⇒ `active: false` + `stub_reason`;
  `stub: false` ⇒ `active: true`).
- Role-set inventory: at least one orchestrator, at least two active
  roles, at least three stub roles.

The frontmatter splitter the production code uses is
`amanuensis.skills._frontmatter.split_frontmatter(text: str) ->
tuple[dict, str]`. It accepts the raw `.md` text of a skill file and
returns `(frontmatter_dict, body)`. Use this helper (rather than
re-implementing the split) in any new code that loads skill files; the
test module uses an equivalent inline implementation for isolation.

## Cross-links

- [`docs/architecture.md`](./architecture.md) — system architecture
  and the surrounding component map.
- [`docs/cli-reference.md`](./cli-reference.md) — `amanuensis distill`
  and `amanuensis install-skills` command details, including harness
  detection.
- [`INVARIANTS.md`](../INVARIANTS.md) — INV-1 (marker), INV-3
  (provenance by construction), INV-4 (determinism boundary), INV-5
  (closed vocabulary), INV-6 (`scale_anchor`), INV-7 (citation
  four-tuple), INV-8 (substrate is the source of truth).
- [`tests/skills/test_skill_frontmatter.py`](../tests/skills/test_skill_frontmatter.py)
  — the parametric frontmatter gate.

## Known limitations

- Stubs are Phase 1 placeholders for Phase 2 roles; activating one
  requires a code + test + plan iteration (not just a frontmatter
  flip), because each role's output contract feeds downstream gates
  that need to be in place first.
- The dispatch driver invokes harness CLIs via subprocess. In-process
  LLM SDK invocation (calling an `anthropic` / `openai` client
  directly) is out of scope for Phase 1; the subprocess boundary is
  what makes write-isolation enforceable.
- Skill files use YAML frontmatter parsed with a hand-rolled splitter
  (`amanuensis.skills._frontmatter.split_frontmatter`); no
  `python-frontmatter` dependency is added. The format is constrained
  (open fence on line 1, close fence on its own line) to keep the
  splitter trivial.
- `amanuensis install-skills` is a copy, not a symlink. Editing a
  shipped skill in-tree does not propagate to installed harness skill
  directories until you re-run `amanuensis install-skills`.
