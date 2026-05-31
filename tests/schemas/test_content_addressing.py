"""Tests for ``amanuensis.schemas._hashing.compute_id``.

Coverage:

1. Determinism: ``compute_id(model) == compute_id(model)`` across calls
   on the same input. No salt, no randomness.
2. Equivalence: two models built from the same payload — but with
   nested-dict-key reorderings in the payload — produce the same id.
   Property-tested with ``hypothesis`` over 500+ generated Atoms
   (satisfies the M1.5 "500+ generated cases" requirement).
3. Distinct content: changing any identity-carrying field changes the
   id. Spot-checked across all five content-addressable types.
4. Volatility: changing only volatile fields does NOT change the id.
   Spot-checked across all five types per the per-class
   ``_VOLATILE_FIELDS`` declaration.
5. Collision-sweep: ~20 distinct fixture-corpus instances produce ~20
   unique ids; no collisions.
6. Rejection of non-content-addressable types
   (``ReplayLogEntry``, ``Vocabulary``, ``VocabularyEntry``,
   ``OperandTypeSchema``).
7. Rejection of NaN / Inf floats in canonical form.
8. Rejection of naive datetimes in canonical form (defensive — the
   schemas already use ``AwareDatetime``, but the hasher's check is
   explicit).
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    Clarification,
    IterationDirective,
    OperandTypeSchema,
    ProvenanceRecord,
    Relation,
    ReplayLogEntry,
    SourceMirrorManifest,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)
from amanuensis.schemas._hashing import _KIND_PREFIX, _to_canonical

# --- 1. Determinism ----------------------------------------------------


def test_compute_id_is_deterministic_atom(atom: Atom) -> None:
    a = compute_id(atom)
    b = compute_id(atom)
    c = compute_id(atom)
    assert a == b == c
    assert a.startswith("a-")
    assert len(a) == len("a-") + 16


def test_compute_id_is_deterministic_relation(relation: Relation) -> None:
    assert compute_id(relation) == compute_id(relation)
    assert compute_id(relation).startswith("r-")


def test_compute_id_is_deterministic_provenance(provenance: ProvenanceRecord) -> None:
    assert compute_id(provenance) == compute_id(provenance)
    assert compute_id(provenance).startswith("p-")


def test_compute_id_is_deterministic_clarification(clarification: Clarification) -> None:
    assert compute_id(clarification) == compute_id(clarification)
    assert compute_id(clarification).startswith("c-")


def test_compute_id_is_deterministic_iteration(iteration: IterationDirective) -> None:
    assert compute_id(iteration) == compute_id(iteration)
    assert compute_id(iteration).startswith("i-")


# --- 2. Equivalence: nested mapping reordering --------------------------


def _shuffle_dict_keys(value: Any) -> Any:
    """Return a deep copy of value with all mapping key orders reversed.

    Reversing is a deterministic permutation that is guaranteed to
    differ from sorted order for any dict with >=2 keys. Lists are
    preserved in order (list order is semantic in JSON).
    """
    if isinstance(value, dict):
        mapping = cast("dict[str, Any]", value)
        keys: list[str] = list(mapping.keys())
        # Reverse the key order so the dict literal differs from the
        # original (and from sorted order, for >=2 keys).
        return {k: _shuffle_dict_keys(mapping[k]) for k in reversed(keys)}
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return [_shuffle_dict_keys(item) for item in items]
    return value


# Hypothesis strategies for Atom payloads.
# We build a strategy that generates a VALID Atom payload-dict.
# Then we test that compute_id(Atom(**payload)) == compute_id(Atom(**reordered_payload)).

_LITERAL_KIND = st.sampled_from(["claim", "data", "qualifier", "rebuttal"])
_LITERAL_SCALE = st.sampled_from(["sentence", "paragraph", "section", "document"])
_LITERAL_QUAL = st.sampled_from(["high", "medium", "low", "contested"])
_LITERAL_ROLE = st.sampled_from(
    [
        "extractor",
        "auditor",
        "contrarian",
        "constructive",
        "premortem",
        "human_supervisor",
    ]
)
_LITERAL_AGENT_KIND = st.sampled_from(["human", "llm"])
_LITERAL_OPERAND_KIND = st.sampled_from(["entity", "literal", "doc_span"])

# Narrow ASCII text — we don't need full unicode for property purposes;
# the canonical-form correctness on unicode is covered separately.
_TEXT = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    min_size=1,
    max_size=20,
)
_IDENT = st.from_regex(r"[a-z][a-z0-9_-]{0,15}", fullmatch=True)


@st.composite
def _agent_payload(draw: st.DrawFn) -> dict[str, Any]:
    return {
        "kind": draw(_LITERAL_AGENT_KIND),
        "identifier": draw(_IDENT),
        "role": draw(_LITERAL_ROLE),
    }


@st.composite
def _role_attribution_payload(draw: st.DrawFn) -> dict[str, Any]:
    when = draw(
        st.datetimes(
            min_value=datetime(2000, 1, 1),
            max_value=datetime(2100, 12, 31),
            timezones=st.just(UTC),
        )
    )
    return {
        "agent": draw(_agent_payload()),
        "activity": draw(_TEXT),
        "at": when,
    }


@st.composite
def _operand_payload(draw: st.DrawFn) -> dict[str, Any]:
    return {
        "role": draw(_IDENT),
        "kind": draw(_LITERAL_OPERAND_KIND),
        "value": draw(_TEXT),
        "type_hint": draw(st.one_of(st.none(), _TEXT)),
    }


@st.composite
def _atom_payload_strategy(draw: st.DrawFn) -> dict[str, Any]:
    span_start = draw(st.integers(min_value=0, max_value=1000))
    span_end = draw(st.integers(min_value=span_start + 1, max_value=span_start + 5000))
    kind = draw(_LITERAL_KIND)
    has_qualifier = draw(st.booleans())
    return {
        "id": "a-stub",  # will be ignored by compute_id (universal volatile)
        "source_id": draw(_IDENT),
        "section_path": draw(st.lists(_TEXT, min_size=0, max_size=4)),
        "paragraph_index": draw(st.integers(min_value=0, max_value=10_000)),
        "sentence_index": draw(st.one_of(st.none(), st.integers(min_value=0, max_value=10_000))),
        "char_span": (span_start, span_end),
        "scale_anchor": draw(_LITERAL_SCALE),
        "kind": kind,
        "predicate": draw(_IDENT),
        "operands": draw(st.lists(_operand_payload(), min_size=0, max_size=3)),
        "narrative": draw(_TEXT),
        "qualifier_level": draw(_LITERAL_QUAL) if has_qualifier else None,
        "qualifier_basis": draw(_TEXT) if has_qualifier else None,
        "provenance_id": draw(_IDENT),
        "role_attributions": draw(st.lists(_role_attribution_payload(), min_size=1, max_size=3)),
        "schema_version": 1,
    }


@given(payload=_atom_payload_strategy())
@settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_compute_id_equivalent_payloads_produce_equal_ids(payload: dict[str, Any]) -> None:
    """Property: equivalent content (modulo dict-key order) → equal ids.

    Build the Atom twice, the second time from a payload whose nested
    mapping key orders are reversed. The two Atoms must hash equal.

    Hypothesis runs this ``max_examples=500`` times, satisfying M1.5's
    "500+ generated cases" requirement.
    """
    atom_a = Atom(**payload)
    reordered = cast("dict[str, Any]", _shuffle_dict_keys(payload))
    atom_b = Atom(**reordered)
    assert compute_id(atom_a) == compute_id(atom_b)


# --- 3. Distinct content → distinct ids --------------------------------


def test_distinct_atom_content_produces_distinct_ids(atom: Atom) -> None:
    a1 = atom
    a2 = atom.model_copy(update={"narrative": atom.narrative + " EDITED"})
    assert compute_id(a1) != compute_id(a2)


def test_distinct_relation_content_produces_distinct_ids(relation: Relation) -> None:
    r1 = relation
    r2 = relation.model_copy(update={"warrant": relation.warrant + " EDITED"})
    assert compute_id(r1) != compute_id(r2)


def test_distinct_provenance_content_produces_distinct_ids(
    provenance: ProvenanceRecord,
) -> None:
    p1 = provenance
    p2 = provenance.model_copy(update={"activity": provenance.activity + "_v2"})
    assert compute_id(p1) != compute_id(p2)


def test_distinct_clarification_content_produces_distinct_ids(
    clarification: Clarification,
) -> None:
    c1 = clarification
    c2 = clarification.model_copy(update={"question": clarification.question + " EDITED"})
    assert compute_id(c1) != compute_id(c2)


def test_distinct_iteration_content_produces_distinct_ids(
    iteration: IterationDirective,
) -> None:
    i1 = iteration
    i2 = iteration.model_copy(update={"directive": iteration.directive + " EDITED"})
    assert compute_id(i1) != compute_id(i2)


# --- 4. Volatility: changes to volatile fields do NOT change the id ---


def test_atom_provenance_id_is_volatile(atom: Atom) -> None:
    a1 = atom
    a2 = atom.model_copy(update={"provenance_id": "prov-DIFFERENT-1234567"})
    assert compute_id(a1) == compute_id(a2)


def test_relation_provenance_id_is_volatile(relation: Relation) -> None:
    r1 = relation
    r2 = relation.model_copy(update={"provenance_id": "prov-DIFFERENT-1234567"})
    assert compute_id(r1) == compute_id(r2)


def test_clarification_lifecycle_fields_are_volatile(
    clarification: Clarification,
    agent: AgentAttribution,
) -> None:
    """Resolving a clarification does NOT change its content-addressable id."""
    c_open = clarification
    c_resolved = clarification.model_copy(
        update={
            "status": "resolved",
            "resolved_at": datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC),
            "resolved_by": agent,
            "resolution": "ACME is the parent corp.",
            "resolved_provenance_id": "p-resolution-record-1234",
        }
    )
    assert compute_id(c_open) == compute_id(c_resolved)


def test_iteration_lifecycle_fields_are_volatile(
    iteration: IterationDirective,
    human_agent: AgentAttribution,
) -> None:
    """Applying a directive does NOT change its content-addressable id."""
    i_issued = iteration
    i_applied = iteration.model_copy(
        update={
            "applied_at": datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC),
            "applied_by": human_agent,
            "applied_outcome": "Re-extracted §3 with stricter qualifier discipline.",
            "applied_provenance_id": "p-application-record-1234",
        }
    )
    assert compute_id(i_issued) == compute_id(i_applied)


# --- 5. Collision-sweep over a small fixture corpus -------------------


def test_collision_sweep_atoms_no_duplicates(atom_payload: dict[str, Any]) -> None:
    """Build ~20 distinct valid Atom instances; assert all ids are unique."""
    corpus: list[Atom] = []
    for i in range(20):
        p = dict(atom_payload)
        p["narrative"] = f"Variation {i}."
        corpus.append(Atom(**p))
    ids = [compute_id(a) for a in corpus]
    assert len(set(ids)) == len(ids), f"collisions detected in 20-atom corpus: {ids}"


def test_collision_sweep_across_kinds(
    atom: Atom,
    relation: Relation,
    provenance: ProvenanceRecord,
    clarification: Clarification,
    iteration: IterationDirective,
) -> None:
    """One of each content-addressable kind. Ids are unique (and prefixes distinct)."""
    # Build a minimal valid SourceMirrorManifest fixture inline so the sweep
    # covers the ``m-`` prefix (the sixth content-addressable kind added in
    # M3.1). Trivial valid values: 64-hex deterministic sha256 strings,
    # zero-length source bytes, empty paragraph list, deterministic
    # provenance id.
    deterministic_hex = "0" * 64
    manifest = SourceMirrorManifest(
        id="m-" + "0" * 16,
        source_id="sweep-test",
        source_filename="sweep.pdf",
        source_sha256=deterministic_hex,
        source_bytes_len=0,
        ingest_engine="docling",
        ingest_engine_version="0.0.0",
        vocabulary_snapshot_sha256=deterministic_hex,
        provenance_id="p-test1234567890ab",
        paragraphs=[],
        schema_version=1,
    )
    ids = {
        compute_id(atom),
        compute_id(relation),
        compute_id(provenance),
        compute_id(clarification),
        compute_id(iteration),
        compute_id(manifest),
    }
    assert len(ids) == 6
    prefixes = {id_[0] for id_ in ids}
    assert prefixes == {"a", "r", "p", "c", "i", "m"}


# --- 6. Non-content-addressable types raise ValueError ----------------


def test_replay_log_entry_rejected(replay_log_entry: ReplayLogEntry) -> None:
    with pytest.raises(ValueError, match="not a content-addressable substrate type"):
        compute_id(replay_log_entry)


def test_vocabulary_rejected(vocabulary: Vocabulary) -> None:
    with pytest.raises(ValueError, match="not a content-addressable substrate type"):
        compute_id(vocabulary)


def test_vocabulary_entry_rejected(vocabulary_entry: VocabularyEntry) -> None:
    with pytest.raises(ValueError, match="not a content-addressable substrate type"):
        compute_id(vocabulary_entry)


def test_operand_type_schema_rejected(operand_type_schema: OperandTypeSchema) -> None:
    with pytest.raises(ValueError, match="not a content-addressable substrate type"):
        compute_id(operand_type_schema)


# --- 7. NaN/Inf rejection in canonical form ---------------------------


def test_canonical_form_rejects_nan() -> None:
    with pytest.raises(ValueError, match="non-finite float"):
        _to_canonical({"x": math.nan})


def test_canonical_form_rejects_inf() -> None:
    with pytest.raises(ValueError, match="non-finite float"):
        _to_canonical({"x": math.inf})


def test_canonical_form_rejects_neg_inf() -> None:
    with pytest.raises(ValueError, match="non-finite float"):
        _to_canonical({"x": -math.inf})


# --- 8. Naive datetime rejection in canonical form --------------------


def test_canonical_form_rejects_naive_datetime() -> None:
    naive = datetime(2026, 5, 29, 12, 0, 0)  # tz-naive
    with pytest.raises(ValueError, match="naive datetime"):
        _to_canonical({"t": naive})


def test_canonical_form_accepts_aware_datetime_non_utc() -> None:
    """tz-aware non-UTC datetime is normalized to UTC, not rejected."""
    plus2 = timezone(timedelta(hours=2))
    when = datetime(2026, 5, 29, 14, 30, 45, 123456, tzinfo=plus2)
    out_raw = _to_canonical({"t": when})
    out = cast("dict[str, Any]", out_raw)
    s = cast("str", out["t"])
    assert isinstance(s, str)
    assert s.endswith("Z")
    # The datetime is 14:30:45.123456 +02:00 → UTC 12:30:45.123456
    assert s == "2026-05-29T12:30:45.123456Z"


# --- 9. Canonical form contract sanity checks -------------------------


def test_canonical_form_drops_id_universally(atom_payload: dict[str, Any]) -> None:
    """Changing only ``id`` must not change the hash."""
    a1 = Atom(**atom_payload)
    other_payload = dict(atom_payload)
    other_payload["id"] = "a-some-other-stub"
    a2 = Atom(**other_payload)
    assert compute_id(a1) == compute_id(a2)


def test_canonical_form_sorts_nested_dict_keys() -> None:
    """Confirm ``_to_canonical`` recursively sorts dict keys."""
    canonical_raw = _to_canonical({"b": {"y": 1, "x": 2}, "a": 3})
    canonical = cast("dict[str, Any]", canonical_raw)
    assert list(canonical.keys()) == ["a", "b"]
    nested = cast("dict[str, Any]", canonical["b"])
    assert list(nested.keys()) == ["x", "y"]


def test_canonical_form_preserves_list_order() -> None:
    """List order is semantic in JSON; ``_to_canonical`` must preserve it."""
    canonical = _to_canonical([3, 1, 2])
    assert canonical == [3, 1, 2]


def test_canonical_form_normalizes_tuple_to_list() -> None:
    canonical = _to_canonical((1, 2, 3))
    assert canonical == [1, 2, 3]


def test_canonical_form_float_to_repr_string() -> None:
    canonical = _to_canonical(1.5)
    assert canonical == "1.5"
    assert isinstance(canonical, str)


# --- Phase 2a: Entity Resolution kind-prefix registration ----------------


def test_phase2a_kind_prefixes_registered() -> None:
    assert _KIND_PREFIX["Entity"] == "e-"
    assert _KIND_PREFIX["Resolution"] == "j-"
    assert _KIND_PREFIX["ResolutionSupersede"] == "s-"
    assert _KIND_PREFIX["EntitySupersede"] == "t-"
