"""Tests for ``scale_anchor`` (INV-6 enforcement)."""

from __future__ import annotations

import pytest

from amanuensis.schemas import Atom
from amanuensis.validators import scale_anchor
from tests.validators._types import AtomFactory


@pytest.mark.parametrize(
    "anchor",
    ["sentence", "paragraph", "section", "document"],
)
def test_scale_anchor_accepts_each_canonical_value(atom_factory: AtomFactory, anchor: str) -> None:
    a = atom_factory(scale_anchor=anchor)
    result = scale_anchor(a)
    assert result.passed is True
    assert result.validator == "scale_anchor"
    assert result.subject_id == a.id


def test_scale_anchor_passes_on_default_fixture(atom: Atom) -> None:
    # The default fixture uses "paragraph"; this is a smoke check that
    # standard fixtures never trip INV-6.
    result = scale_anchor(atom)
    assert result.passed is True


def test_scale_anchor_fails_when_mutated_out_of_band(atom: Atom) -> None:
    # Pydantic prevents constructing an out-of-vocab anchor, so we have
    # to simulate post-construction mutation to exercise the failure
    # branch. ``object.__setattr__`` bypasses the frozen-by-strict guard.
    object.__setattr__(atom, "scale_anchor", "bogus")
    result = scale_anchor(atom)
    assert result.passed is False
    assert "INV-6 violation" in result.reason
    assert "bogus" in result.reason
    assert result.subject_id == atom.id
