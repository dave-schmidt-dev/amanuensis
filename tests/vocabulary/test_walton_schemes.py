"""Tests for the Walton-scheme vocabulary loader (Phase 2c M3.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.vocabulary.walton_schemes import (
    WaltonScheme,
    WaltonSchemeRegistry,
    WaltonSchemeRegistryError,
    load_walton_schemes,
)

TEMPLATE = Path(__file__).parent.parent.parent / "vocabularies" / "generic" / "walton-schemes.yaml"


def test_load_generic_catalogue() -> None:
    """Load the seed generic catalogue — must yield exactly 7 schemes."""
    registry = load_walton_schemes(TEMPLATE)
    assert isinstance(registry, WaltonSchemeRegistry)
    assert registry.version == 1
    assert len(registry.schemes) == 7
    assert all(isinstance(s, WaltonScheme) for s in registry.schemes)


def test_has_scheme_finds_seed_entries() -> None:
    """``has_scheme`` returns True for every seed entry."""
    registry = load_walton_schemes(TEMPLATE)
    expected = {
        "argument-from-expert-opinion",
        "argument-from-witness-testimony",
        "argument-from-temporal-correlation",
        "argument-from-cluster-heuristic",
        "argument-from-precedent",
        "argument-from-analogy",
        "argument-from-sign",
    }
    for name in expected:
        assert registry.has_scheme(name) is True, f"missing seed scheme: {name!r}"


def test_has_scheme_returns_false_for_unknown() -> None:
    """``has_scheme`` returns False for a name not in the registry."""
    registry = load_walton_schemes(TEMPLATE)
    assert registry.has_scheme("argument-from-pure-fabrication") is False
    assert registry.has_scheme("") is False


def test_rejects_malformed_yaml(tmp_path: Path) -> None:
    """A YAML file that fails Pydantic validation raises WaltonSchemeRegistryError."""
    bad = tmp_path / "broken.yaml"
    bad.write_text("version: 1\n", encoding="utf-8")  # missing 'schemes'
    with pytest.raises(WaltonSchemeRegistryError):
        load_walton_schemes(bad)


def test_rejects_unparseable_yaml(tmp_path: Path) -> None:
    """A file that fails YAML parsing raises WaltonSchemeRegistryError."""
    bad = tmp_path / "broken.yaml"
    bad.write_text(": : : not yaml\n", encoding="utf-8")
    with pytest.raises(WaltonSchemeRegistryError):
        load_walton_schemes(bad)


def test_file_not_found_wrapped(tmp_path: Path) -> None:
    """A missing file raises WaltonSchemeRegistryError."""
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(WaltonSchemeRegistryError):
        load_walton_schemes(missing)
