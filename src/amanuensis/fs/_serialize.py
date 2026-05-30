"""Serialization helpers for substrate artifacts.

Two on-disk formats:

- **Markdown with YAML frontmatter** for artifacts that carry a
  human-readable body (``Atom``, ``Clarification``, ``IterationDirective``).
  The body is the artifact's narrative / question / directive text;
  every other field is YAML frontmatter between ``---`` delimiters.
- **Plain YAML** for record-only artifacts (``Relation``,
  ``ProvenanceRecord``). No frontmatter, no body.

The frontmatter is emitted with ``yaml.safe_dump`` using
``sort_keys=True`` and ``default_flow_style=False`` so the on-disk form
is stable across runs (the canonical-form hash already requires sorted
keys, but the wire format wants block-style block flow for readability).

Pydantic ``model_dump(mode="python")`` returns native Python values
including ``datetime`` and ``tuple``. PyYAML's safe-dumper renders
datetimes as ISO-8601 timestamps and tuples as YAML lists. The safe-
loader inverts both. Round-tripping through Pydantic re-validates and
restores the original types (``tuple`` for ``char_span`` etc.).
"""

from __future__ import annotations

from typing import Any, cast

import yaml
from pydantic import BaseModel

from amanuensis.schemas import (
    Atom,
    Clarification,
    IterationDirective,
    ParagraphEntry,
    ProvenanceRecord,
    Relation,
)

_FRONTMATTER_DELIM = "---"


# --- YAML helpers ----------------------------------------------------


def _safe_dump(payload: dict[str, Any]) -> str:
    """Stable YAML serialization (sorted keys, block flow)."""
    return yaml.safe_dump(
        payload,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )


def _safe_load(text: str) -> dict[str, Any]:
    """Parse YAML; assert the top-level shape is a mapping."""
    loaded = yaml.safe_load(text)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"expected YAML mapping at document root, got {type(loaded).__name__}")
    # pyright can't see through yaml's `Any` return; cast for strictness.
    return cast("dict[str, Any]", loaded)


def serialize_yaml(model: BaseModel) -> str:
    """Serialize a record-only model (Relation, ProvenanceRecord) to YAML."""
    payload = model.model_dump(mode="python")
    return _safe_dump(payload)


# --- Markdown-with-frontmatter helpers --------------------------------


def _split_body(payload: dict[str, Any], body_field: str) -> tuple[dict[str, Any], str]:
    """Split a model payload into (frontmatter_dict, body_text)."""
    body = payload.pop(body_field, "")
    if not isinstance(body, str):
        raise ValueError(f"body field {body_field!r} must be str, got {type(body).__name__}")
    return payload, body


def _emit_md(frontmatter: dict[str, Any], body: str) -> str:
    """Emit ``---\\n<yaml>---\\n<body>\\n`` (trailing newline for POSIX hygiene)."""
    fm_yaml = _safe_dump(frontmatter)
    # Body is written as-is. Ensure a single trailing newline.
    body_text = body if body.endswith("\n") else body + "\n"
    return f"{_FRONTMATTER_DELIM}\n{fm_yaml}{_FRONTMATTER_DELIM}\n{body_text}"


def _parse_md(text: str, body_field: str) -> dict[str, Any]:
    """Parse a frontmatter-bearing markdown file back into a payload dict.

    Reconstructs ``{body_field: <body>}`` from the post-frontmatter body.
    """
    if not text.startswith(_FRONTMATTER_DELIM):
        raise ValueError("frontmatter file must start with '---'")
    # Strip the leading delim line (handle either \n or \r\n endings).
    rest = text[len(_FRONTMATTER_DELIM) :].lstrip("\r\n")
    # Locate the closing delim: a line that is exactly '---'.
    close_idx = _find_closing_delim(rest)
    if close_idx < 0:
        raise ValueError("frontmatter not closed with '---' delimiter")
    fm_text = rest[:close_idx]
    body_text = rest[close_idx + len(_FRONTMATTER_DELIM) :]
    # The body conventionally has one leading newline after the closing
    # ``---``. Strip a single leading newline; preserve interior content.
    if body_text.startswith("\r\n"):
        body_text = body_text[2:]
    elif body_text.startswith("\n"):
        body_text = body_text[1:]
    # Strip exactly one trailing newline (matches ``_emit_md`` discipline).
    if body_text.endswith("\n"):
        body_text = body_text[:-1]
    frontmatter = _safe_load(fm_text)
    frontmatter[body_field] = body_text
    return frontmatter


def _find_closing_delim(text: str) -> int:
    """Return the index of a line equal to ``---``, or -1 if not found.

    The closing delimiter must start a line. We scan line-aware so a
    body containing ``---`` lower down doesn't false-match.
    """
    start = 0
    n = len(text)
    while start < n:
        nl = text.find("\n", start)
        if nl == -1:
            line = text[start:]
            line_end = n
        else:
            line = text[start:nl]
            line_end = nl
        if line.rstrip("\r") == _FRONTMATTER_DELIM:
            return start
        if nl == -1:
            break
        start = line_end + 1
    return -1


# --- Per-model serializers --------------------------------------------


def serialize_atom_md(atom: Atom) -> str:
    payload = atom.model_dump(mode="python")
    frontmatter, body = _split_body(payload, "narrative")
    return _emit_md(frontmatter, body)


def parse_atom_md(text: str) -> Atom:
    payload = _parse_md(text, "narrative")
    # YAML has no tuple type — char_span round-trips as a list. Atom's
    # strict Pydantic config rejects list-where-tuple-expected, so coerce
    # here before validation. Other tuple-typed fields can be added the
    # same way if they show up later.
    cs_raw = payload.get("char_span")
    if isinstance(cs_raw, list):
        cs_list = cast("list[Any]", cs_raw)
        if len(cs_list) == 2:
            payload["char_span"] = (cs_list[0], cs_list[1])
    return Atom(**payload)


def serialize_clarification_md(clarification: Clarification) -> str:
    payload = clarification.model_dump(mode="python")
    frontmatter, body = _split_body(payload, "question")
    return _emit_md(frontmatter, body)


def parse_clarification_md(text: str) -> Clarification:
    return Clarification(**_parse_md(text, "question"))


def serialize_iteration_md(iteration: IterationDirective) -> str:
    payload = iteration.model_dump(mode="python")
    frontmatter, body = _split_body(payload, "directive")
    return _emit_md(frontmatter, body)


def parse_iteration_md(text: str) -> IterationDirective:
    return IterationDirective(**_parse_md(text, "directive"))


def parse_relation_yaml(text: str) -> Relation:
    return Relation(**_safe_load(text))


def parse_provenance_yaml(text: str) -> ProvenanceRecord:
    return ProvenanceRecord(**_safe_load(text))


def serialize_paragraph_md(entry: ParagraphEntry, body: str) -> str:
    """Serialize a paragraph as YAML-frontmatter + body markdown.

    The frontmatter carries every ``ParagraphEntry`` field except
    ``content_sha256`` (the body IS the content; the hash is recorded in
    the manifest, not duplicated per-file). The body is written as-is —
    Docling text is plain UTF-8 with no escape requirements at this layer.
    """
    payload: dict[str, Any] = entry.model_dump(mode="python")
    # ``content_sha256`` lives in the manifest, not the per-paragraph file.
    payload.pop("content_sha256", None)
    return _emit_md(payload, body)


def parse_paragraph_md(text: str) -> tuple[dict[str, Any], str]:
    """Parse a paragraph .md file back into (frontmatter, body).

    Returns the raw frontmatter dict (callers reconstruct
    ``ParagraphEntry`` by adding the recomputed ``content_sha256``) and
    the body text exactly as written.
    """
    payload = _parse_md(text, "_body")
    body = payload.pop("_body", "")
    if not isinstance(body, str):
        raise ValueError(f"paragraph body must be str, got {type(body).__name__}")
    return payload, body
