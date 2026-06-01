"""INV-19 — Non-ultimate probanda require non-empty ``alternatives_considered``.

Walks every Probandum under ``mappings/probanda/`` and verifies that
records with ``kind in {"penultimate", "interim"}`` have at least one
entry in ``alternatives_considered`` (Analysis of Competing Hypotheses
discipline). ``ultimate`` probanda are exempt — they ARE the alternative
the corpus picks between. Catches records that bypassed the substrate
write gate (e.g., manually authored YAML).

The helper re-runs the INV-19 gate by attempting to re-add every on-disk
probandum via ``Substrate.add_probandum`` (which enforces the gate). For
valid records the re-add is a no-op (idempotency); for non-ultimate
records with empty ``alternatives_considered`` the gate raises
``AchAlternativesGateViolation``.

Companion surface tests at ``tests/fs/test_probandum_io.py`` exercise the
write-time gate directly; this parametric walker covers the audit-time
half (records that skipped the substrate writer entirely).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from amanuensis.fs import (
    AchAlternativesGateViolation,
    Substrate,
)
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import serialize_probandum_md
from amanuensis.schemas import RoleAttribution, compute_id
from amanuensis.schemas.probandum import Probandum

pytestmark = pytest.mark.invariants


def _make_marker(workspace: Path, project_name: str) -> None:
    marker = workspace / "amanuensis.yaml"
    marker.write_text(
        f"schema_version: 1\nproject_name: {project_name}\n",
        encoding="utf-8",
    )


def _probandum(
    role_attribution: RoleAttribution,
    *,
    statement: str = "ACME breached the contract by failing to pay.",
    scheme: str = "argument-from-expert-opinion",
    kind: Literal["ultimate", "penultimate", "interim"] = "ultimate",
    alternatives_considered: list[str] | None = None,
) -> Probandum:
    """Build a Probandum with a real content-addressable id.

    Default ``alternatives_considered`` is ``[]`` (legal for
    ``ultimate``; callers building penultimate / interim records must
    pass a non-empty list to clear the INV-19 ACH gate at write-time).
    """
    alts = alternatives_considered if alternatives_considered is not None else []
    draft = Probandum(
        id="p-" + "0" * 16,
        statement=statement,
        kind=kind,
        scheme=scheme,
        alternatives_considered=alts,
        confidence="high",
        provenance_id="p-fixture-inv19-prob",
        role_attributions=[role_attribution],
        schema_version=1,
    )
    real_id = compute_id(draft)
    return Probandum(
        id=real_id,
        statement=statement,
        kind=kind,
        scheme=scheme,
        alternatives_considered=alts,
        confidence="high",
        provenance_id="p-fixture-inv19-prob",
        role_attributions=[role_attribution],
        schema_version=1,
    )


def _plant_probandum(workspace: Path, probandum: Probandum) -> None:
    """Write a Probandum YAML+md directly, bypassing the substrate gate."""
    path = workspace / "mappings" / "probanda" / f"{probandum.id}.md"
    atomic_write_text(path, serialize_probandum_md(probandum))


# --- Fixtures ---------------------------------------------------------


@pytest.fixture
def tmp_workspace_inv19_clean(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """Workspace with one ultimate + one penultimate + one interim, all valid.

    The ultimate carries ``alternatives_considered=[]`` (explicitly
    exempt); the penultimate and interim each carry a non-empty
    alternatives list. All three records are written via the substrate
    so the snapshot + write-time gate cooperate.
    """
    _make_marker(tmp_path, "inv19-clean")
    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()
    sub.add_probandum(_probandum(role_attribution, statement="Ultimate.", kind="ultimate"))
    sub.add_probandum(
        _probandum(
            role_attribution,
            statement="Penultimate.",
            kind="penultimate",
            alternatives_considered=["competing-hypothesis-A"],
        )
    )
    sub.add_probandum(
        _probandum(
            role_attribution,
            statement="Interim.",
            kind="interim",
            alternatives_considered=["competing-hypothesis-B"],
        )
    )
    return tmp_path


@pytest.fixture
def tmp_workspace_inv19_planted_penultimate_empty(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace with a planted penultimate probandum whose alternatives are empty.

    The probandum is written directly to disk so it never crosses the
    substrate gate at fixture build time. The INV-19 walker then trips
    on the empty ``alternatives_considered`` list at re-add.
    """
    _make_marker(tmp_path, "inv19-planted-pen-empty")
    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()
    rogue = _probandum(
        role_attribution,
        statement="Planted penultimate.",
        kind="penultimate",
        alternatives_considered=[],
    )
    _plant_probandum(tmp_path, rogue)
    del sub  # written via direct YAML, not the substrate
    return tmp_path


@pytest.fixture
def tmp_workspace_inv19_planted_interim_empty(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace with a planted interim probandum whose alternatives are empty."""
    _make_marker(tmp_path, "inv19-planted-interim-empty")
    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()
    rogue = _probandum(
        role_attribution,
        statement="Planted interim.",
        kind="interim",
        alternatives_considered=[],
    )
    _plant_probandum(tmp_path, rogue)
    del sub
    return tmp_path


@pytest.fixture
def tmp_workspace_inv19_mixed_valid(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """Workspace with a mix of valid ultimate / penultimate / interim records.

    Five probanda total: two ultimates (empty alternatives), two
    penultimates (non-empty), one interim (non-empty). All written via
    the substrate so the on-disk set is a known-good baseline. The
    parametric walker re-checks each via the substrate gate to catch
    drift if a future refactor breaks the audit-time half of INV-19.
    """
    _make_marker(tmp_path, "inv19-mixed-valid")
    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()
    sub.add_probandum(_probandum(role_attribution, statement="Ultimate A.", kind="ultimate"))
    sub.add_probandum(_probandum(role_attribution, statement="Ultimate B.", kind="ultimate"))
    sub.add_probandum(
        _probandum(
            role_attribution,
            statement="Penultimate A.",
            kind="penultimate",
            alternatives_considered=["alt-A1", "alt-A2"],
        )
    )
    sub.add_probandum(
        _probandum(
            role_attribution,
            statement="Penultimate B.",
            kind="penultimate",
            alternatives_considered=["alt-B1"],
        )
    )
    sub.add_probandum(
        _probandum(
            role_attribution,
            statement="Interim.",
            kind="interim",
            alternatives_considered=["alt-I1"],
        )
    )
    return tmp_path


# --- Tests ------------------------------------------------------------


def test_clean_workspace_passes(tmp_workspace_inv19_clean: Path) -> None:
    """A workspace with one of each valid kind passes the INV-19 walk."""
    sub = Substrate(tmp_workspace_inv19_clean)
    _walk_and_check(sub)  # must not raise


def test_planted_penultimate_empty_alternatives_caught(
    tmp_workspace_inv19_planted_penultimate_empty: Path,
) -> None:
    """A planted penultimate with empty alternatives_considered is rejected."""
    sub = Substrate(tmp_workspace_inv19_planted_penultimate_empty)
    with pytest.raises(AchAlternativesGateViolation, match="alternatives_considered"):
        _walk_and_check(sub)


def test_planted_interim_empty_alternatives_caught(
    tmp_workspace_inv19_planted_interim_empty: Path,
) -> None:
    """A planted interim with empty alternatives_considered is rejected."""
    sub = Substrate(tmp_workspace_inv19_planted_interim_empty)
    with pytest.raises(AchAlternativesGateViolation, match="alternatives_considered"):
        _walk_and_check(sub)


def test_ultimate_with_empty_alternatives_passes(
    tmp_path: Path, role_attribution: RoleAttribution
) -> None:
    """An ultimate probandum with empty alternatives_considered is exempt."""
    _make_marker(tmp_path, "inv19-ultimate-exempt")
    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()
    sub.add_probandum(
        _probandum(
            role_attribution,
            statement="Lone ultimate.",
            kind="ultimate",
            alternatives_considered=[],
        )
    )
    _walk_and_check(sub)  # must not raise


def test_mixed_valid_workspace_walk_passes(
    tmp_workspace_inv19_mixed_valid: Path,
) -> None:
    """A workspace with a mix of valid probanda passes the parametric walk.

    Verifies the audit-time half of the gate: every non-ultimate
    probandum on disk has a non-empty ``alternatives_considered`` list,
    and ``ultimate`` records are accepted regardless of that list.
    Re-adds via ``Substrate.add_probandum`` to exercise the same code
    path a future drift would trip.
    """
    sub = Substrate(tmp_workspace_inv19_mixed_valid)
    probanda = list(sub.list_probanda())
    # Sanity: the fixture planted five records.
    assert len(probanda) == 5
    # Audit-time invariant: every non-ultimate has at least one alternative.
    for p in probanda:
        if p.kind in ("penultimate", "interim"):
            assert len(p.alternatives_considered) >= 1, (
                f"INV-19 drift: {p.kind} probandum {p.id} has empty alternatives_considered on disk"
            )
    # And the substrate gate accepts every record (idempotent re-add).
    _walk_and_check(sub)


def _walk_and_check(sub: Substrate) -> None:
    """Re-run the INV-19 gate on every on-disk probandum.

    For each probandum under ``mappings/probanda/``, calls
    ``sub.add_probandum(p)`` — the substrate enforces INV-19 on every
    write, so tampered records (non-ultimate with empty
    ``alternatives_considered``) raise ``AchAlternativesGateViolation``.
    Valid records hit the idempotent no-op path.
    """
    for probandum in sub.list_probanda():
        sub.add_probandum(probandum)
