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
