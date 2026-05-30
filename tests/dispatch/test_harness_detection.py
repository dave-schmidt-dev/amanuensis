"""Harness CLI detection tests (M6.2).

Pure ``shutil.which`` probe. We don't assert any specific harness is
present (test runners vary), only that the API shape is honest: all
four keys present, each value is either ``None`` or a string-typed
absolute path.
"""

from __future__ import annotations

from amanuensis.dispatch.driver import KNOWN_HARNESSES, detect_harnesses


def test_detect_harnesses_returns_all_known_keys() -> None:
    """API contract: keys are exactly the four Phase-1 harness ids."""
    detected = detect_harnesses()
    assert set(detected.keys()) == set(KNOWN_HARNESSES)


def test_detect_harnesses_values_are_path_or_none() -> None:
    """Each value is either None or a non-empty string path."""
    detected = detect_harnesses()
    for harness, value in detected.items():
        assert value is None or isinstance(value, str), (
            f"{harness}: expected None or str, got {type(value).__name__}"
        )
        if isinstance(value, str):
            assert value, f"{harness}: empty string is not a valid path"


def test_known_harnesses_contains_phase1_set() -> None:
    """Documents the Phase-1 contract: claude, codex, cursor, gemini."""
    assert KNOWN_HARNESSES == frozenset({"claude", "codex", "cursor", "gemini"})
