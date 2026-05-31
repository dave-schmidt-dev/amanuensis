"""M10.1 — documentation cross-link + Known Limitations discipline gate.

Two checks, both parametric over every ``docs/*.md`` file:

1. ``test_no_dead_relative_links`` — extracts every markdown link of the
   shape ``[text](path)`` from each doc; for every link whose ``path``
   is a relative file path (not ``http``/``https``/``mailto`` and not a
   bare in-page anchor like ``#section``), asserts the target file
   exists when resolved relative to the doc's parent directory. Anchor
   suffixes (``./foo.md#section``) are stripped before existence is
   checked.

2. ``test_known_limitations_section_present`` — asserts every
   ``docs/*.md`` file carries a header matching
   ``r"^#{1,3}\\s+Known\\s+[Ll]imitations\\b"`` somewhere in the body.
   The trailing ``\\b`` (rather than ``$``) accommodates the existing
   doc convention of optionally pinning a milestone or phase in the
   header (e.g. ``## Known Limitations (Phase 1)``); a strict
   end-of-line anchor would force a non-essential rewrite. The
   discipline this gate enforces is "every doc declares its
   limitations", not "every doc uses the exact same trailing
   formatting".

Scope is intentionally narrow: this is a documentation-discipline gate
(M10.1), not a markdown linter. It does not validate anchor targets
within a doc, does not check link text, and does not enforce a
particular style for cross-links beyond existence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Resolve docs/ relative to this test file. tests/docs/ -> tests/ -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"

# Markdown link regex: matches `[text](target)` where target is a
# non-empty run of characters that does NOT include a closing paren or
# whitespace. This is intentionally simple — the docs in this project do
# not use the ``[text](url "title")`` form or escaped parens inside
# targets, so a stricter parser would not earn its complexity.
_MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<target>[^)\s]+)\)")

_KNOWN_LIMITATIONS_HEADER_RE = re.compile(
    r"^#{1,3}\s+Known\s+[Ll]imitations\b",
    re.MULTILINE,
)


def _docs_files() -> list[Path]:
    """Return every ``docs/*.md`` file (sorted for deterministic IDs)."""
    return sorted(DOCS_DIR.glob("*.md"))


def _is_external(target: str) -> bool:
    """A link is external when it carries a recognised URL scheme.

    Used to skip ``http://``, ``https://``, ``mailto:``, and the like
    when validating relative file targets.
    """
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target))


def _strip_anchor(target: str) -> str:
    """Return ``target`` with any ``#anchor`` suffix removed.

    ``./foo.md#section`` becomes ``./foo.md``. A bare ``#section`` (no
    file portion) collapses to the empty string — the caller treats
    that as an in-page link and skips file existence checking.
    """
    return target.split("#", 1)[0]


@pytest.fixture(scope="module")
def docs_files() -> list[Path]:
    return _docs_files()


def test_docs_directory_has_markdown_files(docs_files: list[Path]) -> None:
    """Sanity check: the docs directory exists and has at least one
    markdown file. Guards against the parametric tests below silently
    passing on an empty corpus.
    """
    assert DOCS_DIR.is_dir(), f"missing docs directory at {DOCS_DIR}"
    assert docs_files, f"no *.md files under {DOCS_DIR}"


@pytest.mark.parametrize("doc_path", _docs_files(), ids=lambda p: p.name)
def test_no_dead_relative_links(doc_path: Path) -> None:
    """Every relative-file markdown link in this doc must resolve to
    an existing file. External links and in-page anchors are skipped.
    """
    text = doc_path.read_text(encoding="utf-8")
    dead: list[tuple[str, Path]] = []
    for match in _MD_LINK_RE.finditer(text):
        target = match.group("target")
        if _is_external(target):
            continue
        file_part = _strip_anchor(target)
        if not file_part:
            # Bare in-page anchor (e.g. ``#known-limitations``); we do
            # not validate anchor targets here.
            continue
        resolved = (doc_path.parent / file_part).resolve()
        if not resolved.exists():
            dead.append((target, resolved))
    assert not dead, f"dead relative links in {doc_path.name}:\n" + "\n".join(
        f"  [...]({target}) -> {resolved}" for target, resolved in dead
    )


@pytest.mark.parametrize("doc_path", _docs_files(), ids=lambda p: p.name)
def test_known_limitations_section_present(doc_path: Path) -> None:
    """Every docs/*.md file must carry a `Known Limitations` header
    somewhere in the body. This is a documentation-discipline gate —
    it forces authors to surface the scope cuts that apply to each
    surface rather than letting them drift undocumented.
    """
    text = doc_path.read_text(encoding="utf-8")
    assert _KNOWN_LIMITATIONS_HEADER_RE.search(text), (
        f"{doc_path.name} is missing a 'Known Limitations' section header "
        "matching the discipline gate regex "
        "'^#{1,3}\\s+Known\\s+[Ll]imitations\\b'."
    )
