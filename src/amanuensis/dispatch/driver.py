"""Harness CLI detection + role invocation (M6.2).

The dispatch driver subprocesses out to whichever harness CLI is
installed on the operator's machine. The Phase 1 plan calls out four
harnesses — Claude, Codex, Cursor, Gemini — each with its own
non-interactive invocation incantation:

============  =================  ==========================================
Harness       Binary             Non-interactive invocation
============  =================  ==========================================
``claude``    ``claude``         ``claude -p '<prompt>' < /dev/null``
``codex``     ``codex``          ``codex exec '<prompt>' < /dev/null``
``cursor``    ``cursor-agent``   ``cursor-agent --print '<prompt>' < /dev/null``
``gemini``    ``gemini``         ``gemini -p '<prompt>' < /dev/null``
============  =================  ==========================================

The ``< /dev/null`` redirect prevents the harness from blocking on stdin
when run from a non-interactive context. We achieve the same effect via
``subprocess.run(..., stdin=subprocess.DEVNULL)`` so no shell is involved
— the prompt is passed as a single argv element, side-stepping any
quoting / escaping pitfall a shell pipeline would introduce.

What this module is NOT
-----------------------
- It does NOT decide which role maps to which harness. That's a
  dispatch-loop configuration concern (``role_routes.yaml`` in a future
  milestone); M6.5's dispatch loop hard-codes ``extractor → claude``
  and ``auditor → claude`` for Phase 1.
- It does NOT enforce write-isolation. That's :mod:`isolation`'s job.
- It does NOT touch the queue / outputs / failures filesystem. Pure
  subprocess invocation + result parsing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

# Mapping of harness id → (binary basename, argv-prefix-builder). The
# builder receives the prompt and returns the full argv list. Keeping the
# table here makes it trivial to add a new harness (single entry).

_HARNESS_INVOCATIONS: dict[str, tuple[str, list[str]]] = {
    # Each tuple is (binary, leading-argv-without-prompt). The prompt is
    # always appended as the final argv element by ``_build_argv``.
    "claude": ("claude", ["-p"]),
    "codex": ("codex", ["exec"]),
    "cursor": ("cursor-agent", ["--print"]),
    "gemini": ("gemini", ["-p"]),
}


KNOWN_HARNESSES: frozenset[str] = frozenset(_HARNESS_INVOCATIONS.keys())
"""Phase 1's recognised harness ids. Stable surface for callers."""


# --- Detection --------------------------------------------------------


def detect_harnesses() -> dict[str, str | None]:
    """Probe ``$PATH`` for each known harness binary.

    Returns a dict keyed by the harness id (``"claude"`` / ``"codex"`` /
    ``"cursor"`` / ``"gemini"``) whose value is the absolute path to the
    binary (if installed) or ``None`` (if missing). Pure :func:`shutil.which`
    probe — no subprocess invocation.

    Stable across calls (no caching state); cheap enough to call once per
    ``amanuensis dispatch --check`` invocation.
    """
    out: dict[str, str | None] = {}
    for harness_id, (binary, _argv_prefix) in _HARNESS_INVOCATIONS.items():
        out[harness_id] = shutil.which(binary)
    return out


# --- Invocation -------------------------------------------------------


@dataclass(frozen=True)
class InvokeResult:
    """Outcome of one harness subprocess invocation.

    Fields:
        stdout: captured stdout (UTF-8 text).
        stderr: captured stderr (UTF-8 text).
        exit_code: process exit code; ``-1`` iff ``timed_out`` is True.
        walltime_seconds: monotonic wall-clock duration.
        timed_out: ``True`` iff the subprocess hit the timeout.
        output_payload: parsed structured output (dict) if stdout parsed
            cleanly as YAML / JSON, else ``None``.
        parse_error: human-readable parse-failure message if stdout
            could not be parsed; ``None`` on clean parse OR when no
            attempt was made (timeout / non-zero exit may set this to
            ``None`` because the parse simply wasn't attempted).
    """

    stdout: str
    stderr: str
    exit_code: int
    walltime_seconds: float
    timed_out: bool
    output_payload: dict[str, Any] | None
    parse_error: str | None


def _build_argv(harness: str, prompt: str) -> list[str]:
    """Build the subprocess argv for ``harness``.

    The first element is the harness binary's basename (resolved later
    by ``subprocess`` against ``$PATH``); the prefix entries from
    :data:`_HARNESS_INVOCATIONS` follow; the prompt is the final argv
    element. Single-arg prompt avoids any shell-quoting concern.
    """
    if harness not in _HARNESS_INVOCATIONS:
        raise ValueError(f"unknown harness {harness!r}; expected one of {sorted(KNOWN_HARNESSES)}")
    binary, prefix = _HARNESS_INVOCATIONS[harness]
    return [binary, *prefix, prompt]


def _parse_stdout(stdout: str) -> tuple[dict[str, Any] | None, str | None]:
    """Try YAML then JSON; return (payload, error_message).

    Stdout must parse to a top-level mapping. Anything else (scalar,
    list, parse error) yields ``(None, "...")``. We try YAML first
    because the project's existing on-disk formats are YAML — a harness
    that returns YAML stdout is the common case; JSON is a strict
    subset and round-trips through PyYAML cleanly, but trying JSON
    second keeps the error message specific when YAML fails on input
    that ISN'T even valid JSON.

    Empty stdout (no bytes after rstrip) yields ``(None, "...")`` so
    the dispatch driver can route to failures with a clear reason.
    """
    text = stdout.strip()
    if not text:
        return None, "stdout was empty"

    # Try YAML first. PyYAML accepts JSON too, so a clean parse here
    # handles both formats. ``safe_load`` rejects tags, which is what
    # we want for an untrusted subprocess.
    try:
        loaded: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        # Fall through to JSON to give a more specific error in the
        # common case where the harness emits JSON-with-bad-YAML-syntax.
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as json_exc:
            return None, f"stdout is neither valid YAML ({exc}) nor JSON ({json_exc})"

    if loaded is None:
        return None, "stdout parsed to null; expected a top-level mapping"
    if not isinstance(loaded, dict):
        return None, (f"stdout parsed to {type(loaded).__name__}; expected a top-level mapping")
    # Cast for static analysis: yaml/json typings widen to Any.
    return cast("dict[str, Any]", loaded), None


def invoke_role(
    *,
    harness: str,
    prompt: str,
    timeout_seconds: int = 600,
    harness_binary_path: Path | None = None,
    cwd: Path | None = None,
) -> InvokeResult:
    """Run the harness subprocess and return a structured result.

    Args:
        harness: harness id; one of :data:`KNOWN_HARNESSES`.
        prompt: prompt text. Passed as a single argv element (no shell).
        timeout_seconds: subprocess wall-clock limit. On expiry we return
            ``InvokeResult(timed_out=True, exit_code=-1, ...)`` rather
            than re-raising — the dispatch loop's contract is "every
            outcome is a routable result".
        harness_binary_path: TEST-ONLY injection seam. When provided,
            this path replaces the resolved harness binary. The dispatch
            driver's production code never passes this; the M6.4
            echo-role fixture uses it to point the invocation at a
            shell-script stand-in. The "TEST-ONLY" callout is the
            contract; the parameter exists because monkey-patching
            ``shutil.which`` at module scope is brittle in parallel
            pytest runs.
        cwd: working directory for the subprocess. Defaults to the
            current working directory; the dispatch loop passes the
            role's assigned output directory so any well-behaved
            harness that "writes near where it ran" lands inside the
            allowed subtree (M6.3 still enforces the harder guarantee).

    Returns:
        :class:`InvokeResult` describing stdout / stderr / exit / parse
        outcome.

    Behaviour notes:
        - ``stdin=DEVNULL`` mirrors the ``< /dev/null`` discipline in
          the harness table.
        - ``capture_output=True, text=True`` decodes stdout/stderr as
          UTF-8 strings.
        - Non-zero exit codes do NOT raise; the caller routes them.
        - Parse failures populate ``parse_error`` and leave
          ``output_payload=None``.
    """
    argv = _build_argv(harness, prompt)
    if harness_binary_path is not None:
        # Replace the binary name with the explicit path. The argv
        # tail (prefix + prompt) is preserved so a fixture script can
        # observe what the real harness would have seen.
        argv = [str(harness_binary_path), *argv[1:]]

    start = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
            cwd=str(cwd) if cwd is not None else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        # ``exc.stdout`` / ``exc.stderr`` are bytes-or-None on timeout.
        stdout_text = _decode_maybe(exc.stdout)
        stderr_text = _decode_maybe(exc.stderr)
        return InvokeResult(
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=-1,
            walltime_seconds=elapsed,
            timed_out=True,
            output_payload=None,
            parse_error=None,
        )
    except FileNotFoundError as exc:
        # Binary missing. The dispatch loop separately checks
        # ``detect_harnesses`` before invocation, so this is a defensive
        # path; return a structured result rather than crash.
        elapsed = time.monotonic() - start
        return InvokeResult(
            stdout="",
            stderr=f"{exc}",
            exit_code=127,
            walltime_seconds=elapsed,
            timed_out=False,
            output_payload=None,
            parse_error=None,
        )

    elapsed = time.monotonic() - start

    # Only attempt to parse stdout when the subprocess exited cleanly.
    # A non-zero exit means the harness itself reported failure; we
    # surface that as the routable signal rather than the parse error.
    payload: dict[str, Any] | None = None
    parse_error: str | None = None
    if completed.returncode == 0:
        payload, parse_error = _parse_stdout(completed.stdout)

    return InvokeResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        walltime_seconds=elapsed,
        timed_out=False,
        output_payload=payload,
        parse_error=parse_error,
    )


def _decode_maybe(blob: bytes | str | None) -> str:
    """Decode subprocess byte buffers (or pass-through strings) to text.

    ``TimeoutExpired.stdout`` is bytes when ``text=False`` and str when
    ``text=True``; we always run with ``text=True`` so the str branch is
    the common case, but the bytes branch is kept as defensive armor.
    """
    if blob is None:
        return ""
    if isinstance(blob, bytes):
        return blob.decode("utf-8", errors="replace")
    return blob
