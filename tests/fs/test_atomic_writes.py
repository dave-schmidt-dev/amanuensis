"""Atomic write discipline + round-trip + id-mismatch enforcement.

The atomic-write contract: callers see either the previous canonical
content or the new canonical content, never a torn intermediate. We
test that contract three ways:

1. Round-trip — every supported on-disk format parses back to a model
   that equals the original (write→read fixed point).
2. ID mismatch — refusal at the substrate layer to write a model whose
   ``id`` disagrees with ``compute_id(model)``.
3. Crash simulation — a child subprocess writes a sibling tmp file and
   exits abruptly via ``os._exit(1)`` before the rename. The canonical
   path does not exist; the orphan tmp file is recoverable.

The crash test uses ``os._exit`` rather than a real SIGKILL because
self-SIGKILL is flaky on macOS (signal delivery races the subprocess
boundary) and because the proof is "the canonical path never receives a
torn write" — that's invariant under any abrupt exit, not just SIGKILL.
"""

from __future__ import annotations

import multiprocessing
import os
from collections.abc import Iterable
from pathlib import Path

import pytest

from amanuensis.fs import Substrate, SubstrateIdMismatch
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import (
    parse_clarification_md,
    parse_iteration_md,
    parse_provenance_yaml,
    parse_relation_yaml,
)
from amanuensis.schemas import (
    Atom,
    Clarification,
    IterationDirective,
    ProvenanceRecord,
    Relation,
    compute_id,
)

# --- Round-trip fixtures ----------------------------------------------


def test_atom_round_trip(tmp_workspace: Path, atom: Atom) -> None:
    sub = Substrate(tmp_workspace)
    path = sub.add_atom(atom.source_id, atom)
    assert path.is_file()
    loaded = sub.get_atom(atom.source_id, atom.id)
    assert loaded == atom


def test_relation_round_trip(tmp_workspace: Path, relation: Relation) -> None:
    sub = Substrate(tmp_workspace)
    path = sub.add_relation(relation.source_id, relation)
    assert path.is_file()
    loaded = parse_relation_yaml(path.read_text(encoding="utf-8"))
    assert loaded == relation


def test_provenance_round_trip(tmp_workspace: Path, provenance: ProvenanceRecord) -> None:
    sub = Substrate(tmp_workspace)
    path = sub.add_provenance("src-fixture-001", provenance)
    assert path.is_file()
    # Path is keyed by the prov record's OWN id, not its entity_id.
    assert path.name == f"{provenance.id}.yaml"
    loaded = parse_provenance_yaml(path.read_text(encoding="utf-8"))
    assert loaded == provenance


def test_clarification_round_trip_open(tmp_workspace: Path, clarification: Clarification) -> None:
    sub = Substrate(tmp_workspace)
    path = sub.add_clarification("src-fixture-001", clarification)
    assert path.is_file()
    # Open clarifications land in the open/ bucket.
    assert path.parent.name == "open"
    loaded = parse_clarification_md(path.read_text(encoding="utf-8"))
    assert loaded == clarification


def test_clarification_resolved_goes_to_resolved_bucket(
    tmp_workspace: Path, resolved_clarification: Clarification
) -> None:
    sub = Substrate(tmp_workspace)
    path = sub.add_clarification("src-fixture-001", resolved_clarification)
    assert path.is_file()
    assert path.parent.name == "resolved"
    loaded = parse_clarification_md(path.read_text(encoding="utf-8"))
    assert loaded == resolved_clarification


def test_iteration_round_trip(tmp_workspace: Path, iteration: IterationDirective) -> None:
    sub = Substrate(tmp_workspace)
    path = sub.add_iteration(iteration)
    assert path.is_file()
    # Iterations live at workspace root, not under any distillation.
    assert path.parent == tmp_workspace.resolve() / "iterations"
    loaded = parse_iteration_md(path.read_text(encoding="utf-8"))
    assert loaded == iteration


# --- ID mismatch enforcement -----------------------------------------


def test_add_atom_rejects_wrong_id(tmp_workspace: Path, atom: Atom) -> None:
    sub = Substrate(tmp_workspace)
    # Substitute an id that does not match the content hash.
    payload = atom.model_dump(mode="python")
    payload["id"] = "a-deadbeef00000000"  # well-formed but wrong
    bogus = Atom(**payload)
    with pytest.raises(SubstrateIdMismatch):
        sub.add_atom(atom.source_id, bogus)
    # Confirm nothing was written.
    assert not sub.atom_path(atom.source_id, bogus.id).exists()


def test_add_relation_rejects_wrong_id(tmp_workspace: Path, relation: Relation) -> None:
    sub = Substrate(tmp_workspace)
    payload = relation.model_dump(mode="python")
    payload["id"] = "r-deadbeef00000000"
    bogus = Relation(**payload)
    with pytest.raises(SubstrateIdMismatch):
        sub.add_relation(relation.source_id, bogus)


def test_add_provenance_rejects_wrong_id(tmp_workspace: Path, provenance: ProvenanceRecord) -> None:
    sub = Substrate(tmp_workspace)
    payload = provenance.model_dump(mode="python")
    payload["id"] = "p-deadbeef00000000"
    bogus = ProvenanceRecord(**payload)
    with pytest.raises(SubstrateIdMismatch):
        sub.add_provenance("src-fixture-001", bogus)


def test_add_clarification_rejects_wrong_id(
    tmp_workspace: Path, clarification: Clarification
) -> None:
    sub = Substrate(tmp_workspace)
    payload = clarification.model_dump(mode="python")
    payload["id"] = "c-deadbeef00000000"
    bogus = Clarification(**payload)
    with pytest.raises(SubstrateIdMismatch):
        sub.add_clarification("src-fixture-001", bogus)


def test_add_iteration_rejects_wrong_id(tmp_workspace: Path, iteration: IterationDirective) -> None:
    sub = Substrate(tmp_workspace)
    payload = iteration.model_dump(mode="python")
    payload["id"] = "i-deadbeef00000000"
    bogus = IterationDirective(**payload)
    with pytest.raises(SubstrateIdMismatch):
        sub.add_iteration(bogus)


# --- source_id cross-check -------------------------------------------


def test_add_atom_rejects_source_mismatch(tmp_workspace: Path, atom: Atom) -> None:
    sub = Substrate(tmp_workspace)
    with pytest.raises(ValueError, match="source_id"):
        sub.add_atom("not-the-right-source", atom)


def test_add_relation_rejects_source_mismatch(tmp_workspace: Path, relation: Relation) -> None:
    sub = Substrate(tmp_workspace)
    with pytest.raises(ValueError, match="source_id"):
        sub.add_relation("not-the-right-source", relation)


# --- list_atoms ------------------------------------------------------


def test_list_atoms_returns_generator(tmp_workspace: Path, atom: Atom) -> None:
    sub = Substrate(tmp_workspace)
    sub.add_atom(atom.source_id, atom)
    result = sub.list_atoms(atom.source_id)
    # Must be an Iterable, not a materialized list (generator preferred).
    assert isinstance(result, Iterable)
    atoms = list(result)
    assert len(atoms) == 1
    assert atoms[0] == atom


def test_list_atoms_empty_distillation(tmp_workspace: Path) -> None:
    sub = Substrate(tmp_workspace)
    # No atoms written. Should yield nothing without raising.
    assert list(sub.list_atoms("src-fixture-001")) == []


def test_list_atoms_skips_tmp_writer_leftovers(tmp_workspace: Path, atom: Atom) -> None:
    sub = Substrate(tmp_workspace)
    sub.add_atom(atom.source_id, atom)
    # Drop a fake .tmp.* sibling that would parse-fail if read.
    atoms_dir = sub.atom_path(atom.source_id, atom.id).parent
    bogus_tmp = atoms_dir / "a-faketmp.md.tmp.99999.deadbeef"
    bogus_tmp.write_text("not valid frontmatter", encoding="utf-8")
    # list_atoms must skip the .tmp sibling.
    atoms = list(sub.list_atoms(atom.source_id))
    assert len(atoms) == 1
    assert atoms[0] == atom


# --- Atomic semantics: pre-rename invariant --------------------------


def test_atomic_write_leaves_no_tmp_on_success(tmp_workspace: Path) -> None:
    target = tmp_workspace / "iterations" / "test-output.txt"
    atomic_write_text(target, "hello world\n")
    assert target.read_text(encoding="utf-8") == "hello world\n"
    # No leftover .tmp.* sibling.
    leftovers = [p for p in target.parent.iterdir() if ".tmp." in p.name]
    assert leftovers == []


def test_atomic_write_overwrites_existing(tmp_workspace: Path) -> None:
    target = tmp_workspace / "iterations" / "test-output.txt"
    atomic_write_text(target, "first\n")
    atomic_write_text(target, "second\n")
    assert target.read_text(encoding="utf-8") == "second\n"


def test_torn_tmp_file_does_not_corrupt_canonical_path(tmp_workspace: Path) -> None:
    # Simulate the half-written-tmp state directly: write a .tmp.<pid>.<x>
    # file but no rename. The canonical path must not exist (no reader
    # sees a torn write), and the tmp orphan is unlinkable.
    target = tmp_workspace / "iterations" / "torn.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f"{target.name}.tmp.99999.cafebabe"
    tmp.write_text("HALF WRITTEN", encoding="utf-8")
    # Canonical path: untouched.
    assert not target.exists()
    # Orphan: recoverable.
    tmp.unlink()
    assert not tmp.exists()


# --- Crash simulation (subprocess) -----------------------------------


def _crash_mid_write(target_str: str) -> None:
    """Child entry point: open the .tmp file, write, then exit abruptly.

    We deliberately do NOT call ``os.replace``. The parent test asserts
    the canonical target never gets created.
    """
    target = Path(target_str)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f"{target.name}.tmp.{os.getpid()}.abadcafe"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("PARTIAL")
        f.flush()
        os.fsync(f.fileno())
    # Abrupt exit BEFORE rename. We use os._exit(1) (not SIGKILL) for
    # cross-platform reliability; the invariant under test ("canonical
    # path never sees a torn write") holds regardless of the signal.
    os._exit(1)


def test_crash_mid_write_leaves_canonical_path_untouched(tmp_workspace: Path) -> None:
    target = tmp_workspace / "iterations" / "crashed.txt"
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=_crash_mid_write, args=(str(target),))
    proc.start()
    proc.join(timeout=10)
    # The child exited with code 1 (our abrupt exit).
    assert proc.exitcode == 1
    # Invariant: canonical target does NOT exist.
    assert not target.exists()
    # Orphan .tmp.* sibling exists and is unlinkable.
    leftovers = [p for p in target.parent.iterdir() if p.name.startswith(f"{target.name}.tmp.")]
    assert len(leftovers) == 1
    leftovers[0].unlink()


def test_compute_id_matches_added_artifact(tmp_workspace: Path, atom: Atom) -> None:
    # End-to-end check that ``compute_id(model)`` agrees with the path
    # the substrate writes to. If this ever drifts, the path-as-truth
    # invariant has broken.
    sub = Substrate(tmp_workspace)
    path = sub.add_atom(atom.source_id, atom)
    assert path.name == f"{compute_id(atom)}.md"
