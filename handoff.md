# Handoff: amanuensis

- **Active Plan:** `~/Documents/Projects/.plans/amanuensis/phase2a-resolve-2026-05-31.md`
- **Active Tasks:** `~/Documents/Projects/.plans/amanuensis/phase2a-resolve-2026-05-31-tasks.md` (82 tasks; 28 done, 54 remain)
- **Current Task:** **T4.1** — `test_intra_doc_only.py` — INV-9 executable gate. First task of M4 (Phase-1-promised invariant gates). Files: create `tests/invariants/test_intra_doc_only.py` + modify `tests/invariants/conftest.py` (add deliberate-violation fixture: a relation whose endpoints span sources). The gate enforces that no Relation has its `from_atom_id` and `to_atom_id` pointing at atoms in DIFFERENT `source_id`s — Phase 1 was supposed to ship this but deferred until Phase 2's cross-doc surface lands; T4.1 is that gate.
- **Critical Files:** `~/Documents/Projects/.plans/amanuensis/phase2a-resolve-2026-05-31-tasks.md` lines 1341-1458 (M4 tasks T4.1-T4.3 in full); `INVARIANTS.md` (INV-9 charter entry needs status update from "no executable gate yet" to "active" once T4.1 lands; INV-2 similarly for T4.2); `tests/invariants/conftest.py` (deliberate-violation fixture pattern to mirror); `src/amanuensis/schemas/relation.py` (Relation has `source_id` field — verify before authoring fixture).

## Strategic Momentum

Phase 2a M1+M2+M3 shipped this session — 28 of 82 tasks done in 11 feature commits + 3 docs/chore commits. Heavy subagent-driven parallelism: M1 ran 3 waves (T1.1 → T1.2-T1.8 parallel ×7 → T1.9+T1.10+T1.12 parallel ×3 → T1.11 sequential), M2 ran 2 waves (T2.1+T2.3 parallel → T2.4+T2.5 parallel; T2.2 inline by orchestrator), M3 ran 1 big wave (T3.1 + T3.2-T3.8 batched + T3.9-T3.11 batched) with inline fixes for 5 conftest-import errors + 1 mutation-test forging error + 2 type errors. Combined spec+code-quality reviewer per task saved ~half the dispatch overhead vs the skill's default two-stage cadence; reviewers caught two real latent bugs that would have hit production: (1) T1.8 implementer's `_serialize.py` v1 `kind` injection corrupted content hashes (kind is identity-bearing, not in `_VOLATILE_FIELDS`) — reverted; v1 records now go through T1.10/T1.11 migration before reaching the deserializer; (2) T1.10's frontmatter parser used `find("---")` instead of `find("\n---")` — would silently mis-split YAML with `---` mid-block-scalar; fixed. Orchestration lesson: do NOT dispatch source-modifying subagents in parallel with a `git push` (pre-push runs full ~7min suite; "files-modified-during-hook" check trips when subagents write during that window). M2 push aborted on this; commits are valid (636/636 tests pass) but need a clean re-push after M3 settled. Per-task targeted verification stays 2-3s (`tests/<subdir>/`); full suite reserved for pre-push (phase boundaries). Per-task atomic commits where clean; batched commits for sibling-task sequences (e.g. T3.2-T3.8). User explicit guidance for the session: maximize parallelism, slow tests at phase boundaries + pushes only. **Immediate next move (next session):** invoke `superpowers:subagent-driven-development`, plan M4 tasks (3 small invariant gates — T4.1 INV-9, T4.2 INV-2, T4.3 INVARIANTS.md status updates; all independent files, can run fully parallel). Then M5 skill bundle (5 tasks, also independent files). After M5 do the M2+M3 push (no source-modifying subagents during it). Then M6-M11 (cumulative ~46 remaining tasks).

## Active Subagents

None. All 11 dispatched subagents this session completed cleanly (8 implementers across M1 wave 1+2; 3 implementers for M3 — T3.1 Haiku, T3.2-T3.8 Sonnet, T3.9-T3.11 Sonnet). 6 reviewer subagents in M1's combined spec+quality wave plus 3 in M2's. Two background `git push` bash tasks: first succeeded (M1; 8 commits pushed), second failed (M2; due to M3 implementers racing — non-fatal, commits are local and valid). No dispatch queue, no replay-log entries pending reconcile.

## Unpushed Commits (8)

```
7cab37a refactor: ReplayLog dual-path (distillation+mapping scope) + centralized resolver (CR-4, PM-1, SR-2) [T3.9-T3.11]
e985fd3 feat: Substrate mappings/ extensions — paths, add/get/list for Entity+Resolution+Supersedes, latest_*_for walkers, enumerators, ensure_mappings_readme [T3.2-T3.8]
0b9412d feat: Phase 2a typed substrate exceptions [T3.1]
8ac5720 feat: Substrate entity-vocabulary snapshot + archive (Phase 2a M2) [T2.5]
9f81cd1 feat: entity_kind_in_vocabulary validator (Phase 2a M2) [T2.4]
fef6d7c feat: EntityVocabulary loader (Phase 2a M2) [T2.3]
1148a55 feat: entity-kinds.yaml template-loadable gate test (PM-5) [T2.2]
ae28096 feat: entity-kinds.yaml template (9 kinds; Phase 2a M2) [T2.1]
```

When pushing: ensure NO subagents are writing to source files during the push (pre-push hook runs the full suite ~7min and "files-modified-during-hook" check is strict).
