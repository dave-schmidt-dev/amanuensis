"""Smoke tests for the static-HTML export stub (M9.1).

The export is a stub: it stitches the source-mirror manifest + atoms +
relations into one self-contained HTML file. These tests verify the
file-shape contract that Phase 4's audit-HTML bundle will rebuild on
top of:

- The file exists, is chmod 0o644, and parses as HTML at least to the
  extent of containing ``<!DOCTYPE html>`` and the source_id.
- The three ``<script type="application/json">`` blocks
  (``paragraphs-data`` / ``atoms-data`` / ``relations-data``) are
  present and their bodies parse as JSON.
- The file is self-contained — no CDN URLs are baked into the output.
- The CLI command surface (``amanuensis export <source-id>``) works
  end-to-end with ``typer.testing.CliRunner``.
- Exporting a distillation with a manifest but no atoms produces a
  valid file (empty atoms section).
"""

from __future__ import annotations

import json
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.export import export_static_html
from amanuensis.fs import Substrate
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    OperandRef,
    OperandTypeSchema,
    ParagraphEntry,
    ProvenanceRecord,
    RoleAttribution,
    SourceMirrorManifest,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)

SOURCE_ID = "export-fixture-src"

runner = CliRunner()


# --- Fixtures ---------------------------------------------------------


@pytest.fixture
def export_workspace(tmp_path: Path) -> Path:
    """An empty tmpdir with the INV-1 marker."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: export-test\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def export_substrate(export_workspace: Path) -> Substrate:
    return Substrate(export_workspace)


def _build_vocabulary() -> Vocabulary:
    return Vocabulary(
        name="export-test-vocab",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall"],
                operand_types=[
                    OperandTypeSchema(name="subject", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="export-test entry",
            ),
        ],
    )


def _plant_manifest(substrate: Substrate, source_id: str) -> SourceMirrorManifest:
    """Plant a minimal valid SourceMirrorManifest under ``source_id``."""
    deterministic_hex = "0" * 64
    prov_id = "p-" + "1" * 16
    paragraphs = [
        ParagraphEntry(
            paragraph_id="p-0000",
            paragraph_index=0,
            section_path=["Preamble"],
            label="text",
            page_no=1,
            char_count=42,
            content_sha256=deterministic_hex,
        ),
        ParagraphEntry(
            paragraph_id="p-0001",
            paragraph_index=1,
            section_path=["Part I"],
            label="text",
            page_no=1,
            char_count=58,
            content_sha256=deterministic_hex,
        ),
    ]
    common: dict[str, Any] = {
        "source_id": source_id,
        "source_filename": "example.pdf",
        "source_sha256": deterministic_hex,
        "source_bytes_len": 1024,
        "ingest_engine": "docling",
        "ingest_engine_version": "9.9.9",
        "vocabulary_snapshot_sha256": deterministic_hex,
        "provenance_id": prov_id,
        "paragraphs": paragraphs,
        "schema_version": 1,
    }
    draft = SourceMirrorManifest(id="m-" + "0" * 16, **common)
    manifest = SourceMirrorManifest(id=compute_id(draft), **common)
    substrate.add_source_mirror_manifest(source_id, manifest)
    # Plant per-paragraph .md files so the body-rendering path is exercised.
    from amanuensis.fs._atomic import atomic_write_text
    from amanuensis.fs._serialize import serialize_paragraph_md

    bodies = {
        "p-0000": "First paragraph body text.",
        "p-0001": "Second paragraph body text.",
    }
    for entry in paragraphs:
        path = substrate.paragraph_path(source_id, entry.paragraph_id)
        atomic_write_text(path, serialize_paragraph_md(entry, bodies[entry.paragraph_id]))
    return manifest


def _plant_atom(substrate: Substrate, source_id: str) -> tuple[Atom, ProvenanceRecord]:
    """Plant one atom + its provenance + a vocabulary snapshot under ``source_id``."""
    vocab = _build_vocabulary()
    substrate.snapshot_vocabulary(source_id, vocab)

    agent = AgentAttribution(kind="llm", identifier="test-model", role="extractor")
    role_attribution = RoleAttribution(
        agent=agent,
        activity="proposed",
        at=datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
    )
    operand = OperandRef(role="subject", kind="entity", value="ent-acme", type_hint=None)

    atom_payload: dict[str, Any] = {
        "source_id": source_id,
        "section_path": ["Part I", "§1"],
        "paragraph_index": 0,
        "sentence_index": None,
        "char_span": (0, 30),
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [operand],
        "narrative": "ACME shall pay within 30 days.",
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


# --- Helpers ----------------------------------------------------------


def _extract_json_block(text: str, block_id: str) -> Any:
    """Extract and parse a ``<script type="application/json" id="...">`` block."""
    pattern = re.compile(
        r'<script type="application/json" id="' + re.escape(block_id) + r'">\s*(.*?)\s*</script>',
        re.DOTALL,
    )
    match = pattern.search(text)
    assert match is not None, f"json block {block_id!r} not found in output"
    # Reverse the ``</`` → ``<\/`` escape that the renderer applies for
    # defense against ``</script`` injection.
    raw = match.group(1).replace("<\\/", "</")
    return json.loads(raw)


# --- Tests ------------------------------------------------------------


def test_export_produces_self_contained_html(
    export_workspace: Path,
    export_substrate: Substrate,
    tmp_path: Path,
) -> None:
    """Smoke: manifest + atom planted → export writes a valid HTML file."""
    _plant_manifest(export_substrate, SOURCE_ID)
    atom, _ = _plant_atom(export_substrate, SOURCE_ID)

    output_path = tmp_path / "out" / "export.html"
    written = export_static_html(
        substrate=export_substrate,
        source_id=SOURCE_ID,
        output_path=output_path,
    )

    assert written == output_path
    assert output_path.is_file()
    # Mode 0644 — the export is meant to be shared.
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o644

    text = output_path.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    assert SOURCE_ID in text
    assert atom.narrative in text
    # The three JSON sidecar blocks must be present and parse cleanly.
    paragraphs_data: list[dict[str, Any]] = _extract_json_block(text, "paragraphs-data")
    atoms_data: list[dict[str, Any]] = _extract_json_block(text, "atoms-data")
    relations_data: list[dict[str, Any]] = _extract_json_block(text, "relations-data")
    assert isinstance(paragraphs_data, list)
    assert isinstance(atoms_data, list)
    assert isinstance(relations_data, list)
    assert len(paragraphs_data) == 2
    assert len(atoms_data) == 1
    assert atoms_data[0]["id"] == atom.id


def test_export_no_external_cdn(
    export_workspace: Path,
    export_substrate: Substrate,
    tmp_path: Path,
) -> None:
    """Self-containment: no CDN URLs in the rendered output."""
    _plant_manifest(export_substrate, SOURCE_ID)
    _plant_atom(export_substrate, SOURCE_ID)

    output_path = tmp_path / "export.html"
    export_static_html(
        substrate=export_substrate,
        source_id=SOURCE_ID,
        output_path=output_path,
    )

    text = output_path.read_text(encoding="utf-8")
    # The renderer should never reach for an external resource. Phase 1
    # is offline-first; Phase 4 may add an opt-in CDN mode but the stub
    # is strictly self-contained.
    forbidden_hosts = (
        "unpkg.com",
        "cdn.jsdelivr.net",
        "cdnjs.cloudflare.com",
        "googleapis.com",
        "gstatic.com",
        "jsdelivr.net",
    )
    for host in forbidden_hosts:
        assert host not in text, f"CDN reference to {host!r} leaked into export"
    # Catch any stray http:// / https:// resource link as a belt-and-braces
    # measure. The renderer's only ``http``-looking string is inside CSS
    # comments or attribute values it controls; if a real link slips in
    # this fails loudly.
    assert "https://" not in text, "no external https:// URL should appear in the export"
    assert "http://" not in text, "no external http:// URL should appear in the export"


def test_export_cli_command_succeeds(
    export_workspace: Path,
    export_substrate: Substrate,
    tmp_path: Path,
) -> None:
    """End-to-end: ``amanuensis export <source-id> --output ...`` exits 0."""
    _plant_manifest(export_substrate, SOURCE_ID)
    _plant_atom(export_substrate, SOURCE_ID)

    output_path = tmp_path / "cli-export.html"
    result = runner.invoke(
        app,
        [
            "export",
            SOURCE_ID,
            "--output",
            str(output_path),
            "--workspace",
            str(export_workspace),
        ],
    )
    assert result.exit_code == 0, (
        f"export CLI failed (exit={result.exit_code})\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert output_path.is_file()
    assert "wrote" in result.stdout
    # Sanity: the file shape matches the in-process export.
    text = output_path.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    assert SOURCE_ID in text


def test_export_renders_with_no_atoms(
    export_workspace: Path,
    export_substrate: Substrate,
    tmp_path: Path,
) -> None:
    """Empty-atoms case: manifest present, zero atoms, export still succeeds."""
    _plant_manifest(export_substrate, SOURCE_ID)
    # NB: no atom planted; no vocabulary snapshot needed because the
    # export reads atoms directly off disk via Substrate.list_atoms,
    # which simply yields nothing.

    output_path = tmp_path / "empty-atoms.html"
    written = export_static_html(
        substrate=export_substrate,
        source_id=SOURCE_ID,
        output_path=output_path,
    )

    assert written.is_file()
    text = written.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    # Empty-atoms placeholder; copy mirrors _render_atoms.
    assert "No atoms extracted" in text
    atoms_data = _extract_json_block(text, "atoms-data")
    assert atoms_data == []


# --- T9.1: --include-mappings CLI flag tests --------------------------


def test_export_include_mappings_default_on(
    export_workspace: Path,
    export_substrate: Substrate,
    tmp_path: Path,
) -> None:
    """Default behavior includes mappings flag (exit 0, file produced)."""
    _plant_manifest(export_substrate, SOURCE_ID)
    _plant_atom(export_substrate, SOURCE_ID)

    output_path = tmp_path / "default-mappings.html"
    result = runner.invoke(
        app,
        [
            "export",
            SOURCE_ID,
            "--output",
            str(output_path),
            "--workspace",
            str(export_workspace),
        ],
    )
    assert result.exit_code == 0, (
        f"export CLI failed (exit={result.exit_code})\nstdout: {result.stdout}"
    )
    assert output_path.is_file()
    # Functional assertion (sidebar present) verified in T9.2.


def test_export_no_include_mappings_disables(
    export_workspace: Path,
    export_substrate: Substrate,
    tmp_path: Path,
) -> None:
    """--no-include-mappings flag is accepted and exits 0."""
    _plant_manifest(export_substrate, SOURCE_ID)
    _plant_atom(export_substrate, SOURCE_ID)

    output_path = tmp_path / "no-mappings.html"
    result = runner.invoke(
        app,
        [
            "export",
            SOURCE_ID,
            "--output",
            str(output_path),
            "--workspace",
            str(export_workspace),
            "--no-include-mappings",
        ],
    )
    assert result.exit_code == 0, (
        f"export CLI failed (exit={result.exit_code})\nstdout: {result.stdout}"
    )
    assert output_path.is_file()
    # Functional assertion (sidebar absent) verified in T9.2.


# --- T9.2: Entity sidebar rendering tests ----------------------------


def test_sidebar_with_mappings(
    populated_mappings_workspace: Path,
    tmp_path: Path,
) -> None:
    """Sidebar appears with entity canonical_name when include_mappings=True."""
    substrate = Substrate(populated_mappings_workspace)
    out = tmp_path / "report.html"
    export_static_html(
        substrate=substrate,
        source_id="export-m9-src",
        output_path=out,
        include_mappings=True,
    )
    text = out.read_text(encoding="utf-8")
    assert '<aside class="entity-sidebar">' in text
    assert "ACME" in text


def test_sidebar_absent_without_mappings_flag(
    populated_mappings_workspace: Path,
    tmp_path: Path,
) -> None:
    """Sidebar is absent when include_mappings=False."""
    substrate = Substrate(populated_mappings_workspace)
    out = tmp_path / "report.html"
    export_static_html(
        substrate=substrate,
        source_id="export-m9-src",
        output_path=out,
        include_mappings=False,
    )
    text = out.read_text(encoding="utf-8")
    assert '<aside class="entity-sidebar">' not in text


def test_empty_state_when_mappings_empty(
    empty_mappings_workspace: Path,
    tmp_path: Path,
) -> None:
    """Empty-state message rendered when mappings/entities/ is absent."""
    substrate = Substrate(empty_mappings_workspace)
    out = tmp_path / "report.html"
    export_static_html(
        substrate=substrate,
        source_id="export-m9-src",
        output_path=out,
        include_mappings=True,
    )
    text = out.read_text(encoding="utf-8")
    assert "No mappings yet" in text


# --- T9.3: Inline resolution annotation tests ------------------------


def test_inline_annotation_when_resolved(
    resolved_atom_workspace: Path,
    tmp_path: Path,
) -> None:
    """Resolved entity operand renders as <a href="#entity-..."> link."""
    substrate = Substrate(resolved_atom_workspace)
    out = tmp_path / "resolved.html"
    export_static_html(
        substrate=substrate,
        source_id="export-m9-src",
        output_path=out,
        include_mappings=True,
    )
    text = out.read_text(encoding="utf-8")
    assert 'class="resolved-entity"' in text
    assert 'href="#entity-' in text


def test_no_inline_annotation_with_flag_off(
    resolved_atom_workspace: Path,
    tmp_path: Path,
) -> None:
    """With include_mappings=False, resolved operand is NOT wrapped in <a>."""
    substrate = Substrate(resolved_atom_workspace)
    out = tmp_path / "no-mappings.html"
    export_static_html(
        substrate=substrate,
        source_id="export-m9-src",
        output_path=out,
        include_mappings=False,
    )
    text = out.read_text(encoding="utf-8")
    assert 'class="resolved-entity"' not in text


def test_unresolved_operand_renders_plain_span(
    unresolved_atom_workspace: Path,
    tmp_path: Path,
) -> None:
    """Unresolved kind=entity operand renders as <span class="unresolved-entity">."""
    substrate = Substrate(unresolved_atom_workspace)
    out = tmp_path / "unresolved.html"
    export_static_html(
        substrate=substrate,
        source_id="export-m9-src",
        output_path=out,
        include_mappings=True,
    )
    text = out.read_text(encoding="utf-8")
    assert 'class="unresolved-entity"' in text
    assert 'class="resolved-entity"' not in text
