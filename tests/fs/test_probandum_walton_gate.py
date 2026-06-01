"""T3.3 — INV-18 substrate-side Walton-scheme gate on add_probandum.

Three cases:
1. Unknown scheme rejected with ``WaltonSchemeGateViolation``.
2. Scheme present in the pinned snapshot is accepted.
3. Missing snapshot raises ``SubstrateNotFound`` with a user-actionable hint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import (
    Substrate,
    SubstrateNotFound,
    WaltonSchemeGateViolation,
)
from amanuensis.schemas import RoleAttribution
from tests.fs.conftest import _probandum_basic_payload


def _ws(tmp_path: Path) -> Substrate:
    (tmp_path / "amanuensis.yaml").write_text("workspace: test\n")
    return Substrate(tmp_path)


def test_add_probandum_rejects_unknown_scheme(
    tmp_path: Path, role_attribution: RoleAttribution
) -> None:
    """A scheme NOT in the pinned snapshot raises WaltonSchemeGateViolation."""
    sub = _ws(tmp_path)
    sub.snapshot_walton_schemes()
    p = _probandum_basic_payload(
        role_attribution,
        scheme="argument-from-pure-fabrication",  # not in catalogue
    )
    with pytest.raises(WaltonSchemeGateViolation, match="argument-from-pure-fabrication"):
        sub.add_probandum(p)


def test_add_probandum_accepts_scheme_in_snapshot(
    tmp_path: Path, role_attribution: RoleAttribution
) -> None:
    """A scheme in the pinned snapshot is accepted (default seed value passes)."""
    sub = _ws(tmp_path)
    sub.snapshot_walton_schemes()
    p = _probandum_basic_payload(
        role_attribution,
        scheme="argument-from-expert-opinion",  # in the seed catalogue
    )
    written = sub.add_probandum(p)
    assert written.is_file()


def test_add_probandum_raises_substrate_not_found_when_no_snapshot(
    tmp_path: Path, role_attribution: RoleAttribution
) -> None:
    """Adding a probandum without a snapshot raises SubstrateNotFound."""
    sub = _ws(tmp_path)
    # No snapshot taken.
    p = _probandum_basic_payload(role_attribution)
    with pytest.raises(SubstrateNotFound, match="walton-scheme"):
        sub.add_probandum(p)


def test_add_probandum_gate_uses_cache_after_first_read(
    tmp_path: Path, role_attribution: RoleAttribution
) -> None:
    """After a successful add, the substrate's cache holds the snapshot.

    Removing the snapshot file from disk after a first successful add
    must NOT block the next add — the cache satisfies the gate. This
    documents the cache contract and exercises the invalidation path.
    """
    sub = _ws(tmp_path)
    sub.snapshot_walton_schemes()
    p1 = _probandum_basic_payload(role_attribution, statement="First probandum.")
    sub.add_probandum(p1)
    # Cache is populated now. Delete the file to verify cache is used.
    sub.walton_scheme_snapshot_path().unlink()
    p2 = _probandum_basic_payload(role_attribution, statement="Second probandum.")
    sub.add_probandum(p2)  # must not raise


def test_snapshot_rewrite_invalidates_cache(
    tmp_path: Path, role_attribution: RoleAttribution
) -> None:
    """Calling snapshot_walton_schemes clears the cache (re-read on next gate).

    If the cache were not invalidated, a freshly-pinned snapshot would
    not be consulted until process restart — defeating the per-engagement
    snapshot discipline.
    """
    sub = _ws(tmp_path)
    sub.snapshot_walton_schemes()
    p1 = _probandum_basic_payload(role_attribution, statement="Cache-priming add.")
    sub.add_probandum(p1)  # priming
    assert sub._walton_snapshot_cache is not None  # pyright: ignore[reportPrivateUsage]
    # Idempotent re-snapshot still invalidates the cache (simplest contract).
    sub.snapshot_walton_schemes()
    assert sub._walton_snapshot_cache is None  # pyright: ignore[reportPrivateUsage]
