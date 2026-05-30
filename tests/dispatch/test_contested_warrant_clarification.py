"""CR-7 — warrant-defensibility-contested clarification (M7.4).

The reconciliation gate must auto-raise a
``warrant-defensibility-contested`` clarification whenever:

- an extractor's ``proposed_relations`` entry carries
  ``warrant_defensibility: contested``, OR
- an auditor's ``rejected_atoms`` entry carries the same value.

This test plants the extractor variant — the load-bearing CR-7 contract
is that the gate sees ``contested`` and writes an open clarification
with the discriminating activity slot ``"warrant-defensibility-contested"``
and a ``context_refs`` list naming the contested artifact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import Substrate
from amanuensis.fs._serialize import parse_clarification_md
from amanuensis.schemas import (
    OperandTypeSchema,
    Vocabulary,
    VocabularyEntry,
)


def _make_workspace(tmp_path: Path) -> Path:
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: cr7-test\n",
        encoding="utf-8",
    )
    return tmp_path


def _plant_distillation(workspace: Path, source_id: str) -> Substrate:
    substrate = Substrate(workspace)
    (workspace / "distillations" / source_id).mkdir(parents=True, exist_ok=True)
    substrate.snapshot_vocabulary(
        source_id,
        Vocabulary(
            name="cr7-vocab",
            version="0.1.0",
            entries=[
                VocabularyEntry(
                    predicate="asserts_obligation",
                    aliases=[],
                    operand_types=[
                        OperandTypeSchema(name="subject", kind="entity", required=True),
                    ],
                    qualifier_required=False,
                    notes="cr7-test entry",
                ),
            ],
        ),
    )
    return substrate


def _atom_payload(source_id: str, narrative: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "section_path": ["§1"],
        "paragraph_index": 0,
        "char_span": [0, len(narrative)],
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [
            {"role": "subject", "kind": "entity", "value": "ent-acme"},
        ],
        "narrative": narrative,
        "qualifier_level": None,
        "qualifier_basis": None,
    }


def test_contested_warrant_on_relation_auto_raises_clarification(tmp_path: Path) -> None:
    """A relation flagged ``contested`` raises a warrant-defensibility-contested clarification."""
    workspace = _make_workspace(tmp_path)
    source_id = "cr7-src"
    substrate = _plant_distillation(workspace, source_id)

    # Two atoms so the relation's endpoints resolve through
    # local_to_committed and lineage_closure passes.
    atom_a = _atom_payload(source_id, "ACME shall pay within 30 days.")
    atom_b = _atom_payload(source_id, "ACME shall remit on invoice.")

    payload: dict[str, Any] = {
        "proposed_atoms": [atom_a, atom_b],
        "proposed_relations": [
            {
                "source_id": source_id,
                # We won't know the canonical atom ids until reconcile
                # computes them; reference the atoms by content_hash =
                # the narrative-uniqued shape. The reconciler maps via
                # local_to_committed; here we hand it the explicit
                # ``content_hash`` slot the brief documents.
                "from_atom_id": "local-a",
                "to_atom_id": "local-b",
                "kind": "supports",
                "warrant": "Both clauses bind the same obligation by parallel language.",
                "warrant_defensibility": "contested",
                "warrant_basis": "literary inference",
                "confidence": "medium",
            }
        ],
    }
    # Mark the atoms with local ids so the relation pass can resolve
    # subject/object refs via the local_to_committed map.
    atom_a["id"] = "local-a"
    atom_b["id"] = "local-b"

    out_dir = workspace / "dispatch" / "outputs" / f"extractor-{'k' * 64}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "output.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    # Both atoms should have committed (they're valid).
    assert len(result.atoms_committed) == 2, (
        f"expected 2 atoms committed, got {result.atoms_committed!r}; errors={result.errors!r}"
    )
    # AT LEAST one clarification was raised — the contested warrant.
    assert len(result.clarifications_raised) >= 1, (
        f"expected >= 1 clarification, got {result.clarifications_raised!r}"
    )

    # Find the open clarification(s) on disk and confirm at least one is
    # the warrant-defensibility-contested variant.
    contested_found = False
    for clar_id in result.clarifications_raised:
        clar_path = substrate.clarification_path(source_id, clar_id, resolved=False)
        assert clar_path.is_file(), f"clarification not on disk: {clar_path}"
        clar = parse_clarification_md(clar_path.read_text(encoding="utf-8"))
        if clar.raised_by_activity == "warrant-defensibility-contested":
            contested_found = True
            # context_refs should reference an atom id (the from/to of
            # the contested relation, which the reconciler resolved
            # through local_to_committed).
            assert clar.context_refs, "warrant-contested clarification must carry context_refs"
            # The committed atoms should appear as the relation endpoints.
            committed = set(result.atoms_committed)
            assert any(ref in committed for ref in clar.context_refs), (
                f"context_refs {clar.context_refs!r} should overlap committed atoms {committed!r}"
            )
            # Question text mentions the contested warrant.
            assert "contested" in clar.question.lower(), (
                f"question should mention contested status: {clar.question!r}"
            )
    assert contested_found, (
        f"no warrant-defensibility-contested clarification found; "
        f"raised ids: {result.clarifications_raised!r}"
    )
