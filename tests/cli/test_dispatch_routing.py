"""Tests for _DEFAULT_ROLE_TO_HARNESS routing (T6.2).

Verifies that the Phase 2a map-roles are registered in the dispatch
CLI's role-to-harness routing table, alongside the Phase 1 extractor
and auditor entries.
"""

from __future__ import annotations

import pytest

from amanuensis.cli.dispatch import _DEFAULT_ROLE_TO_HARNESS  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "role",
    [
        "extractor",
        "auditor",
        "map-resolve",
        "map-audit",
        # Phase 2b M5 — Connector role.
        "connect",
        # Phase 2c M7 — Hierarchize role.
        "hierarchize",
    ],
)
def test_role_routes_to_claude(role: str) -> None:
    """Every expected role routes to the ``claude`` harness."""
    assert role in _DEFAULT_ROLE_TO_HARNESS, f"role {role!r} missing from _DEFAULT_ROLE_TO_HARNESS"
    assert _DEFAULT_ROLE_TO_HARNESS[role] == "claude"


def test_map_resolve_in_table() -> None:
    """map-resolve is explicitly present in the routing table."""
    assert "map-resolve" in _DEFAULT_ROLE_TO_HARNESS


def test_map_audit_in_table() -> None:
    """map-audit is explicitly present in the routing table."""
    assert "map-audit" in _DEFAULT_ROLE_TO_HARNESS


def test_connect_role_in_table() -> None:
    """The Phase 2b Connector role is registered in the routing table.

    The dispatch driver routes by ``entry.role``; ``connect`` is the
    Phase 2b string the orchestrator (M6) will enqueue. Roles missing
    from this table route to failures with reason ``role-unmapped``,
    so the presence assertion is the dispatch-side acceptance test
    for T5.3.
    """
    assert "connect" in _DEFAULT_ROLE_TO_HARNESS
    assert _DEFAULT_ROLE_TO_HARNESS["connect"] == "claude"


def test_hierarchize_role_in_table() -> None:
    """The Phase 2c Hierarchize role is registered in the routing table.

    The dispatch driver routes by ``entry.role``; ``hierarchize`` is
    the Phase 2c string the orchestrator (Phase 2c M8, future) will
    enqueue. Roles missing from this table route to failures with
    reason ``role-unmapped``, so the presence assertion is the
    dispatch-side acceptance test for T7.3.
    """
    assert "hierarchize" in _DEFAULT_ROLE_TO_HARNESS
    assert _DEFAULT_ROLE_TO_HARNESS["hierarchize"] == "claude"
