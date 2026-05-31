"""M11.3 — invariants-charter integrity gate.

`INVARIANTS.md` is the project's source of truth for foundational
properties. This gate enforces three drift-prevention contracts on the
charter:

1.  **Every ``## INV-N`` heading has a parseable ``Gate test:`` bullet.**
    The bullet may be qualified (``Gate test (partial):`` /
    ``Gate test (planned, not yet shipped):`` / etc.), and may contain
    multiple referenced paths (INV-1 references both an `fs/` and a
    `cli/` surface test). The discipline is "every invariant declares
    what — if anything — gates it".
2.  **Every ``tests/...`` path mentioned in a gate-test bullet exists
    on disk.** This catches drift in the charter direction: an
    invariant whose gate-test file was renamed, moved, or never
    created.
3.  **Every ``tests/invariants/test_*.py`` file is referenced by some
    INV-N's gate-test bullet.** This catches drift in the test-suite
    direction: a gate test added without a corresponding INV entry
    (which would mean either the test enforces an undocumented
    invariant, or the test should have lived elsewhere).

Charter entries explicitly marked as having no executable gate (the
gate-test bullet says ``None``, e.g. INV-9's scope contract) are
honoured: they satisfy contract #1 by declaring the absence, and they
do not need to satisfy contract #2 because no paths are extracted.
A pytest warning surfaces these so reviewers can see them in the
test output without failing the build — Phase 2 may convert some of
them to executable gates.

This file deliberately lives under ``tests/docs/`` rather than
``tests/invariants/``: it is a documentation-discipline gate on the
charter itself, not an INV-N gate on substrate behaviour. Adding it
to ``tests/invariants/`` would create a recursion (contract #3 would
need to find an INV entry referencing this file).
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest

# Resolve repo root: tests/docs/test_X.py -> tests/docs/ -> tests/ -> repo
REPO_ROOT = Path(__file__).resolve().parents[2]
INVARIANTS_MD = REPO_ROOT / "INVARIANTS.md"
INVARIANTS_TEST_DIR = REPO_ROOT / "tests" / "invariants"

# Heading shape: ``## INV-<id> — <title>``. The em dash is the canonical
# separator (matches the INVARIANTS.md current content); a plain hyphen
# is accepted as a fallback for resilience.
_HEADING_RE = re.compile(r"^##\s+(?P<id>INV-\d+)\b", re.MULTILINE)

# Gate-test bullet. Matches the canonical ``- **Gate test:**`` plus the
# qualified variants used in the charter (``Gate test (partial):``,
# ``Gate test (planned, not yet shipped):``, ``Gate test (active):``).
# Captures the qualifier (the parenthetical, if any) AND everything
# after the closing ``**`` up to (but not including) the next top-level
# bullet (``\n- **``) or the next ``## INV-`` heading or EOF. Keeping
# the qualifier inside ``body`` is load-bearing: the "no executable
# gate yet" phrase detection (``_NO_GATE_PHRASES``) needs to see
# qualifiers like ``(planned, not yet shipped)``.
_GATE_TEST_BLOCK_RE = re.compile(
    r"^- \*\*Gate test(?P<qualifier>[^*]*)\*\*\s*(?P<rest>.*?)"
    r"(?=^- \*\*|^## INV-|\Z)",
    re.MULTILINE | re.DOTALL,
)

# Path extraction from inside a gate-test body. We accept anything that
# starts with ``tests/`` and ends at the first whitespace, backtick, or
# closing-paren character. Backticks (``tests/invariants/foo.py``) are
# the dominant style; bare paths are tolerated for resilience.
_TEST_PATH_RE = re.compile(r"(?:`)?(tests/[A-Za-z0-9_./-]+\.py)(?:`)?")

# Phrases that, when found in a gate-test body, mean "this invariant
# has no executable gate yet — that is intentional, do not require any
# tests/ paths to be resolvable". The match is case-insensitive and
# substring-based; precision is not the point, surfacing the gap is.
_NO_GATE_PHRASES = (
    "None in Phase 1",
    "planned, not yet shipped",
    "no automated scan yet",
)


def _inv_id_label(value: object) -> str:
    """pytest parametrize ``ids`` callback: render only the INV-N id
    portion of a (inv_id, body) tuple so test ids stay readable.
    """
    if isinstance(value, str) and value.startswith("INV-"):
        return value
    return ""


def _split_invariants(text: str) -> list[tuple[str, str]]:
    """Return ``[(inv_id, body), ...]`` for every INV-N section.

    ``body`` is the text from just after the heading line up to (but
    not including) the next ``## INV-`` heading or end-of-file.
    """
    matches = list(_HEADING_RE.finditer(text))
    sections: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections.append((match.group("id"), text[start:end]))
    return sections


def _gate_test_block(section_body: str) -> str | None:
    """Return the gate-test bullet body (qualifier + rest) for one INV
    section, or None.

    None means the section is missing a ``- **Gate test...:**`` bullet
    altogether — that's a contract #1 violation. The returned string
    concatenates the parenthetical qualifier (if any) with the bullet
    body so phrase detection sees both halves.
    """
    match = _GATE_TEST_BLOCK_RE.search(section_body)
    if match is None:
        return None
    qualifier = match.group("qualifier") or ""
    rest = match.group("rest") or ""
    return (qualifier + " " + rest).strip()


def _extract_test_paths(gate_test_body: str) -> list[str]:
    """Return every ``tests/...`` path mentioned in a gate-test body."""
    return _TEST_PATH_RE.findall(gate_test_body)


def _declares_no_gate(gate_test_body: str) -> bool:
    """Return True if this gate-test body explicitly declares 'no gate yet'."""
    haystack = gate_test_body.lower()
    return any(phrase.lower() in haystack for phrase in _NO_GATE_PHRASES)


@pytest.fixture(scope="module")
def invariants_text() -> str:
    assert INVARIANTS_MD.is_file(), f"missing charter at {INVARIANTS_MD}"
    return INVARIANTS_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def invariant_sections(invariants_text: str) -> list[tuple[str, str]]:
    sections = _split_invariants(invariants_text)
    assert sections, "INVARIANTS.md has no '## INV-N' headings"
    return sections


def test_invariants_md_exists_and_has_entries(
    invariant_sections: list[tuple[str, str]],
) -> None:
    """Sanity check: charter exists and has at least the Phase 1 set
    of invariants. Guards against the parametric tests below silently
    passing on an empty parse.
    """
    # Phase 1 ships 11 INV entries (INV-1..INV-11). If the charter
    # drops below this, something is structurally wrong; we don't pin
    # the exact count because Phase 2 may add more.
    assert len(invariant_sections) >= 11, (
        f"INVARIANTS.md has only {len(invariant_sections)} entries; "
        "Phase 1 established at least 11. Did a section get truncated?"
    )
    ids = [inv_id for inv_id, _ in invariant_sections]
    # IDs should be unique.
    assert len(ids) == len(set(ids)), f"duplicate INV ids: {ids}"


@pytest.mark.parametrize(
    "inv_id,section_body",
    _split_invariants(INVARIANTS_MD.read_text(encoding="utf-8")),
    ids=_inv_id_label,
)
def test_each_invariant_has_gate_test_bullet(inv_id: str, section_body: str) -> None:
    """Contract #1: every INV-N section declares a Gate test bullet.

    The bullet may declare 'None' or 'planned' (handled below) — we
    just require the bullet exist so the charter never silently omits
    its enforcement story.
    """
    body = _gate_test_block(section_body)
    assert body is not None, (
        f"{inv_id} is missing a '- **Gate test...:**' bullet. Every "
        "invariant must declare what enforces it (even if the declaration "
        "is 'None — scope contract', as in INV-9)."
    )


@pytest.mark.parametrize(
    "inv_id,section_body",
    _split_invariants(INVARIANTS_MD.read_text(encoding="utf-8")),
    ids=_inv_id_label,
)
def test_each_invariant_gate_test_paths_exist(inv_id: str, section_body: str) -> None:
    """Contract #2: every ``tests/...`` path in a gate-test bullet exists.

    INV entries that explicitly declare 'no gate' (per ``_NO_GATE_PHRASES``)
    are honoured: they may reference future test paths in passing, but
    those paths are not required to exist yet. A pytest warning surfaces
    the gap.
    """
    body = _gate_test_block(section_body)
    # Contract #1 has its own test; if the bullet is missing entirely we
    # don't double-report here.
    if body is None:
        pytest.skip(f"{inv_id} has no gate-test bullet (covered by contract #1)")
        return  # unreachable; satisfies type narrowing for ``body``

    paths = _extract_test_paths(body)
    no_gate = _declares_no_gate(body)

    if no_gate:
        # Surface the gap in pytest output without failing.
        warnings.warn(
            f"{inv_id} declares no executable gate yet "
            f"(matched a 'no-gate' phrase). Referenced paths "
            f"({paths!r}) are NOT required to exist.",
            UserWarning,
            stacklevel=1,
        )
        return

    assert paths, (
        f"{inv_id} has a Gate test bullet but no parseable ``tests/...`` "
        "path. Either reference the gate test file by relative path "
        "(e.g. ``tests/invariants/test_foo.py``) or mark the invariant "
        "as having no executable gate using one of "
        f"{_NO_GATE_PHRASES!r}."
    )

    missing: list[str] = []
    for rel in paths:
        resolved = REPO_ROOT / rel
        if not resolved.is_file():
            missing.append(rel)
    assert not missing, (
        f"{inv_id} references gate-test paths that do not exist on disk: "
        f"{missing!r}. Either ship the gate test, update the path in "
        "INVARIANTS.md, or mark the invariant as planned."
    )


def test_no_orphan_invariant_gate_tests(
    invariant_sections: list[tuple[str, str]],
) -> None:
    """Contract #3: every ``tests/invariants/test_*.py`` file is referenced
    by some INV-N's gate-test bullet.

    Drift in this direction means: someone shipped a gate test under
    ``tests/invariants/`` without adding (or updating) an INV entry to
    reference it. Either the test belongs elsewhere (e.g. under
    ``tests/validators/`` if it's a per-validator test), or the
    INVARIANTS.md charter needs an entry.

    Helpers (``conftest.py``, ``_types.py``, ``__init__.py``) are
    excluded — only ``test_*.py`` files are policed.
    """
    if not INVARIANTS_TEST_DIR.is_dir():
        pytest.skip(f"no {INVARIANTS_TEST_DIR} directory yet")

    on_disk = {f"tests/invariants/{p.name}" for p in INVARIANTS_TEST_DIR.glob("test_*.py")}
    if not on_disk:
        pytest.skip("no test_*.py files under tests/invariants/")

    referenced: set[str] = set()
    for _, section_body in invariant_sections:
        body = _gate_test_block(section_body)
        if body is None:
            continue
        for rel in _extract_test_paths(body):
            referenced.add(rel)

    orphans = sorted(on_disk - referenced)
    assert not orphans, (
        f"the following tests/invariants/ files are not referenced by any "
        f"INV-N's gate-test bullet in INVARIANTS.md: {orphans!r}. Either "
        "add an INV entry that references the file or move the test "
        "out of tests/invariants/."
    )
