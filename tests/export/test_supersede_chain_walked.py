"""T9.5 — CV-9: static-export consumer walks the entity supersede chain.

Surface contract: every export-side surface that displays entity ids
must call ``latest_entity_for`` to canonicalize, so superseded ids
never leak to the exported HTML.

The ``merged_entity_workspace`` fixture (defined in conftest.py) plants:
  - ``entity_A`` (kind=organization, canonical_name="Old Corp", superseded by entity_B)
  - ``entity_B`` (kind=organization, canonical_name="New Corp", canonical)
  - ``atom`` with kind=entity operand value "Old Corp"
  - ``resolution_R`` whose on-disk ``entity_id`` == entity_A's id
  - ``EntitySupersede(A → B)``
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from amanuensis.export import export_static_html
from amanuensis.fs import Substrate

_MERGE_SOURCE_ID = "src-merge"
_FROZEN_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _export(workspace: Path, tmp_path: Path, *, include_mappings: bool = True) -> str:
    """Helper: export and return rendered HTML text."""
    substrate = Substrate(workspace)
    out = tmp_path / "report.html"
    export_static_html(
        substrate=substrate,
        source_id=_MERGE_SOURCE_ID,
        output_path=out,
        include_mappings=include_mappings,
        now=_FROZEN_NOW,
    )
    return out.read_text(encoding="utf-8")


def test_sidebar_contains_only_canonical_entity(
    merged_entity_workspace: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    """Sidebar lists only entity_B (canonical); entity_A (superseded) must not appear."""
    workspace, ent_a_id, ent_b_id, _ = merged_entity_workspace
    text = _export(workspace, tmp_path)

    # entity_B's anchor must be present.
    assert f'id="entity-{ent_b_id}"' in text, (
        f"canonical entity_B anchor (id=entity-{ent_b_id}) missing from sidebar"
    )
    # entity_A's anchor must NOT be present (superseded entity excluded).
    assert f'id="entity-{ent_a_id}"' not in text, (
        f"superseded entity_A anchor (id=entity-{ent_a_id}) leaked into sidebar"
    )


def test_inline_annotation_links_canonical(
    merged_entity_workspace: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    """Atom-inline annotation must link to entity_B (canonical), not entity_A (on-disk)."""
    workspace, ent_a_id, ent_b_id, _ = merged_entity_workspace
    text = _export(workspace, tmp_path)

    # The resolved-entity link must point at the canonical id.
    assert f'href="#entity-{ent_b_id}"' in text, (
        f"resolved-entity link should point at canonical entity_B "
        f"(#entity-{ent_b_id}), not superseded entity_A"
    )
    # The superseded id must not appear in any href.
    assert f'href="#entity-{ent_a_id}"' not in text, (
        "superseded entity_A id leaked into resolved-entity href"
    )


def test_superseded_id_absent_from_html_body(
    merged_entity_workspace: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    """Superseded entity_A's id must not appear anywhere in the rendered body."""
    workspace, ent_a_id, _ent_b_id, _ = merged_entity_workspace
    text = _export(workspace, tmp_path)

    # The superseded entity id must not appear in the HTML body surfaces
    # (sidebar anchors, inline annotation hrefs).  It may appear in the
    # embedded JSON sidecar (that is raw on-disk data, not a rendered surface).
    # We check only the <body> portion before any <script> block.
    body_before_scripts = text.split('<script type="application/json"')[0]
    assert ent_a_id not in body_before_scripts, (
        f"superseded entity_A id ({ent_a_id}) leaked into rendered HTML body "
        "(before embedded JSON scripts)"
    )


def test_sidebar_absent_does_not_leak_superseded(
    merged_entity_workspace: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    """With include_mappings=False, no entity ids appear in the rendered body."""
    workspace, ent_a_id, ent_b_id, _ = merged_entity_workspace
    text = _export(workspace, tmp_path, include_mappings=False)

    body_before_scripts = text.split('<script type="application/json"')[0]
    assert ent_a_id not in body_before_scripts
    assert ent_b_id not in body_before_scripts
    assert '<aside class="entity-sidebar">' not in text


@pytest.mark.parametrize("include_mappings", [True, False])
def test_export_purity_with_merged_entity(
    merged_entity_workspace: tuple[Path, str, str, str],
    tmp_path: Path,
    include_mappings: bool,
) -> None:
    """Byte-identical output across two runs for merged-entity workspace."""
    workspace, _, _, _ = merged_entity_workspace
    substrate = Substrate(workspace)
    out1 = tmp_path / "run1.html"
    out2 = tmp_path / "run2.html"
    kwargs = {
        "substrate": substrate,
        "source_id": _MERGE_SOURCE_ID,
        "include_mappings": include_mappings,
        "now": _FROZEN_NOW,
    }
    export_static_html(output_path=out1, **kwargs)  # type: ignore[arg-type]
    export_static_html(output_path=out2, **kwargs)  # type: ignore[arg-type]
    assert out1.read_bytes() == out2.read_bytes()
