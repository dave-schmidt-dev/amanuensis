"""T2.1 — Substrate.add_probandum filesystem write + ACH alternatives gate.

Covers:
- ``add_probandum`` writes to ``mappings/probanda/<id>.md``.
- Idempotent on byte-identical content (INV-13).
- Raises ``MutationOfImmutableRecord`` on diverging non-volatile content.
- ACH alternatives gate: ``kind in {"penultimate","interim"}`` requires
  ``len(alternatives_considered) >= 1``; ``ultimate`` accepts empty.

INV-18 (closed Walton scheme vocabulary) is deferred to M3; ``scheme``
is accepted as any string here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import (
    AchAlternativesGateViolation,
    MutationOfImmutableRecord,
    Substrate,
)
from amanuensis.schemas import RoleAttribution
from tests.fs.conftest import _probandum_basic_payload


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


def test_add_probandum_writes_to_mappings_probanda(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p = _probandum_basic_payload(role_attribution)
    sub.add_probandum(p)
    path = tmp_workspace / "mappings" / "probanda" / f"{p.id}.md"
    assert path.is_file()


def test_add_probandum_is_idempotent(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p = _probandum_basic_payload(role_attribution)
    sub.add_probandum(p)
    # Second write with identical content must not raise; exactly one file
    # must exist on disk.
    sub.add_probandum(p)
    probanda_dir = tmp_workspace / "mappings" / "probanda"
    files = [f for f in probanda_dir.iterdir() if f.is_file() and f.suffix == ".md"]
    assert len(files) == 1


def test_add_probandum_raises_on_diverging_content(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Tampered on-disk content with same id triggers INV-13."""
    sub = _new(tmp_workspace)
    p = _probandum_basic_payload(role_attribution)
    sub.add_probandum(p)
    path = tmp_workspace / "mappings" / "probanda" / f"{p.id}.md"
    # Append a manual edit so the existing bytes differ from canonical.
    path.write_text(path.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8")
    with pytest.raises(MutationOfImmutableRecord):
        sub.add_probandum(p)


def test_rejects_empty_alternatives_on_penultimate(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p = _probandum_basic_payload(
        role_attribution,
        kind="penultimate",
        alternatives_considered=[],
    )
    with pytest.raises(AchAlternativesGateViolation):
        sub.add_probandum(p)


def test_rejects_empty_alternatives_on_interim(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p = _probandum_basic_payload(
        role_attribution,
        kind="interim",
        alternatives_considered=[],
    )
    with pytest.raises(AchAlternativesGateViolation):
        sub.add_probandum(p)


def test_accepts_empty_alternatives_on_ultimate(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p = _probandum_basic_payload(
        role_attribution,
        kind="ultimate",
        alternatives_considered=[],
    )
    sub.add_probandum(p)  # no raise
    assert (tmp_workspace / "mappings" / "probanda" / f"{p.id}.md").is_file()
