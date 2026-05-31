"""Phase-1 backward-compat round-trip test (closes SR-1).

Loads hand-authored v1 fixture records and asserts they validate cleanly
against the current schemas. The only schema that bumped to v2 in Phase 2a
is Clarification (T1.8); its migration is handled by T1.10 / T1.11 and
exercised in test_clarification_migration.py — NOT here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from amanuensis.schemas import Atom, Relation

FIXTURES = Path(__file__).parent.parent / "fixtures" / "phase1-records"


def test_phase1_atom_still_validates() -> None:
    payload = yaml.safe_load((FIXTURES / "atom_v1.yaml").read_text())
    # YAML loads char_span as list; convert to tuple for Pydantic strict mode
    payload["char_span"] = tuple(payload["char_span"])
    a = Atom(**payload)
    assert a.id.startswith("a-")
    assert a.schema_version == 1


def test_phase1_relation_still_validates() -> None:
    payload = yaml.safe_load((FIXTURES / "relation_v1.yaml").read_text())
    r = Relation(**payload)
    assert r.id.startswith("r-")
    assert r.schema_version == 1
