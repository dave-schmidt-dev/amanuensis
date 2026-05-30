"""Content-addressable ID computation for substrate artifacts.

Every content-addressable model (``Atom``, ``Relation``,
``ProvenanceRecord``, ``Clarification``, ``IterationDirective``) has a
deterministic id = hash of its canonical-form content. The canonical
form:

1. **Drops the ``id`` field itself** (chicken-and-egg).
2. **Drops fields explicitly marked volatile** — observational metadata
   about the record's lifecycle or outbound pointers, NOT part of the
   record's identity. Each content-addressable model declares its
   per-class volatile set as
   ``_VOLATILE_FIELDS: ClassVar[frozenset[str]]``. The hasher always
   adds ``id`` to the drop set on top of that.
3. **Sorts mapping keys lexicographically** (recursively, deepest
   first).
4. **Encodes datetimes as ISO-8601 UTC with microsecond precision and
   a ``Z`` suffix.** Naive datetimes are rejected — the schema layer's
   ``AwareDatetime`` constraint guarantees we never reach the hasher
   with one, but the check is defensive.
5. **Encodes floats with ``repr()``** (Python's shortest round-trip
   string). The float becomes a JSON string, not a JSON number, in the
   canonical encoding — this is deliberate: hashing is a closed loop
   (we hash, we never round-trip back to a model from canonical form),
   and ``repr()`` is the only stdlib float formatter that guarantees a
   shortest, lossless decimal representation. NaN and Inf are
   rejected; canonical JSON does not represent them.
6. **Encodes as canonical JSON** (UTF-8, no whitespace, ``\\u``-escape
   non-ASCII, ``sort_keys=True``, ``allow_nan=False``).

The hash is the first 16 hex chars (8 bytes) of the SHA-256 of the
canonical-form bytes, prefixed by the record-kind letter:

- ``a-`` for ``Atom``
- ``r-`` for ``Relation``
- ``p-`` for ``ProvenanceRecord``
- ``c-`` for ``Clarification``
- ``i-`` for ``IterationDirective``
- ``m-`` for ``SourceMirrorManifest``

Collision discipline: 8-byte truncation gives ~2^32 records before
birthday-collision risk approaches 50%, well above any realistic
single-engagement corpus. Tests assert no collisions in fixture
corpora; production discovery of a collision triggers a governance
event (lengthen the truncation).

Per-model volatile-field sets (rationale in ``docs/schema-reference.md``):

- ``Atom``: ``{"provenance_id"}``
- ``Relation``: ``{"provenance_id"}``
- ``ProvenanceRecord``: ``set()``
- ``Clarification``: ``{"status", "resolved_at", "resolved_by",
  "resolution", "raised_provenance_id", "resolved_provenance_id"}``
- ``IterationDirective``: ``{"applied_at", "applied_by",
  "applied_outcome", "issued_provenance_id",
  "applied_provenance_id"}``
- ``SourceMirrorManifest``: ``set()``

The "lifecycle-completion" volatile fields on ``Clarification`` /
``IterationDirective`` (``status``, ``resolved_*``, ``applied_*``)
exist so that resolving a clarification or applying an iteration does
NOT change the artifact's content-addressable id — the open and
resolved states are the same artifact, with the resolution recorded
via paired provenance records (see plan §4 and INV-3).

Plan §4 "Content-addressable ID computation" is the authoritative spec.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pydantic import BaseModel

# Kind-letter prefix per content-addressable type.
# Keyed by ``type(model).__name__`` so the hasher does not import the
# concrete model classes at module load time (avoids an import cycle:
# the schemas import this module to declare ``_VOLATILE_FIELDS``).
_KIND_PREFIX: dict[str, str] = {
    "Atom": "a-",
    "Relation": "r-",
    "ProvenanceRecord": "p-",
    "Clarification": "c-",
    "IterationDirective": "i-",
    "SourceMirrorManifest": "m-",
}

# Universally-volatile field (always dropped from canonical form, on
# every content-addressable type).
_UNIVERSAL_VOLATILE: frozenset[str] = frozenset({"id"})


def compute_id(model: BaseModel) -> str:
    """Compute the content-addressable id of a substrate artifact.

    Args:
        model: A Pydantic ``BaseModel`` instance of one of the six
            content-addressable types (``Atom``, ``Relation``,
            ``ProvenanceRecord``, ``Clarification``,
            ``IterationDirective``, ``SourceMirrorManifest``). Each
            declares a class attribute
            ``_VOLATILE_FIELDS: ClassVar[frozenset[str]]`` enumerating
            the fields to drop from its canonical form. The ``id``
            field itself is always dropped (chicken-and-egg).

    Returns:
        The id string: ``"<kind-letter>-<16 hex chars>"``.

    Raises:
        ValueError: if ``type(model)`` is not a registered content-
            addressable type (e.g. ``ReplayLogEntry``, ``Vocabulary``).
        ValueError: if any float field contains NaN or Inf.
        ValueError: if any datetime field is naive (no tzinfo).
    """
    cls = type(model)
    cls_name = cls.__name__
    prefix = _KIND_PREFIX.get(cls_name)
    if prefix is None:
        raise ValueError(
            f"{cls_name} is not a content-addressable substrate type; "
            f"compute_id() only accepts Atom, Relation, ProvenanceRecord, "
            f"Clarification, IterationDirective, SourceMirrorManifest"
        )
    _empty: frozenset[str] = frozenset()
    per_class_raw: Any = getattr(cls, "_VOLATILE_FIELDS", _empty)
    per_class_volatile: frozenset[str] = frozenset(cast("frozenset[str]", per_class_raw))
    top_level_drops: frozenset[str] = _UNIVERSAL_VOLATILE | per_class_volatile
    payload: dict[str, Any] = model.model_dump(mode="python")
    canonical: Any = _to_canonical(payload, top_level_drops=top_level_drops)
    encoded = _canonical_json(canonical)
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    return f"{prefix}{digest}"


def _to_canonical(
    value: Any,
    top_level_drops: frozenset[str] | None = None,
) -> Any:
    """Recursively normalize a dumped Pydantic payload into canonical form.

    - Drops ``top_level_drops`` keys at the OUTERMOST mapping only. The
      drop set is identity-scoped to the top-level record, not its
      nested mappings (a nested ``AgentAttribution`` happens to use no
      colliding names today, but the explicit scoping is the right
      contract).
    - Sorts mapping keys lexicographically at every level.
    - Converts tuples to lists (JSON has no tuple type).
    - Renders ``datetime`` as ISO-8601 UTC microsecond with ``Z`` suffix.
    - Renders ``float`` via ``repr()``, after rejecting NaN/Inf.
    - Leaves ``int``, ``bool``, ``str``, ``None`` untouched.
    """
    if isinstance(value, dict):
        # Pydantic model_dump produces ``dict[str, Any]`` keys; we type
        # the iteration explicitly so pyright strict is happy.
        mapping = cast("dict[str, Any]", value)
        result: dict[str, Any] = {}
        for k in sorted(mapping.keys()):
            if top_level_drops is not None and k in top_level_drops:
                continue
            # Nested levels: no further drops; identity-volatile fields
            # are scoped to the top-level record.
            result[k] = _to_canonical(mapping[k], top_level_drops=None)
        return result
    if isinstance(value, list):
        seq_list = cast("list[Any]", value)
        return [_to_canonical(item, top_level_drops=None) for item in seq_list]
    if isinstance(value, tuple):
        seq_tup = cast("tuple[Any, ...]", value)
        return [_to_canonical(item, top_level_drops=None) for item in seq_tup]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime cannot be canonicalized; "
                "AwareDatetime should have prevented this at the schema layer"
            )
        utc = value.astimezone(UTC)
        # Microsecond precision; explicit Z suffix (consistent format).
        return utc.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    if isinstance(value, bool):
        # Must precede the float check: bool is a subclass of int, and
        # ``True``/``False`` are also instances of int. JSON true/false
        # is fine — pass through as-is.
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"non-finite float cannot be canonicalized: {value!r}")
        # repr for shortest round-trip; emitted as a JSON STRING in
        # canonical form (closed-loop hashing; see module docstring).
        return repr(value)
    return value


def _canonical_json(value: Any) -> bytes:
    """Encode a canonical-form payload as canonical JSON bytes.

    ``sort_keys=True`` is belt-and-suspenders — ``_to_canonical`` already
    sorts. ``ensure_ascii=True`` produces ``\\u``-escapes for non-ASCII.
    ``separators=(",", ":")`` strips whitespace. ``allow_nan=False``
    rejects NaN/Inf at the JSON layer in case anything leaked past
    ``_to_canonical``.
    """
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
