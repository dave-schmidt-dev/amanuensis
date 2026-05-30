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

Distill a single source into the substrate: emit atoms (with their PROV
records and intra-document relations) by enqueueing one Extractor pass
and one Auditor pass against the source-mirror, then reconcile the
outputs against the M7.4 gate. This skill is the playbook a supervisor
LLM (or the CLI as a degenerate no-LLM supervisor) follows when the
user invokes `amanuensis distill <source-id>`.

## Inputs

- `--source-id` (required): the source-mirror identifier to distill.
- `--role-set` (optional): override the default active role set
  (`extractor,auditor`). Phase 1 only honors the two active roles; stub
  roles are skipped with a notice (see "Stub roles" below).
- `--interactive` (optional): pause after each enqueue so the supervisor
  can confirm before the dispatch driver runs.

## Workflow

1. **Confirm marker (INV-1).** Refuse to proceed if the working
   directory is not a marked amanuensis project. The `@require_marker`
   decorator on the CLI command enforces this; the supervisor should
   surface the error verbatim.
2. **Confirm source-mirror exists.** Run `amanuensis status` and verify
   the requested `--source-id` appears in the ingested-sources list. If
   it does not, instruct the user to run
   `amanuensis ingest <path-to-source>` first; do not attempt to
   distill an un-ingested source.
3. **Enqueue Extractor.** Enqueue one Extractor work item for the
   source. The dispatch queue entry's `inputs_hash` is the SHA-256 of
   `(source_id, source-mirror manifest hash, vocabulary snapshot hash)`
   so requeues are deterministic.
4. **Enqueue Auditor.** Enqueue one Auditor work item that takes the
   Extractor's output path as its input. The Auditor entry's
   `inputs_hash` covers the Extractor's `output.yaml` content hash.
5. **Run dispatch.** Run `amanuensis dispatch --once` (or, in
   non-interactive supervisor mode, instruct the supervisor harness to
   do so). The driver invokes the configured agent harness (Claude /
   Codex / Cursor / Gemini) per role and lands outputs at
   `dispatch/outputs/<role>-<hash>/output.yaml`.
6. **Reconcile via the M7.4 gate.** The reconciliation gate (lands
   separately) consumes the Extractor + Auditor outputs, merges
   accepted atoms into the substrate, writes PROV records, and emits
   any clarifications the Auditor raised. Until M7.4 is in place, stop
   here and surface the raw outputs to the supervisor.

## Stub roles

Phase 1 ships Extractor + Auditor as the only active roles. The three
stub roles below are reserved for Phase 2 and are skipped (with a
notice) if listed in `--role-set`:

- **Contrarian** (`distill_contrarian`) — steelmans the opposing
  framing.
- **Constructive** (`distill_constructive`) — proposes alternative
  atomizations a senior reviewer might recommend.
- **Premortem** (`distill_premortem`) — catalogs failure modes before
  extraction runs.

## Reading the skill list

The set of CLI commands each skill invokes is enumerated in its
frontmatter under `cli_commands_invoked`. Supervisors that need to
pre-flight permissions or sandbox a harness can read that field
without parsing the skill body.

## Hard rules

- **INV-1.** Refuse to operate without an `amanuensis.yaml` marker.
- **INV-3.** Every substrate write (atom, relation, PROV record,
  clarification) carries provenance by construction; never retrofit.
- **INV-4.** LLM calls (Extractor, Auditor) cross the determinism
  boundary only through the dispatch driver; the orchestrator never
  calls a model directly.
- **INV-8.** The substrate on disk is the source of truth; never
  cache, mirror, or summarize substrate state in some other store and
  then act on the mirror.
