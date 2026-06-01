"""INV-18 — Probandum.scheme is in the pinned Walton-scheme snapshot.

Walks every Probandum under ``mappings/probanda/`` and verifies its
``scheme`` field appears in the per-engagement snapshot. Catches
records that bypassed the substrate write gate (e.g., manually
authored YAML).

The helper re-runs the INV-18 gate by attempting to re-add every
probandum on disk via ``Substrate.add_probandum`` (which enforces the
gate). For valid records the re-add is a no-op (idempotency); for
records whose scheme is absent from the snapshot the gate raises
``WaltonSchemeGateViolation``. If the snapshot itself is missing,
``SubstrateNotFound`` fires before the per-scheme check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from amanuensis.fs import (
    Substrate,
    SubstrateNotFound,
    WaltonSchemeGateViolation,
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
) -> Probandum:
    """Build a Probandum with a real content-addressable id."""
    draft = Probandum(
        id="p-" + "0" * 16,
        statement=statement,
        kind=kind,
        scheme=scheme,
        alternatives_considered=[],
        confidence="high",
        provenance_id="p-fixture-inv18-prob",
        role_attributions=[role_attribution],
        schema_version=1,
    )
    real_id = compute_id(draft)
    return Probandum(
        id=real_id,
        statement=statement,
        kind=kind,
        scheme=scheme,
        alternatives_considered=[],
        confidence="high",
        provenance_id="p-fixture-inv18-prob",
        role_attributions=[role_attribution],
        schema_version=1,
    )


def _plant_probandum(workspace: Path, probandum: Probandum) -> None:
    """Write a Probandum YAML+md directly, bypassing the substrate gate."""
    path = workspace / "mappings" / "probanda" / f"{probandum.id}.md"
    atomic_write_text(path, serialize_probandum_md(probandum))


@pytest.fixture
def tmp_workspace_inv18_clean(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """Workspace with the snapshot pinned and a probandum whose scheme is in it."""
    _make_marker(tmp_path, "inv18-clean")
    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()
    sub.add_probandum(_probandum(role_attribution))
    return tmp_path


@pytest.fixture
def tmp_workspace_inv18_unknown_scheme(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """Workspace with a snapshot + a manually planted probandum whose scheme is absent."""
    _make_marker(tmp_path, "inv18-unknown-scheme")
    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()
    # Bypass the substrate gate by writing the file directly with a
    # scheme that is NOT in the seed catalogue.
    rogue = _probandum(role_attribution, scheme="argument-from-pure-fabrication")
    _plant_probandum(tmp_path, rogue)
    return tmp_path


@pytest.fixture
def tmp_workspace_inv18_missing_snapshot(tmp_path: Path, role_attribution: RoleAttribution) -> Path:
    """Workspace with a probandum on disk but no Walton-scheme snapshot pinned.

    The probandum is written via direct YAML so it never crosses the
    substrate gate at fixture build time. The INV-18 walker then trips
    on the missing snapshot.
    """
    _make_marker(tmp_path, "inv18-missing-snapshot")
    rogue = _probandum(role_attribution)
    _plant_probandum(tmp_path, rogue)
    return tmp_path


def test_clean_workspace_passes(tmp_workspace_inv18_clean: Path) -> None:
    """A workspace with a snapshot + a valid probandum passes the walk."""
    sub = Substrate(tmp_workspace_inv18_clean)
    _walk_and_check(sub)  # must not raise


def test_unknown_scheme_caught(tmp_workspace_inv18_unknown_scheme: Path) -> None:
    """A probandum whose scheme is absent from the snapshot is rejected."""
    sub = Substrate(tmp_workspace_inv18_unknown_scheme)
    with pytest.raises(WaltonSchemeGateViolation, match="argument-from-pure-fabrication"):
        _walk_and_check(sub)


def test_missing_snapshot_caught(tmp_workspace_inv18_missing_snapshot: Path) -> None:
    """A workspace with probanda on disk but no snapshot raises SubstrateNotFound."""
    sub = Substrate(tmp_workspace_inv18_missing_snapshot)
    with pytest.raises(SubstrateNotFound, match="walton-scheme"):
        _walk_and_check(sub)


def _walk_and_check(sub: Substrate) -> None:
    """Re-run the INV-18 gate on every on-disk probandum.

    For each probandum under ``mappings/probanda/``, calls
    ``sub.add_probandum(p)`` — the substrate enforces INV-18 on every
    write, so tampered records raise ``WaltonSchemeGateViolation`` and
    a missing snapshot raises ``SubstrateNotFound``. Valid records hit
    the idempotent no-op path.
    """
    for probandum in sub.list_probanda():
        sub.add_probandum(probandum)
