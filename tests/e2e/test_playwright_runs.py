"""Pytest hook that drives the Playwright @playwright/test E2E suite.

This single test shells out to ``npx playwright test`` from
``tests/e2e/`` and asserts exit code 0. It integrates the
Node/TypeScript Playwright suite into the existing pytest run via the
``e2e`` marker declared in ``pyproject.toml``::

    uv run --no-sync pytest -m e2e

Skips
-----
This test SKIPs (does NOT fail) when:

* ``npx`` is not on ``PATH`` (no Node toolchain).
* ``node_modules`` is missing under ``tests/e2e/`` (Playwright deps
  haven't been installed).
* The Playwright chromium browser is not installed.

In every skip path the message tells the operator how to recover. To
install everything once::

    cd tests/e2e
    npm install
    npx playwright install chromium

The skip-not-fail policy matters because not every CI runner has Node
(e.g. the docs-only CI lane); a missing Node toolchain MUST NOT break
``pytest -q`` for unrelated changes. The skip surfaces loudly enough
(via the ``e2e`` marker and a clear message) that a developer running
the full suite locally will notice and install the missing piece.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_NODE_MODULES = _THIS_DIR / "node_modules"
_PLAYWRIGHT_BIN = _NODE_MODULES / ".bin" / "playwright"
_SETUP_HINT = (
    "Install with:\n    cd tests/e2e\n    npm install\n    npx playwright install chromium"
)


def _has_chromium_installed() -> bool:
    """Return True iff Playwright's chromium browser is on disk.

    Playwright stores browsers at one of two cache locations depending
    on platform / env: ``$PLAYWRIGHT_BROWSERS_PATH`` if set, otherwise
    ``~/Library/Caches/ms-playwright`` on macOS or
    ``~/.cache/ms-playwright`` on Linux. We probe both and look for any
    ``chromium-*`` directory. This is a heuristic; the authoritative
    check would be ``playwright install --dry-run``, but that requires
    the npm package to be installed (which is a separate skip path).
    """
    candidates: list[Path] = []
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            Path.home() / "Library" / "Caches" / "ms-playwright",
            Path.home() / ".cache" / "ms-playwright",
        ]
    )
    for root in candidates:
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if entry.name.startswith("chromium-") and entry.is_dir():
                return True
    return False


@pytest.mark.e2e
def test_playwright_suite_runs() -> None:
    """Run the @playwright/test suite via npx; assert exit 0.

    Wrapped as a single pytest test so the existing ``e2e`` marker
    selects it. Streams the Playwright reporter output through the
    pytest capture (visible with ``pytest -s -m e2e``); on failure
    the captured stdout / stderr include the @playwright/test list
    reporter's failure block, which is usually enough to diagnose
    without re-running the suite directly.
    """
    if shutil.which("npx") is None:
        pytest.skip("npx not on PATH — Node toolchain required for the E2E suite.\n" + _SETUP_HINT)
    if not _NODE_MODULES.is_dir() or not _PLAYWRIGHT_BIN.exists():
        pytest.skip(
            "tests/e2e/node_modules missing (or @playwright/test not installed).\n" + _SETUP_HINT
        )
    if not _has_chromium_installed():
        pytest.skip("Playwright chromium browser not installed.\n" + _SETUP_HINT)

    # Use the locally-installed Playwright binary directly (faster +
    # avoids npx's network-resolution path). Forward CI / DEBUG env so
    # behaviour matches what the developer would see running the suite
    # directly.
    cmd = [str(_PLAYWRIGHT_BIN), "test"]
    completed = subprocess.run(
        cmd,
        cwd=str(_THIS_DIR),
        check=False,
        capture_output=True,
        text=True,
    )
    # Echo the reporter output so pytest's failure capture surfaces it.
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    assert completed.returncode == 0, (
        f"playwright test exited with {completed.returncode}; see captured "
        "output for failing specs."
    )
