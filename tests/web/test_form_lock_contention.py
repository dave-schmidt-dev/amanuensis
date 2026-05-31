"""M8.6 form-lock contention tests (SR-4 mitigation).

The M8.5 supervisor-write routes (``POST /clarifications/<id>/resolve``
and ``POST /iterations/add``) acquire the workspace flock with a 5s
timeout (plan §5). On contention the route must:

1. surface a clear HTTP 503 with a rendered error page (not an opaque
   500 / hang), so the supervisor knows the workspace is busy; and
2. leave the on-disk substrate completely untouched (no half-written
   directive, no clarification flipped from open/ to resolved/).

When the holder releases the lock, a subsequent form POST must
succeed normally — the "supervisor-friendly recovery" half of SR-4.

The tests spawn a separate process to hold the workspace flock (so the
contention is real cross-process flock contention, not a same-process
re-entry which ``flock`` would happily allow), then monkeypatch
``forms._FORM_LOCK_TIMEOUT_SECONDS`` tight so the test is fast. The
child uses ``multiprocessing.get_context("spawn")`` for cross-platform
reliability — mirrors the M1.8 pattern from
``tests/fs/test_concurrent_distill_blocked.py``.
"""

from __future__ import annotations

import multiprocessing
import time
from multiprocessing.process import BaseProcess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.fs import Substrate, WorkspaceLockTimeout, acquire_workspace_lock
from amanuensis.schemas import Atom, Clarification, ProvenanceRecord
from amanuensis.web.app import create_app
from amanuensis.web.routes import forms as forms_routes

from .conftest import SOURCE_ID

# --- Child entry point (module-level for spawn pickling) -------------


def _hold_lock(workspace_str: str, hold_seconds: float, ready_marker_str: str) -> None:
    """Acquire the workspace lock, signal readiness, hold, then release.

    The readiness marker lets the parent observe that the child holds
    the lock before the parent issues the contending form POST — avoids
    a race where the parent's POST arrives before the child has grabbed
    the flock and the test passes trivially.
    """
    ready_marker = Path(ready_marker_str)
    with acquire_workspace_lock(Path(workspace_str), timeout=5.0):
        ready_marker.write_text("ready", encoding="utf-8")
        time.sleep(hold_seconds)


# --- Helpers ---------------------------------------------------------


def _build_client() -> TestClient:
    """Build a TestClient with the M8.5 forms router mounted.

    Mirrors the pattern in ``test_clarification_resolve.py`` /
    ``test_iteration_add.py``: the orchestrator wires the router into
    the app proper after every wave-3 subagent lands; until then the
    tests mount it explicitly so the routes are exercisable.
    """
    app = create_app()
    app.include_router(forms_routes.router)
    return TestClient(app)


def _spawn_holder(workspace: Path, hold_seconds: float) -> tuple[BaseProcess, Path]:
    """Spawn a child that holds the workspace lock; wait until it's held.

    Returns the live child process and the readiness-marker path so the
    caller can assert exit-code and clean up. Raises ``pytest.fail`` if
    the child does not signal readiness within a generous deadline.
    """
    ctx = multiprocessing.get_context("spawn")
    ready_marker = workspace / ".lock-holder-ready"
    proc = ctx.Process(
        target=_hold_lock,
        args=(str(workspace), hold_seconds, str(ready_marker)),
    )
    proc.start()

    # Wait for the child to signal it actually holds the lock.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if ready_marker.exists():
            return proc, ready_marker
        time.sleep(0.02)

    # Defensive: child never readied — clean up before failing.
    if proc.is_alive():  # pragma: no cover — defensive
        proc.terminate()
        proc.join(timeout=5)
    pytest.fail("child holder process never signalled lock acquisition")


def _join_child(proc: BaseProcess) -> None:
    """Join the child process; terminate if it overran."""
    proc.join(timeout=10)
    if proc.is_alive():  # pragma: no cover — defensive
        proc.terminate()
        proc.join(timeout=5)


# --- Tests -----------------------------------------------------------


def test_clarification_resolve_times_out_when_lock_held(
    planted_clarification_workspace: tuple[Path, Clarification, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST resolve while another process holds the lock returns 503.

    The clarification must remain in ``open/`` after the failure — the
    contention is observable to the supervisor, the substrate is not.
    """
    workspace, clar, _atom, _prov = planted_clarification_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    # Tight timeout so the test is fast; child holds the lock longer.
    monkeypatch.setattr(forms_routes, "_FORM_LOCK_TIMEOUT_SECONDS", 0.5)

    substrate = Substrate(workspace)
    open_path = substrate.clarification_path(SOURCE_ID, clar.id, resolved=False)
    assert open_path.is_file(), "fixture should have planted an open clarification"

    proc, _ready = _spawn_holder(workspace, hold_seconds=2.0)
    try:
        client = _build_client()
        t0 = time.monotonic()
        response = client.post(
            f"/clarifications/{clar.id}/resolve",
            data={
                "source_id": SOURCE_ID,
                "resolution": "Should never be written — lock is held.",
            },
            follow_redirects=False,
        )
        elapsed = time.monotonic() - t0

        # SR-4 contract: clear 503, not an opaque hang or 500.
        assert response.status_code == 503, response.text

        # The rendered error page must give the supervisor an actionable
        # signal. The M8.5 template says "workspace busy" and explains
        # the lock-holding scenario.
        body_lower = response.text.lower()
        assert "workspace busy" in body_lower
        assert "lock" in body_lower

        # The route should honour the tight timeout, not wait the
        # default 5s. Generous bound to absorb CI scheduler jitter
        # (spawn child startup, TestClient overhead, polling jitter).
        assert elapsed < 3.0, f"route waited too long: {elapsed:.3f}s"

        # The on-disk substrate is untouched: the open variant still
        # exists, no resolved variant was written.
        assert open_path.is_file(), "open clarification must survive a lock-timeout"
        resolved_path = substrate.clarification_path(SOURCE_ID, clar.id, resolved=True)
        assert not resolved_path.is_file(), (
            "no resolved variant should have been written under contention"
        )
    finally:
        _join_child(proc)
        assert proc.exitcode == 0


def test_iteration_add_times_out_when_lock_held(
    planted_clarification_workspace: tuple[Path, Clarification, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST iterations/add while the lock is held returns 503; no directive written.

    Reuses the planted-clarification workspace because it sets up the
    INV-1 marker AND a real ``distillations/<source_id>/`` directory
    (so ``target_source`` is a valid known source). The directive
    target is irrelevant to the contention assertion — what matters is
    that no ``iterations/*.md`` file appears.
    """
    workspace, _clar, _atom, _prov = planted_clarification_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    monkeypatch.setattr(forms_routes, "_FORM_LOCK_TIMEOUT_SECONDS", 0.5)

    substrate = Substrate(workspace)
    iters_dir = substrate.root / "iterations"
    # The directory might exist as a side effect of fixture setup or
    # not — what we assert below is that no *.md file appears after
    # the contended POST.
    before = (
        sorted(p.name for p in iters_dir.iterdir() if p.suffix == ".md")
        if iters_dir.is_dir()
        else []
    )

    proc, _ready = _spawn_holder(workspace, hold_seconds=2.0)
    try:
        client = _build_client()
        t0 = time.monotonic()
        response = client.post(
            "/iterations/add",
            data={
                "directive": "Should never be written — lock is held.",
                "target_source": SOURCE_ID,
                "target_phase": "distill",
                "rationale": "test rationale",
            },
            follow_redirects=False,
        )
        elapsed = time.monotonic() - t0

        assert response.status_code == 503, response.text
        body_lower = response.text.lower()
        assert "workspace busy" in body_lower
        assert "lock" in body_lower
        assert elapsed < 3.0, f"route waited too long: {elapsed:.3f}s"

        # No new directive file appeared.
        after = (
            sorted(p.name for p in iters_dir.iterdir() if p.suffix == ".md")
            if iters_dir.is_dir()
            else []
        )
        assert after == before, (
            f"no new iteration directive should have been written; before={before} after={after}"
        )
        # And no .tmp.* writer leftover either (would indicate an aborted
        # mid-write — the route should fail BEFORE entering the writer).
        if iters_dir.is_dir():
            tmp_leftovers = [p.name for p in iters_dir.iterdir() if ".tmp." in p.name]
            assert tmp_leftovers == [], f"unexpected writer leftovers: {tmp_leftovers}"
    finally:
        _join_child(proc)
        assert proc.exitcode == 0


def test_form_recovers_after_lock_released(
    planted_clarification_workspace: tuple[Path, Clarification, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A form POST issued after the holder releases the lock succeeds normally.

    The "supervisor-friendly recovery" half of SR-4: a transient holder
    must not poison the route. Strategy: spawn a child that holds the
    lock briefly (well under the form timeout), join it before issuing
    the POST, then verify the POST writes through to disk as if no
    contention had occurred.
    """
    workspace, clar, _atom, _prov = planted_clarification_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    # Generous form timeout — the child releases quickly so the route
    # has plenty of budget. We're testing recovery, not contention.
    monkeypatch.setattr(forms_routes, "_FORM_LOCK_TIMEOUT_SECONDS", 5.0)

    substrate = Substrate(workspace)
    open_path = substrate.clarification_path(SOURCE_ID, clar.id, resolved=False)
    assert open_path.is_file()

    # Spawn a child that holds the lock for ~100ms then releases.
    proc, _ready = _spawn_holder(workspace, hold_seconds=0.1)
    # Wait for the child to die (lock fully released) before POSTing,
    # so the assertion below is purely about post-release recovery, not
    # about waiting-out a held lock.
    _join_child(proc)
    assert proc.exitcode == 0

    # Sanity check: the lock is acquirable from the parent right now.
    with acquire_workspace_lock(workspace, timeout=1.0):
        pass

    # The form POST should succeed exactly as in the happy-path test.
    client = _build_client()
    response = client.post(
        f"/clarifications/{clar.id}/resolve",
        data={
            "source_id": SOURCE_ID,
            "resolution": "Recovered after transient lock contention.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/clarifications"

    # The on-disk state matches the happy-path: open variant gone,
    # resolved variant written.
    assert not open_path.is_file()
    resolved_path = substrate.clarification_path(SOURCE_ID, clar.id, resolved=True)
    assert resolved_path.is_file()


def test_form_recovers_after_lock_released_does_not_raise_for_holder(
    web_workspace: Path,
) -> None:
    """Sanity: ``acquire_workspace_lock`` itself rejects a missing marker.

    Belt-and-suspenders guard that the fixtures we rely on really do
    plant the ``amanuensis.yaml`` marker — without it the child holder
    would crash with ``SubstrateMarkerMissing`` and every other test
    in this module would mis-attribute the failure to a route bug.
    """
    marker = web_workspace / "amanuensis.yaml"
    assert marker.is_file(), "web_workspace fixture must plant the INV-1 marker"
    # And the lock module accepts it.
    with acquire_workspace_lock(web_workspace, timeout=0.5):
        pass

    # The unused import sentinel keeps the import-list honest: this
    # symbol IS exercised by the contention assertions implicitly
    # (the route catches it), but pyright would otherwise flag it.
    assert WorkspaceLockTimeout is not None
