# Handoff: amanuensis

- **Active Plan:** ~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29.md
- **Current Task:** M3.1 — Docling integration via `amanuensis ingest`. Wrap Docling; produce paragraph-indexed source-mirror with `section_path` metadata; emit `source-mirror/manifest.yaml` with source hash + ingest activity PROV record. Write `distillations/<source-id>/source-mirror/paragraphs/p-NNNN.md` with frontmatter per paragraph. Pending; first task in M3 after M2 complete.
- **Critical Files:** ~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29-tasks.md (lines 178–186 are M3.1), src/amanuensis/fs/substrate.py, src/amanuensis/schemas/provenance.py, src/amanuensis/validators/, INVARIANTS.md (INV-3 + INV-7 + INV-10), HISTORY.md.

## Strategic Momentum

Milestone M2 (Validators + vocabulary, 5 tasks) is complete and shipped: 249 tests pass; pyright strict + ruff + ruff-format + vulture all clean; pre-commit + pre-push hooks installed and verified at both stages; public repo live at https://github.com/dave-schmidt-dev/amanuensis with a clean orphan-squash baseline so previously-deleted client-research artifacts are not retrievable from history. INVARIANTS.md graduated INV-3, INV-5, INV-10 from "Gate test (planned)" to "Gate test (active)"; 11 gate tests under `tests/invariants/` certify them on fixture substrate. Immediate next move: dispatch the M3.1 implementer per the orchestrator pattern — Docling integration is the task that lights up two currently-deferred gates (INV-10's "snapshot hash matches manifest entry" and INV-3's walk extension to source-mirror PROV records) once `source-mirror/manifest.yaml` exists.

**Resume note:** the editable install was found stale at session start (likely perturbed by pre-commit hook environments between runs); fix is `uv sync --reinstall-package amanuensis` if pytest fails with `ModuleNotFoundError: No module named 'amanuensis'`. Worth pinning a short bootstrap entry in TASKS.md or the project's standing dev notes if this recurs.

## Active Subagents

None. All M2 implementer + spec-compliance + code-quality + fix subagent chains returned cleanly; the M2-complete commit (`da8e954`) is on `main` and pushed to `origin/main`.
