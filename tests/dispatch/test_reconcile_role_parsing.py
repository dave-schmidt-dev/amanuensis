"""Tests for _parse_output_dir_name role-parsing logic (T6.1).

Covers the four known-role parse paths plus the error branches for
names that cannot be parsed (no hyphen, uppercase hash characters).
The _MAP_ROLE_RE regex handles multi-component map-role names; single-
component roles (extractor / auditor) fall through to the partition path.
"""

from __future__ import annotations

import pytest

from amanuensis.dispatch.reconcile import (
    _parse_output_dir_name,  # pyright: ignore[reportPrivateUsage]
)


@pytest.mark.parametrize(
    "dir_name,expected_role,expected_hash",
    [
        # Phase 1 single-component roles.
        ("extractor-" + "a" * 64, "extractor", "a" * 64),
        ("auditor-" + "b" * 64, "auditor", "b" * 64),
        # Phase 2a map-roles with a hyphen in the role name itself.
        ("map-resolve-" + "c" * 64, "map-resolve", "c" * 64),
        ("map-audit-" + "d" * 64, "map-audit", "d" * 64),
    ],
)
def test_parse_known_roles(dir_name: str, expected_role: str, expected_hash: str) -> None:
    """Known role names parse to the correct (role, hash) pair."""
    role, inputs_hash = _parse_output_dir_name(dir_name)
    assert role == expected_role
    assert inputs_hash == expected_hash


def test_parse_raises_for_no_hyphen() -> None:
    """A dir name with no hyphen at all raises ValueError."""
    with pytest.raises(ValueError, match="no hyphen"):
        _parse_output_dir_name("nohyphenatall")


def test_parse_raises_for_empty_role() -> None:
    """A dir name starting with a hyphen (empty role component) raises ValueError."""
    with pytest.raises(ValueError, match="empty role or hash component"):
        _parse_output_dir_name("-" + "a" * 64)


def test_map_resolve_accepts_any_word_hash() -> None:
    """The map-role regex accepts any non-empty ``\\w+`` hash.

    Production hashes are lowercase hex from SHA-256, but synthetic test
    fixtures use arbitrary repeated chars (``"g" * 64``, ``"A" * 64``)
    for visual identification. The regex is deliberately permissive so
    those parse correctly; the partition-fallback path is reserved for
    single-component (distillation) roles.
    """
    role, inputs_hash = _parse_output_dir_name("map-resolve-" + "A" * 64)
    assert role == "map-resolve"
    assert inputs_hash == "A" * 64
