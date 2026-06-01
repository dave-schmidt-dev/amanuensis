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
from amanuensis.schemas import ProbandumSupersede, RoleAttribution
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


# --- T2.2: list_probanda with composable filters ---------------------


def test_list_probanda_filters_by_kind(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p_ult = _probandum_basic_payload(role_attribution, kind="ultimate")
    p_pen = _probandum_basic_payload(
        role_attribution,
        kind="penultimate",
        statement="Penultimate node A.",
        alternatives_considered=["alt-1"],
    )
    p_int = _probandum_basic_payload(
        role_attribution,
        kind="interim",
        statement="Interim node B.",
        alternatives_considered=["alt-2"],
    )
    sub.add_probandum(p_ult)
    sub.add_probandum(p_pen)
    sub.add_probandum(p_int)

    only_pen = list(sub.list_probanda(kind="penultimate"))
    assert len(only_pen) == 1
    assert only_pen[0].id == p_pen.id


def test_list_probanda_filters_by_scheme(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p1 = _probandum_basic_payload(role_attribution, scheme="argument-from-expert-opinion")
    p2 = _probandum_basic_payload(
        role_attribution,
        statement="Different statement so id differs.",
        scheme="argument-from-analogy",
    )
    sub.add_probandum(p1)
    sub.add_probandum(p2)

    result = list(sub.list_probanda(scheme="argument-from-analogy"))
    assert len(result) == 1
    assert result[0].id == p2.id


def test_list_probanda_lists_all(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    sub = _new(tmp_workspace)
    p1 = _probandum_basic_payload(role_attribution, statement="First.")
    p2 = _probandum_basic_payload(role_attribution, statement="Second.")
    sub.add_probandum(p1)
    sub.add_probandum(p2)

    all_p = list(sub.list_probanda())
    assert {p.id for p in all_p} == {p1.id, p2.id}


def test_list_probanda_respects_limit(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p1 = _probandum_basic_payload(role_attribution, statement="A.")
    p2 = _probandum_basic_payload(role_attribution, statement="B.")
    p3 = _probandum_basic_payload(role_attribution, statement="C.")
    sub.add_probandum(p1)
    sub.add_probandum(p2)
    sub.add_probandum(p3)

    limited = list(sub.list_probanda(limit=2))
    assert len(limited) == 2


def test_list_probanda_empty_when_no_dir(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    assert list(sub.list_probanda()) == []


# --- T2.5: supersede methods + chain-walking -------------------------


def _probandum_supersede(
    role_attribution: RoleAttribution,
    old: object,
    new: object,
    **overrides: object,
) -> ProbandumSupersede:
    from datetime import UTC, datetime

    from amanuensis.schemas import compute_id as _compute_id

    payload: dict[str, object] = {
        "id": "u-" + "0" * 16,
        "supersedes_id": old.id,  # type: ignore[attr-defined]
        "superseded_by_id": new.id,  # type: ignore[attr-defined]
        "kind": "probandum",
        "reason": "Supervisor refined the statement.",
        "provenance_id": "p-fixture-psup-001",
        "role_attributions": [role_attribution],
        "at": datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC),
        "schema_version": 1,
    }
    payload.update(overrides)
    draft = ProbandumSupersede(**payload)  # type: ignore[arg-type]
    payload["id"] = _compute_id(draft)
    return ProbandumSupersede(**payload)  # type: ignore[arg-type]


def test_add_probandum_supersede_writes_to_supersedes_dir(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p_old = _probandum_basic_payload(role_attribution, statement="Initial proposition.")
    p_new = _probandum_basic_payload(role_attribution, statement="Refined proposition.")
    sub.add_probandum(p_old)
    sub.add_probandum(p_new)
    sup = _probandum_supersede(role_attribution, p_old, p_new)
    sub.add_probandum_supersede(sup)

    path = tmp_workspace / "mappings" / "supersedes" / f"{sup.id}.yaml"
    assert path.is_file()
    assert sup.id.startswith("u-")


def test_add_probandum_supersede_is_idempotent(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p_old = _probandum_basic_payload(role_attribution, statement="Initial.")
    p_new = _probandum_basic_payload(role_attribution, statement="Refined.")
    sub.add_probandum(p_old)
    sub.add_probandum(p_new)
    sup = _probandum_supersede(role_attribution, p_old, p_new)
    sub.add_probandum_supersede(sup)
    sub.add_probandum_supersede(sup)  # must not raise
    sup_dir = tmp_workspace / "mappings" / "supersedes"
    files = [f for f in sup_dir.iterdir() if f.is_file() and f.name.startswith("u-")]
    assert len(files) == 1


def test_latest_probandum_for_returns_terminus(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    p_old = _probandum_basic_payload(role_attribution, statement="Initial.")
    p_new = _probandum_basic_payload(role_attribution, statement="Refined.")
    sub.add_probandum(p_old)
    sub.add_probandum(p_new)
    sup = _probandum_supersede(role_attribution, p_old, p_new)
    sub.add_probandum_supersede(sup)

    # Walking from the superseded id returns the replacement.
    got = sub.latest_probandum_for(p_old.id)
    assert got is not None
    assert got.id == p_new.id

    # Walking from the replacement (no further supersede) returns itself.
    got2 = sub.latest_probandum_for(p_new.id)
    assert got2 is not None
    assert got2.id == p_new.id


def test_latest_probandum_for_returns_none_for_unknown_id(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    assert sub.latest_probandum_for("p-nonexistent00000") is None


def test_list_supersedes_unfiltered_yields_probandum_kind(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """``list_supersedes`` without filter must yield ``u-`` records."""
    sub = _new(tmp_workspace)
    p_old = _probandum_basic_payload(role_attribution, statement="A.")
    p_new = _probandum_basic_payload(role_attribution, statement="B.")
    sub.add_probandum(p_old)
    sub.add_probandum(p_new)
    sup = _probandum_supersede(role_attribution, p_old, p_new)
    sub.add_probandum_supersede(sup)

    listed = list(sub.list_supersedes())
    assert len(listed) == 1
    assert listed[0].id == sup.id


def test_list_supersedes_kind_probandum_filter(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """``kind='probandum'`` returns only ProbandumSupersede records."""
    sub = _new(tmp_workspace)
    p_old = _probandum_basic_payload(role_attribution, statement="A.")
    p_new = _probandum_basic_payload(role_attribution, statement="B.")
    sub.add_probandum(p_old)
    sub.add_probandum(p_new)
    sup = _probandum_supersede(role_attribution, p_old, p_new)
    sub.add_probandum_supersede(sup)

    listed = list(sub.list_supersedes(kind="probandum"))
    assert len(listed) == 1
    assert isinstance(listed[0], ProbandumSupersede)
    assert listed[0].id == sup.id
