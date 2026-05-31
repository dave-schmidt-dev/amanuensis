"""Gate test for the shipped ``vocabularies/generic/entity-kinds.yaml`` template (PM-5).

Asserts the template loads cleanly as YAML, exposes the canonical 9 kind
ids, and every kind declares at least one resolution rule. Distinct from
``tests/vocabulary/test_entity_registry.py`` (which exercises the
Pydantic loader): this test is a pure-YAML structural gate so a
malformed template trips even if the Pydantic loader regresses.
"""

from __future__ import annotations

from pathlib import Path

import yaml

TEMPLATE = Path(__file__).parent.parent.parent / "vocabularies" / "generic" / "entity-kinds.yaml"

EXPECTED_KIND_IDS = {
    "party",
    "person",
    "organization",
    "instrument",
    "event",
    "statute",
    "case-citation",
    "jurisdiction",
    "concept",
}


def test_template_loadable() -> None:
    payload = yaml.safe_load(TEMPLATE.read_text())
    assert "kinds" in payload


def test_nine_kinds_present() -> None:
    payload = yaml.safe_load(TEMPLATE.read_text())
    ids = {entry["id"] for entry in payload["kinds"]}
    assert ids == EXPECTED_KIND_IDS


def test_every_kind_has_rules() -> None:
    payload = yaml.safe_load(TEMPLATE.read_text())
    for entry in payload["kinds"]:
        assert isinstance(entry.get("resolution_rules"), list)
        assert len(entry["resolution_rules"]) >= 1
