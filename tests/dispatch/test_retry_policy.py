"""``invoke_role`` outcome / parsing tests (M6.2).

Covers the four routable outcomes a harness subprocess can produce:

1. Successful exit + parseable stdout → ``output_payload`` populated.
2. Successful exit + garbage stdout → ``parse_error`` set, payload None.
3. Non-zero exit → exit_code surfaced; no parse attempted.
4. Timeout → ``timed_out=True``, exit_code -1, no re-raise.

Tests monkey-patch :func:`subprocess.run` so they don't depend on any
harness CLI actually being installed.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from typing import Any

import pytest

from amanuensis.dispatch import driver
from amanuensis.dispatch.driver import invoke_role


class _FakeCompleted:
    """Stand-in for ``subprocess.CompletedProcess`` (we only need three fields)."""

    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Yield a state dict; tests fill in ``state['result']`` or ``state['raise']``."""
    state: dict[str, Any] = {}

    def _fake(*args: Any, **kwargs: Any) -> _FakeCompleted:
        _ = args, kwargs
        if state.get("raise") is not None:
            raise state["raise"]
        return state["result"]

    monkeypatch.setattr(driver.subprocess, "run", _fake)
    yield state


def test_successful_exit_with_yaml_stdout(fake_run: dict[str, Any]) -> None:
    """Clean exit + valid YAML mapping ⇒ output_payload populated."""
    fake_run["result"] = _FakeCompleted(
        returncode=0,
        stdout="atoms:\n  - id: a-1\n    predicate: p\nfindings: []\n",
    )
    result = invoke_role(harness="claude", prompt="extract")
    assert result.exit_code == 0
    assert not result.timed_out
    assert result.output_payload == {
        "atoms": [{"id": "a-1", "predicate": "p"}],
        "findings": [],
    }
    assert result.parse_error is None


def test_successful_exit_with_json_stdout(fake_run: dict[str, Any]) -> None:
    """JSON is a YAML subset; safe-load handles it cleanly."""
    fake_run["result"] = _FakeCompleted(
        returncode=0,
        stdout='{"atoms": [], "findings": []}',
    )
    result = invoke_role(harness="claude", prompt="extract")
    assert result.exit_code == 0
    assert result.output_payload == {"atoms": [], "findings": []}


def test_successful_exit_with_garbage_stdout(fake_run: dict[str, Any]) -> None:
    """Unparseable stdout ⇒ parse_error set, payload None."""
    fake_run["result"] = _FakeCompleted(
        returncode=0,
        stdout="this is not yaml: : : ::: nor json",
    )
    result = invoke_role(harness="claude", prompt="extract")
    assert result.exit_code == 0
    assert result.output_payload is None
    assert result.parse_error is not None


def test_successful_exit_with_non_mapping_stdout(fake_run: dict[str, Any]) -> None:
    """A YAML list at the top-level is not a mapping ⇒ parse_error."""
    fake_run["result"] = _FakeCompleted(
        returncode=0,
        stdout="- item-1\n- item-2\n",
    )
    result = invoke_role(harness="claude", prompt="extract")
    assert result.output_payload is None
    assert result.parse_error is not None
    assert "mapping" in result.parse_error


def test_successful_exit_with_empty_stdout(fake_run: dict[str, Any]) -> None:
    """Empty stdout ⇒ parse_error, payload None."""
    fake_run["result"] = _FakeCompleted(returncode=0, stdout="")
    result = invoke_role(harness="claude", prompt="extract")
    assert result.output_payload is None
    assert result.parse_error is not None


def test_nonzero_exit_captures_code(fake_run: dict[str, Any]) -> None:
    """Non-zero exit ⇒ exit_code surfaced; no parse attempted."""
    fake_run["result"] = _FakeCompleted(
        returncode=1,
        stdout="",
        stderr="something broke",
    )
    result = invoke_role(harness="claude", prompt="extract")
    assert result.exit_code == 1
    assert not result.timed_out
    assert result.output_payload is None
    assert result.parse_error is None  # Not attempted on non-zero exit.
    assert "something broke" in result.stderr


def test_timeout_returns_timed_out_result(fake_run: dict[str, Any]) -> None:
    """``TimeoutExpired`` ⇒ structured result, not a re-raise."""
    fake_run["raise"] = subprocess.TimeoutExpired(cmd=["claude"], timeout=1)
    result = invoke_role(harness="claude", prompt="extract", timeout_seconds=1)
    assert result.timed_out is True
    assert result.exit_code == -1
    assert result.output_payload is None


def test_unknown_harness_raises_value_error() -> None:
    """An unknown harness id is a programming error → ValueError fast."""
    with pytest.raises(ValueError, match="unknown harness"):
        invoke_role(harness="not-a-harness", prompt="p")


def test_file_not_found_returns_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing binary surfaces as exit_code 127, not a crash."""

    def _missing(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("claude: not on path")

    monkeypatch.setattr(driver.subprocess, "run", _missing)
    result = invoke_role(harness="claude", prompt="p")
    assert result.exit_code == 127
    assert not result.timed_out
    assert "claude: not on path" in result.stderr
