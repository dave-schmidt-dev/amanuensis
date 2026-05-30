"""M8.3 atom-detail route tests.

Covers:

- 200 + ``<mark>`` highlight of the atom's char_span slice on a planted
  paragraph body.
- 404 for an unknown atom id.

The highlight test plants its OWN atom + paragraph (rather than reusing
``planted_atom_workspace``) so the char_span is controlled by the test
and the assertion against ``<mark>fghijklmno</mark>`` is exact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import serialize_paragraph_md
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    OperandRef,
    OperandTypeSchema,
    ParagraphEntry,
    ProvenanceRecord,
    RoleAttribution,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)
from amanuensis.web.app import create_app

from .conftest import SOURCE_ID

# Width-4 zero-pad mirrors M3.1's ``_PARAGRAPH_ID_WIDTH``. Duplicated in
# the test to keep the test independent of ingest-package internals.
_PARAGRAPH_ID_WIDTH = 4


def _plant_atom_with_paragraph(
    substrate: Substrate,
    source_id: str,
    *,
    paragraph_body: str,
    paragraph_index: int,
    char_span: tuple[int, int],
) -> tuple[Atom, ProvenanceRecord]:
    """Plant an atom + provenance + paragraph file with caller-controlled span.

    Returns the planted (atom, provenance) pair so the test can assert
    against atom.id directly.
    """
    # 1) Vocabulary snapshot (INV-10 prerequisite for any atom write).
    vocab = Vocabulary(
        name="atom-detail-vocab",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=[],
                operand_types=[
                    OperandTypeSchema(name="subject", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="",
            ),
        ],
    )
    substrate.snapshot_vocabulary(source_id, vocab)

    # 2) Paragraph file — written via the same serializer the ingester uses,
    #    so the route's ``parse_paragraph_md`` round-trips cleanly.
    paragraph_id = f"p-{paragraph_index:0{_PARAGRAPH_ID_WIDTH}d}"
    entry = ParagraphEntry(
        paragraph_id=paragraph_id,
        paragraph_index=paragraph_index,
        section_path=["Test"],
        label="text",
        page_no=1,
        char_count=len(paragraph_body),
        content_sha256="0" * 64,
    )
    paragraph_path = substrate.paragraph_path(source_id, paragraph_id)
    atomic_write_text(paragraph_path, serialize_paragraph_md(entry, paragraph_body))

    # 3) Atom + provenance, mirroring tests/web/conftest._plant_atom but
    #    parameterised on ``char_span`` and ``paragraph_index``.
    agent = AgentAttribution(kind="llm", identifier="test-model", role="extractor")
    role_attribution = RoleAttribution(
        agent=agent,
        activity="proposed",
        at=datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
    )
    operand = OperandRef(role="subject", kind="entity", value="ent-acme", type_hint=None)

    atom_payload: dict[str, Any] = {
        "source_id": source_id,
        "section_path": ["Test"],
        "paragraph_index": paragraph_index,
        "sentence_index": None,
        "char_span": char_span,
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [operand],
        "narrative": "test narrative",
        "qualifier_level": None,
        "qualifier_basis": None,
        "provenance_id": "p-" + "0" * 16,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    atom_payload["id"] = "a-" + "0" * 16
    atom_draft = Atom(**atom_payload)
    atom_id = compute_id(atom_draft)

    prov_payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": "atom",
        "entity_id": atom_id,
        "activity": "extract_v1",
        "activity_started_at": datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 30, 12, 0, 1, tzinfo=UTC),
        "used_entity_ids": [source_id],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    prov_draft = ProvenanceRecord(**prov_payload)
    prov_id = compute_id(prov_draft)
    prov_payload["id"] = prov_id
    prov = ProvenanceRecord(**prov_payload)
    substrate.add_provenance(source_id, prov)

    atom_payload["id"] = atom_id
    atom_payload["provenance_id"] = prov_id
    atom = Atom(**atom_payload)
    substrate.add_atom(source_id, atom)
    return atom, prov


def test_atom_detail_with_span_highlight(
    web_workspace: Path, web_substrate: Substrate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The detail page wraps body[5:15] in ``<mark>`` for a known fixture."""
    atom, _prov = _plant_atom_with_paragraph(
        web_substrate,
        SOURCE_ID,
        paragraph_body="abcdefghijklmnopqrst",
        paragraph_index=0,
        char_span=(5, 15),
    )
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    client = TestClient(create_app())
    response = client.get(f"/distillations/{SOURCE_ID}/atoms/{atom.id}")
    assert response.status_code == 200
    body = response.text
    # The exact substring body[5:15] is "fghijklmno". The route emits it
    # inside a <mark> tag (Tailwind class list may follow on the tag, so
    # we look for the inner-text match rather than the literal tag form).
    assert "fghijklmno</mark>" in body
    # And the surrounding text is not inside the mark (proves slicing).
    assert "abcde<mark" in body
    # PROV record id is rendered as plain text.
    assert atom.provenance_id in body
    # Link back to atom browser exists.
    assert f'href="/distillations/{SOURCE_ID}/atoms"' in body


def test_atom_detail_unknown_atom_returns_404(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nonexistent atom id under a real distillation returns 404."""
    workspace, _atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(create_app())
    response = client.get(f"/distillations/{SOURCE_ID}/atoms/a-doesnotexist")
    assert response.status_code == 404
